from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.app.live_news import dao
from backend.app.live_news.allowlist import load_allowlist
from backend.app.live_news.dao import PostgresLiveNewsStore, load_checkpoint, persist_batch
from backend.app.live_news.types import LiveImportResult, LiveNewsArticle, NormalizedGalBatch


def test_store_uses_psycopg_transaction_context_instead_of_begin_method() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, sql: str, params: tuple[Any, ...]) -> None:
            self.executed.append((sql, params))

    class TransactionOnlyConnection:
        def __init__(self) -> None:
            self.cursor_value = Cursor()
            self.transaction_entries = 0
            self.closed = False

        @contextmanager
        def transaction(self):
            self.transaction_entries += 1
            yield

        def cursor(self) -> Cursor:
            return self.cursor_value

        def close(self) -> None:
            self.closed = True

    connection = TransactionOnlyConnection()
    store = PostgresLiveNewsStore(lambda: connection)

    store.record_failure("gdelt_gal", "fixture failure")

    assert connection.transaction_entries == 1
    assert connection.closed is True
    assert connection.cursor_value.executed[0][1] == ("gdelt_gal", "fixture failure")


def test_store_passes_allowlist_to_batch_persistence(monkeypatch, tmp_path) -> None:
    class Connection:
        def __init__(self) -> None:
            self.closed = False

        @contextmanager
        def transaction(self):
            yield

        def close(self) -> None:
            self.closed = True

    config = tmp_path / "sources.json"
    config.write_text(
        '{"sources":[{"domain":"example.com","languages":["en"],'
        '"quality_weight":0.8,"content":{"mode":"html","display":"full_text",'
        '"feed_urls":[]}}]}',
        encoding="utf-8",
    )
    allowlist = load_allowlist(config)
    connection = Connection()
    captured: dict[str, object] = {}

    def fake_persist(connection_arg, batch_arg, *, allowlist=None):
        captured.update(connection=connection_arg, batch=batch_arg, allowlist=allowlist)
        return LiveImportResult("batch", 1, 0)

    monkeypatch.setattr(dao, "persist_batch", fake_persist)
    batch = MagicMock(spec=NormalizedGalBatch)
    store = PostgresLiveNewsStore(lambda: connection, allowlist)

    result = store.persist_batch(batch)

    assert result.accepted_count == 1
    assert captured == {"connection": connection, "batch": batch, "allowlist": allowlist}
    assert connection.closed is True


@pytest.mark.postgres
def test_replaying_live_batch_is_idempotent(postgres_connection) -> None:
    batch_time = datetime(2026, 8, 17, 2, 16, tzinfo=UTC)
    article = LiveNewsArticle(
        article_id="L0123456789abcdef0123456789abcdef",
        canonical_url="https://www.reuters.com/live-dao-fixture",
        source_external_id="fixture",
        title="Live DAO fixture",
        summary="Fixture summary",
        image_url=None,
        publisher="Reuters",
        source_domain="www.reuters.com",
        language="en",
        author=None,
        published_at=batch_time,
        published_at_quality="gdelt_unverified",
        discovered_at=batch_time,
        fetched_at=batch_time,
        content_hash="a" * 64,
        publisher_quality=1.0,
        raw_metadata={"fixture": True},
    )
    batch = NormalizedGalBatch(
        source_name="gdelt_gal_test",
        batch_id="gdelt_gal_test:20260817021600",
        batch_time=batch_time,
        source_url="fixture://batch",
        source_sha256="b" * 64,
        etag='"fixture"',
        last_modified="fixture-modified",
        raw_count=1,
        articles=(article,),
        rejections=(),
    )
    try:
        first = persist_batch(postgres_connection, batch)
        postgres_connection.commit()
        second = persist_batch(postgres_connection, batch)
        postgres_connection.commit()

        with postgres_connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS count FROM live_news WHERE article_id = %s",
                (article.article_id,),
            )
            assert int(cursor.fetchone()["count"]) == 1
        assert first == second
        checkpoint = load_checkpoint(postgres_connection, batch.source_name)
        assert checkpoint is not None
        assert checkpoint.last_batch_time == batch_time
    finally:
        with postgres_connection.cursor() as cursor:
            cursor.execute("DELETE FROM live_news_import WHERE batch_id = %s", (batch.batch_id,))
            cursor.execute(
                "DELETE FROM live_news_source_checkpoint WHERE source_name = %s",
                (batch.source_name,),
            )
            cursor.execute("DELETE FROM live_news WHERE article_id = %s", (article.article_id,))
        postgres_connection.commit()
