from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from backend.app.live_news.allowlist import SourceAllowlist
from backend.app.live_news.content_dao import ensure_content_job
from backend.app.live_news.types import (
    LiveImportResult,
    LiveNewsCheckpoint,
    NormalizedGalBatch,
)


def load_checkpoint(connection: Any, source_name: str) -> LiveNewsCheckpoint | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_name, last_batch_time, last_etag, last_modified,
                   last_success_at, last_error
            FROM live_news_source_checkpoint
            WHERE source_name = %s
            """,
            (source_name,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return LiveNewsCheckpoint(
        source_name=str(row["source_name"]),
        last_batch_time=row.get("last_batch_time"),
        last_etag=row.get("last_etag"),
        last_modified=row.get("last_modified"),
        last_success_at=row.get("last_success_at"),
        last_error=row.get("last_error"),
    )


def persist_batch(
    connection: Any,
    batch: NormalizedGalBatch,
    *,
    allowlist: SourceAllowlist | None = None,
) -> LiveImportResult:
    rejection_counts = Counter(item.reason for item in batch.rejections)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO live_news_import (
              batch_id, source_url, source_sha256, fetched_at,
              raw_count, accepted_count, rejected_count,
              rejection_summary_json, status, error_message
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'fetching', NULL)
            ON CONFLICT (batch_id) DO UPDATE SET
              source_url = EXCLUDED.source_url,
              source_sha256 = EXCLUDED.source_sha256,
              fetched_at = EXCLUDED.fetched_at,
              raw_count = EXCLUDED.raw_count,
              accepted_count = EXCLUDED.accepted_count,
              rejected_count = EXCLUDED.rejected_count,
              rejection_summary_json = EXCLUDED.rejection_summary_json,
              status = 'fetching',
              error_message = NULL
            """,
            (
                batch.batch_id,
                batch.source_url,
                batch.source_sha256,
                batch.batch_time,
                batch.raw_count,
                len(batch.articles),
                len(batch.rejections),
                json.dumps(rejection_counts, sort_keys=True),
            ),
        )
        rows = [
            (
                article.article_id,
                article.canonical_url,
                article.source_external_id,
                article.title,
                article.summary,
                article.image_url,
                article.publisher,
                article.source_domain,
                article.language,
                article.published_at,
                article.published_at_quality,
                article.discovered_at,
                article.fetched_at,
                article.content_hash,
                json.dumps(article.raw_metadata, ensure_ascii=False, sort_keys=True),
            )
            for article in batch.articles
        ]
        if rows:
            cursor.executemany(
                """
                INSERT INTO live_news (
                  article_id, canonical_url, source_external_id, title, summary,
                  image_url, publisher, source_domain, language, published_at,
                  published_at_quality, discovered_at, fetched_at, content_hash,
                  status, raw_metadata_json, created_at, updated_at
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, 'active', %s::jsonb,
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                ON CONFLICT (article_id) DO UPDATE SET
                  title = EXCLUDED.title,
                  summary = EXCLUDED.summary,
                  image_url = EXCLUDED.image_url,
                  publisher = EXCLUDED.publisher,
                  published_at = EXCLUDED.published_at,
                  published_at_quality = EXCLUDED.published_at_quality,
                  fetched_at = EXCLUDED.fetched_at,
                  content_hash = EXCLUDED.content_hash,
                  status = 'active',
                  raw_metadata_json = EXCLUDED.raw_metadata_json,
                  updated_at = CURRENT_TIMESTAMP
                """,
                rows,
            )
        if allowlist is not None:
            for article in batch.articles:
                policy = allowlist.match(article.source_domain)
                if policy is not None:
                    ensure_content_job(
                        connection,
                        article.article_id,
                        policy.content,
                        now=batch.batch_time,
                    )
        cursor.execute(
            """
            UPDATE live_news_import
            SET status = 'completed', error_message = NULL
            WHERE batch_id = %s
            """,
            (batch.batch_id,),
        )
        cursor.execute(
            """
            INSERT INTO live_news_source_checkpoint (
              source_name, last_batch_time, last_etag, last_modified,
              last_success_at, last_error, updated_at
            ) VALUES (%s, %s, %s, %s, %s, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT (source_name) DO UPDATE SET
              last_batch_time = GREATEST(
                live_news_source_checkpoint.last_batch_time,
                EXCLUDED.last_batch_time
              ),
              last_etag = EXCLUDED.last_etag,
              last_modified = EXCLUDED.last_modified,
              last_success_at = EXCLUDED.last_success_at,
              last_error = NULL,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                batch.source_name,
                batch.batch_time,
                batch.etag,
                batch.last_modified,
                datetime.now(UTC),
            ),
        )
    return LiveImportResult(
        batch_id=batch.batch_id,
        accepted_count=len(batch.articles),
        rejected_count=len(batch.rejections),
    )


def record_failure(connection: Any, source_name: str, error: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO live_news_source_checkpoint (
              source_name, last_error, updated_at
            ) VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (source_name) DO UPDATE SET
              last_error = EXCLUDED.last_error,
              updated_at = CURRENT_TIMESTAMP
            """,
            (source_name, error),
        )


class PostgresLiveNewsStore:
    def __init__(
        self,
        connection_factory: Callable[[], Any],
        allowlist: SourceAllowlist | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._allowlist = allowlist

    def load_checkpoint(self, source_name: str) -> LiveNewsCheckpoint | None:
        connection = self._connection_factory()
        try:
            return load_checkpoint(connection, source_name)
        finally:
            connection.close()

    def persist_batch(self, batch: NormalizedGalBatch) -> LiveImportResult:
        connection = self._connection_factory()
        try:
            with connection.transaction():
                return persist_batch(connection, batch, allowlist=self._allowlist)
        finally:
            connection.close()

    def record_failure(self, source_name: str, error: str) -> None:
        connection = self._connection_factory()
        try:
            with connection.transaction():
                record_failure(connection, source_name, error)
        finally:
            connection.close()
