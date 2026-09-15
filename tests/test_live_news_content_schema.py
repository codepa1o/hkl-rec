from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.db.schema import metadata


def test_live_content_migration_is_single_head() -> None:
    root = Path(__file__).resolve().parents[1]
    script = ScriptDirectory.from_config(Config(root / "alembic.ini"))

    assert script.get_heads() == ["20260914_0013"]
    revision = script.get_revision("20260818_0010")
    assert revision is not None
    assert revision.down_revision == "20260817_0009"


def test_metadata_defines_live_body_columns_and_job_queue() -> None:
    news = metadata.tables["live_news"]
    assert {
        "body_text",
        "body_source",
        "body_status",
        "body_fetched_at",
        "body_content_hash",
        "body_extraction_version",
        "content_rights",
    } <= set(news.c.keys())
    assert str(news.c.body_status.server_default.arg) == "'metadata_only'"
    assert str(news.c.content_rights.server_default.arg) == "'link_only'"

    jobs = metadata.tables["live_news_content_job"]
    assert [column.name for column in jobs.primary_key.columns] == ["article_id"]
    assert set(jobs.c.keys()) == {
        "article_id",
        "status",
        "attempt_count",
        "next_attempt_at",
        "claimed_at",
        "worker_id",
        "last_error_code",
        "last_error_detail",
        "target_extraction_version",
        "requested_by",
        "created_at",
        "updated_at",
    }
    assert {
        element.target_fullname
        for constraint in jobs.foreign_key_constraints
        for element in constraint.elements
    } == {"live_news.article_id"}
    assert "idx_live_news_content_job_due" in {index.name for index in jobs.indexes}
