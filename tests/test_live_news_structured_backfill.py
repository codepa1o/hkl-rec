from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from backend.app.live_news.allowlist import load_allowlist
from backend.app.live_news.content_backfill import BackfillFilters, enqueue_structured_backfill

ROOT = Path(__file__).resolve().parents[1]


class Cursor:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.rows = rows or [{"article_id": "L0123456789abcdef0123456789abcdef"}]

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.executed.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.cursor_value = Cursor(rows)
        self.transactions = 0

    def cursor(self) -> Cursor:
        return self.cursor_value

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield


def test_backfill_dry_run_selects_without_mutating_jobs() -> None:
    connection = Connection()

    count = enqueue_structured_backfill(
        connection,
        BackfillFilters(source_domain="theguardian.com", language="en", limit=10),
        dry_run=True,
    )

    sql, params = connection.cursor_value.executed[0]
    assert count == 1
    assert sql.startswith("SELECT news.article_id")
    assert "INSERT INTO" not in sql
    assert "news.content_rights <> 'link_only'" in sql
    assert "news.body_document_version IS DISTINCT FROM 'structured-1'" in sql
    assert params == (30, "theguardian.com", "en", 10)


def test_backfill_enqueues_versioned_operator_jobs_idempotently() -> None:
    connection = Connection()

    count = enqueue_structured_backfill(
        connection,
        BackfillFilters(limit=20),
        dry_run=False,
    )

    statements = "\n".join(sql for sql, _params in connection.cursor_value.executed)
    assert count == 1
    assert "INSERT INTO live_news_content_job" in statements
    assert "ON CONFLICT (article_id) DO UPDATE" in statements
    assert "requested_by = 'operator_backfill'" in statements
    assert "UPDATE live_news" in statements
    assert connection.transactions == 1


def test_backfill_supports_source_suffix_and_bounded_age() -> None:
    connection = Connection()

    enqueue_structured_backfill(
        connection,
        BackfillFilters(source_suffix="xinhuanet.com", since_days=7, limit=20),
        dry_run=True,
    )

    sql, params = connection.cursor_value.executed[0]
    assert "news.source_domain = %s OR news.source_domain LIKE %s" in sql
    assert params == (7, "xinhuanet.com", "%.xinhuanet.com", 20)


def test_local_research_backfill_requires_runtime_gate(tmp_path: Path) -> None:
    config = tmp_path / "sources.json"
    config.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "domain": "xinhuanet.com",
                        "languages": ["zh"],
                        "quality_weight": 0.9,
                        "content": {
                            "mode": "html",
                            "display": "full_text",
                            "access_scope": "local_research",
                            "adapter": "xinhuanet",
                            "target_extraction_version": "zh-xinhua-1",
                            "allow_insecure_http": True,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    connection = Connection(
        [
            {
                "article_id": "L0123456789abcdef0123456789abcdef",
                "source_domain": "www.ha.xinhuanet.com",
                "body_document_version": None,
            }
        ]
    )

    with pytest.raises(ValueError, match="local research"):
        enqueue_structured_backfill(
            connection,
            BackfillFilters(source_suffix="xinhuanet.com", language="zh", limit=20),
            dry_run=True,
            allowlist=load_allowlist(config),
            local_research_allowed=False,
        )


def test_backfill_script_help_runs_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/backfill_live_structured_content.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--source-suffix" in result.stdout


@pytest.mark.postgres
def test_local_research_backfill_commits_jobs(postgres_connection, tmp_path: Path) -> None:
    article_id = "L22222222222222222222222222222222"
    config = tmp_path / "sources.json"
    config.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "domain": "xinhuanet.com",
                        "languages": ["zh"],
                        "quality_weight": 0.9,
                        "content": {
                            "mode": "html",
                            "display": "full_text",
                            "access_scope": "local_research",
                            "adapter": "xinhuanet",
                            "target_extraction_version": "zh-xinhua-1",
                            "allow_insecure_http": True,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with postgres_connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO live_news (
              article_id, canonical_url, title, summary, publisher,
              source_domain, language, published_at_quality,
              discovered_at, fetched_at, content_hash, status, raw_metadata_json
            ) VALUES (
              %s, 'http://www.xinhuanet.com/backfill-commit-fixture',
              '虚构回填测试', '摘要', '新华网', 'www.xinhuanet.com', 'zh',
              'publisher', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
              %s, 'active', '{}'::jsonb
            )
            """,
            (article_id, "2" * 64),
        )
    postgres_connection.commit()
    try:
        count = enqueue_structured_backfill(
            postgres_connection,
            BackfillFilters(source_suffix="xinhuanet.com", language="zh", limit=1),
            dry_run=False,
            allowlist=load_allowlist(config),
            local_research_allowed=True,
        )
        postgres_connection.rollback()

        with postgres_connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT news.body_access_scope, job.status, job.target_extraction_version
                FROM live_news AS news
                JOIN live_news_content_job AS job USING (article_id)
                WHERE news.article_id = %s
                """,
                (article_id,),
            )
            row = cursor.fetchone()
        assert count == 1
        assert row == {
            "body_access_scope": "local_research",
            "status": "pending",
            "target_extraction_version": "zh-xinhua-1",
        }
    finally:
        postgres_connection.rollback()
        with postgres_connection.cursor() as cursor:
            cursor.execute("DELETE FROM live_news WHERE article_id = %s", (article_id,))
        postgres_connection.commit()
