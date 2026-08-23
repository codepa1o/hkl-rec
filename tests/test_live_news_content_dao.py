from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.live_news.allowlist import load_allowlist
from backend.app.live_news.content_dao import (
    PostgresLiveContentStore,
    claim_due_content_jobs,
    complete_content_job,
    ensure_content_job,
    finish_content_job,
    retry_content_job,
)
from backend.app.live_news.content_document import (
    ImageBlock,
    ParagraphBlock,
    StructuredBodyDocument,
)
from backend.app.live_news.content_policy import ContentPolicy
from backend.app.live_news.content_types import AcquiredContent, ContentJob, ContentRequest

NOW = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
ARTICLE_ID = "L0123456789abcdef0123456789abcdef"
BLOCKED_ARTICLE_ID = "L11111111111111111111111111111111"


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.cursor_value = FakeCursor(rows)
        self.transaction_entries = 0
        self.closed = False

    @contextmanager
    def transaction(self):
        self.transaction_entries += 1
        yield

    def cursor(self) -> FakeCursor:
        return self.cursor_value

    def close(self) -> None:
        self.closed = True


def test_ensure_content_job_keeps_link_only_article_metadata_only() -> None:
    connection = FakeConnection()

    ensure_content_job(
        connection,
        ARTICLE_ID,
        ContentPolicy("link_only", "link_only"),
        now=NOW,
    )

    statements = "\n".join(sql for sql, _params in connection.cursor_value.executed)
    assert "body_status = 'metadata_only'" in statements
    assert "DELETE FROM live_news_content_job" in statements
    assert "INSERT INTO live_news_content_job" not in statements


def test_ensure_content_job_inserts_one_pending_eligible_job() -> None:
    connection = FakeConnection()

    ensure_content_job(
        connection,
        ARTICLE_ID,
        ContentPolicy("html", "full_text"),
        now=NOW,
    )

    statements = "\n".join(sql for sql, _params in connection.cursor_value.executed)
    assert "ELSE 'pending'" in statements
    assert "INSERT INTO live_news_content_job" in statements
    assert "ON CONFLICT (article_id) DO UPDATE" in statements
    assert "target_extraction_version = 'structured-1'" in statements
    assert connection.cursor_value.executed[0][1] == ("full_text", ARTICLE_ID)
    assert (ARTICLE_ID, NOW) in [params for _sql, params in connection.cursor_value.executed]
    assert connection.cursor_value.executed[-1][1] == (ARTICLE_ID,)


def test_claim_due_content_jobs_attaches_current_source_policy(tmp_path: Path) -> None:
    config = tmp_path / "sources.json"
    config.write_text(
        '{"sources":[{"domain":"example.com","languages":["en"],'
        '"quality_weight":0.8,"content":{"mode":"html","display":"full_text",'
        '"feed_urls":[]}}]}',
        encoding="utf-8",
    )
    allowlist = load_allowlist(config)
    connection = FakeConnection(
        [
            {
                "article_id": ARTICLE_ID,
                "canonical_url": "https://news.example.com/story",
                "source_domain": "news.example.com",
                "language": "en",
                "content_rights": "full_text",
                "attempt_count": 1,
            }
        ]
    )

    jobs = claim_due_content_jobs(
        connection,
        allowlist,
        worker_id="worker-1",
        limit=10,
        now=NOW,
    )

    assert len(jobs) == 1
    assert jobs[0].request.policy.mode == "html"
    assert jobs[0].request.expected_domain == "example.com"
    assert jobs[0].attempt_count == 1


def test_completion_persists_document_and_image_metadata_in_the_same_transaction() -> None:
    connection = FakeConnection()
    document = StructuredBodyDocument(
        extraction_version="structured-1",
        source="html",
        blocks=[
            ParagraphBlock(id="p-1", text="A complete paragraph."),
            ImageBlock(
                id="img-1",
                asset_id="asset-1",
                source_url="https://images.example.com/photo.jpg",
                display_url="https://images.example.com/photo.jpg",
                alt="Photo",
                caption="Caption",
                credit="Photograph: Example",
                width=1200,
                height=800,
                mime_type="image/jpeg",
                cache_status="remote_only",
            ),
        ],
    )
    job = ContentJob(
        article_id=ARTICLE_ID,
        request=ContentRequest(
            article_id=ARTICLE_ID,
            canonical_url="https://example.com/story",
            expected_domain="example.com",
            language="en",
            policy=ContentPolicy("html", "full_text"),
        ),
        content_rights="full_text",
        attempt_count=1,
    )

    complete_content_job(
        connection,
        job,
        AcquiredContent(
            source="html",
            body_text="A complete paragraph.",
            fetched_at=NOW,
            extraction_version="structured-1",
            body_document=document,
        ),
    )

    statements = "\n".join(sql for sql, _params in connection.cursor_value.executed)
    assert "body_document = %s" in statements
    assert "body_structure_status = %s" in statements
    assert any("available" in params for _sql, params in connection.cursor_value.executed)
    assert "INSERT INTO live_news_content_asset" in statements
    assert "ON CONFLICT (article_id, block_id) DO UPDATE" in statements
    assert "UPDATE live_news_content_job" in statements


