from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from backend.app.live_news.content_backfill import BackfillFilters, enqueue_structured_backfill


class Cursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.rows = [{"article_id": "L0123456789abcdef0123456789abcdef"}]

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.executed.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self) -> None:
        self.cursor_value = Cursor()
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
    assert params == ("theguardian.com", "en", 10)


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
