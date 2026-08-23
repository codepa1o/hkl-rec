from __future__ import annotations

import subprocess
import sys

from backend.app.db.schema import live_news, live_news_content_asset, live_news_content_job


def test_live_news_schema_exposes_structured_document_columns() -> None:
    assert {
        "body_document",
        "body_document_version",
        "body_document_hash",
        "body_structure_status",
        "body_structure_updated_at",
    } <= set(live_news.c.keys())
    assert str(live_news.c.body_structure_status.server_default.arg) == "'missing'"


def test_content_asset_schema_tracks_ordered_image_metadata_without_binary_data() -> None:
    assert {
        "asset_id",
        "article_id",
        "block_id",
        "source_url",
        "storage_key",
        "display_url",
        "mime_type",
        "width",
        "height",
        "alt_text",
        "caption",
        "credit",
        "content_hash",
        "cache_status",
        "last_error_code",
        "fetched_at",
        "created_at",
        "updated_at",
    } == set(live_news_content_asset.c.keys())
    assert live_news_content_asset.c.article_id.foreign_keys
    assert all(
        column.name not in {"body", "bytes", "binary"} for column in live_news_content_asset.c
    )


def test_content_jobs_record_target_version_and_request_source() -> None:
    assert {"target_extraction_version", "requested_by"} <= set(live_news_content_job.c.keys())


def test_structured_document_migration_is_the_alembic_head() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "20260821_0011 (head)"