def test_structure_retry_and_failure_preserve_existing_plain_text() -> None:
    connection = FakeConnection()
    job = ContentJob(
        article_id=ARTICLE_ID,
        request=ContentRequest(
            article_id=ARTICLE_ID,
            canonical_url="https://example.com/story",
            expected_domain="example.com",
            language="en",
            policy=ContentPolicy("html", "full_text"),
        ),
        content_rights="full_text",
        attempt_count=2,
    )

    retry_content_job(
        connection,
        job,
        code="timeout",
        detail="temporary",
        next_attempt_at=NOW,
    )
    finish_content_job(
        connection,
        job,
        status="failed",
        code="extraction_too_short",
        detail="permanent",
    )

    live_updates = [
        sql for sql, _params in connection.cursor_value.executed if "UPDATE live_news\n" in sql
    ]
    assert live_updates
    assert all("body_text = NULL" not in sql for sql in live_updates)
    assert any("body_structure_status = 'pending'" in sql for sql in live_updates)
    assert any("body_structure_status = %s" in sql for sql in live_updates)


def test_postgres_store_wraps_claim_in_transaction_and_closes_connection(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sources.json"
    config.write_text(
        '{"sources":[{"domain":"example.com","languages":["en"],"quality_weight":0.8}]}',
        encoding="utf-8",
    )
    connection = FakeConnection()
    store = PostgresLiveContentStore(lambda: connection, load_allowlist(config))

    assert store.claim_due("worker-1", 10, NOW) == []
    assert connection.transaction_entries == 1
    assert connection.closed is True


@pytest.mark.postgres
def test_postgres_queue_claim_and_completion_are_persistent(
    postgres_connection,
    tmp_path: Path,
) -> None:
    config = tmp_path / "sources.json"
    config.write_text(
        '{"sources":[{"domain":"example.com","languages":["en"],'
        '"quality_weight":0.8,"content":{"mode":"html","display":"full_text",'
        '"feed_urls":[]}}]}',
        encoding="utf-8",
    )
    allowlist = load_allowlist(config)
    body = " ".join(["A complete persisted article paragraph for integration testing."] * 12)
    with postgres_connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO live_news (
              article_id, canonical_url, title, summary, publisher,
              source_domain, language, published_at_quality,
              discovered_at, fetched_at, content_hash, status, raw_metadata_json
            ) VALUES (
              %s, 'https://example.com/content-dao-fixture', 'Fixture', 'Summary',
              'Example', 'example.com', 'en', 'publisher', %s, %s,
              %s, 'active', '{}'::jsonb
            ) ON CONFLICT (article_id) DO NOTHING
            """,
            (ARTICLE_ID, NOW, NOW, "a" * 64),
        )
    ensure_content_job(
        postgres_connection,
        ARTICLE_ID,
        ContentPolicy("html", "full_text"),
        now=NOW,
    )
    postgres_connection.commit()
    try:
        jobs = claim_due_content_jobs(
            postgres_connection,
            allowlist,
            worker_id="integration-worker",
            limit=1,
            now=NOW,
        )
        postgres_connection.commit()
        assert len(jobs) == 1

        complete_content_job(
            postgres_connection,
            jobs[0],
            AcquiredContent("html", body, NOW, "trafilatura-2.1"),
        )
        postgres_connection.commit()

        with postgres_connection.cursor() as cursor:
            cursor.execute(
                "SELECT body_status, body_text FROM live_news WHERE article_id = %s",
                (ARTICLE_ID,),
            )
            assert cursor.fetchone() == {"body_status": "available", "body_text": body}
            cursor.execute(
                "SELECT status FROM live_news_content_job WHERE article_id = %s",
                (ARTICLE_ID,),
            )
            assert cursor.fetchone() == {"status": "completed"}
    finally:
        with postgres_connection.cursor() as cursor:
            cursor.execute("DELETE FROM live_news WHERE article_id = %s", (ARTICLE_ID,))
        postgres_connection.commit()


@pytest.mark.postgres
def test_metadata_replay_preserves_blocked_job_state(postgres_connection) -> None:
    with postgres_connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO live_news (
              article_id, canonical_url, title, summary, publisher,
              source_domain, language, published_at_quality,
              discovered_at, fetched_at, content_hash, status, raw_metadata_json,
              body_status, content_rights
            ) VALUES (
              %s, 'https://example.com/blocked-content-fixture', 'Fixture', 'Summary',
              'Example', 'example.com', 'en', 'publisher', %s, %s,
              %s, 'active', '{}'::jsonb, 'blocked', 'full_text'
            ) ON CONFLICT (article_id) DO NOTHING
            """,
            (BLOCKED_ARTICLE_ID, NOW, NOW, "b" * 64),
        )
        cursor.execute(
            """
            INSERT INTO live_news_content_job (
              article_id, status, attempt_count, next_attempt_at,
              last_error_code, last_error_detail
            ) VALUES (%s, 'blocked', 1, %s, 'authentication_required', 'forbidden')
            ON CONFLICT (article_id) DO UPDATE SET status = 'blocked'
            """,
            (BLOCKED_ARTICLE_ID, NOW),
        )
    postgres_connection.commit()
    try:
        ensure_content_job(
            postgres_connection,
            BLOCKED_ARTICLE_ID,
            ContentPolicy("html", "full_text"),
            now=NOW,
        )
        postgres_connection.commit()

        with postgres_connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT body_status, body_structure_status
                FROM live_news
                WHERE article_id = %s
                """,
                (BLOCKED_ARTICLE_ID,),
            )
            assert cursor.fetchone() == {
                "body_status": "blocked",
                "body_structure_status": "blocked",
            }
    finally:
        with postgres_connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM live_news WHERE article_id = %s",
                (BLOCKED_ARTICLE_ID,),
            )
        postgres_connection.commit()
