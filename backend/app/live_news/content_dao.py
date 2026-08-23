from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal, cast

from backend.app.live_news.allowlist import SourceAllowlist
from backend.app.live_news.content_document import ImageBlock
from backend.app.live_news.content_normalize import body_hash
from backend.app.live_news.content_parser import document_hash
from backend.app.live_news.content_policy import ContentPolicy, ContentRights
from backend.app.live_news.content_types import (
    AcquiredContent,
    ContentJob,
    ContentRequest,
    JobStatus,
)


def ensure_content_job(
    connection: Any,
    article_id: str,
    policy: ContentPolicy,
    *,
    now: datetime,
) -> None:
    with connection.cursor() as cursor:
        if policy.mode == "link_only":
            cursor.execute(
                """
                UPDATE live_news
                SET content_rights = 'link_only',
                    body_status = 'metadata_only',
                    body_structure_status = 'blocked',
                    body_text = NULL,
                    body_source = NULL,
                    body_fetched_at = NULL,
                    body_content_hash = NULL,
                    body_extraction_version = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE article_id = %s
                """,
                (article_id,),
            )
            cursor.execute(
                "DELETE FROM live_news_content_job WHERE article_id = %s",
                (article_id,),
            )
            return
        cursor.execute(
            """
            UPDATE live_news
            SET content_rights = %s,
                body_structure_status = CASE
                    WHEN body_document IS NOT NULL
                         AND body_document_version = 'structured-1' THEN 'available'
                    ELSE 'pending'
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE article_id = %s
            """,
            (policy.display, article_id),
        )
        cursor.execute(
            """
            INSERT INTO live_news_content_job (
              article_id, status, attempt_count, next_attempt_at,
              target_extraction_version, requested_by, created_at, updated_at
            ) VALUES (
              %s, 'pending', 0, %s, 'structured-1', 'ingest',
              CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (article_id) DO UPDATE SET
              status = CASE
                WHEN live_news_content_job.status = 'fetching' THEN 'fetching'
                WHEN EXISTS (
                  SELECT 1 FROM live_news
                  WHERE article_id = EXCLUDED.article_id
                    AND body_structure_status = 'available'
                    AND body_document_version = 'structured-1'
                ) THEN live_news_content_job.status
                ELSE 'pending'
              END,
              next_attempt_at = CASE
                WHEN live_news_content_job.status = 'fetching'
                  THEN live_news_content_job.next_attempt_at
                ELSE EXCLUDED.next_attempt_at
              END,
              target_extraction_version = 'structured-1',
              requested_by = 'ingest',
              updated_at = CURRENT_TIMESTAMP
            """,
            (article_id, now),
        )
        cursor.execute(
            """
            UPDATE live_news AS news
            SET body_status = CASE job.status
                    WHEN 'blocked' THEN 'blocked'
                    WHEN 'failed' THEN 'failed'
                    WHEN 'completed' THEN
                        CASE WHEN news.body_text IS NOT NULL THEN 'available' ELSE 'pending' END
                    ELSE 'pending'
                END,
                updated_at = CURRENT_TIMESTAMP
            FROM live_news_content_job AS job
            WHERE news.article_id = %s AND job.article_id = news.article_id
            """,
            (article_id,),
        )


def claim_due_content_jobs(
    connection: Any,
    allowlist: SourceAllowlist,
    *,
    worker_id: str,
    limit: int,
    now: datetime,
) -> list[ContentJob]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH due AS (
              SELECT job.article_id
              FROM live_news_content_job AS job
              WHERE job.status = 'pending' AND job.next_attempt_at <= %s
              ORDER BY job.next_attempt_at, job.article_id
              FOR UPDATE SKIP LOCKED
              LIMIT %s
            )
            UPDATE live_news_content_job AS job
            SET status = 'fetching',
                attempt_count = job.attempt_count + 1,
                claimed_at = %s,
                worker_id = %s,
                updated_at = CURRENT_TIMESTAMP
            FROM due, live_news AS news
            WHERE job.article_id = due.article_id
              AND news.article_id = job.article_id
            RETURNING
              news.article_id, news.canonical_url, news.source_domain, news.image_url,
              news.language, news.content_rights, job.attempt_count
            """,
            (now, limit, now, worker_id),
        )
        rows = cursor.fetchall()
    jobs: list[ContentJob] = []
    for row in rows:
        policy = allowlist.match(str(row["source_domain"]))
        if policy is None or policy.content.mode == "link_only":
            continue
        jobs.append(
            ContentJob(
                article_id=str(row["article_id"]),
                request=ContentRequest(
                    article_id=str(row["article_id"]),
                    canonical_url=str(row["canonical_url"]),
                    expected_domain=policy.domain,
                    language=cast(Literal["zh", "en"], row["language"]),
                    policy=policy.content,
                    lead_image_url=cast(str | None, row.get("image_url")),
                ),
                content_rights=cast(ContentRights, row["content_rights"]),
                attempt_count=int(row["attempt_count"]),
            )
        )
    return jobs


def complete_content_job(
    connection: Any,
    job: ContentJob,
    acquired: AcquiredContent,
) -> None:
    document = acquired.body_document
    document_payload = (
        json.dumps(document.model_dump(mode="json"), ensure_ascii=False) if document else None
    )
    structure_status = "available" if document else "missing"
    structure_version = document.extraction_version if document else None
    structure_hash = document_hash(document) if document else None
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE live_news
            SET body_text = %s,
                body_source = %s,
                body_status = 'available',
                body_fetched_at = %s,
                body_content_hash = %s,
                body_extraction_version = %s,
                content_rights = %s,
                body_document = %s::jsonb,
                body_document_version = %s,
                body_document_hash = %s,
                body_structure_status = %s,
                body_structure_updated_at = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE article_id = %s
            """,
            (
                acquired.body_text,
                acquired.source,
                acquired.fetched_at,
                body_hash(acquired.body_text),
                acquired.extraction_version,
                job.content_rights,
                document_payload,
                structure_version,
                structure_hash,
                structure_status,
                acquired.fetched_at,
                job.article_id,
            ),
        )
        cursor.execute(
            "DELETE FROM live_news_content_asset WHERE article_id = %s",
            (job.article_id,),
        )
        if document:
            for block in document.blocks:
                if not isinstance(block, ImageBlock):
                    continue
                cursor.execute(
                    """
                    INSERT INTO live_news_content_asset (
                      asset_id, article_id, block_id, source_url, display_url,
                      mime_type, width, height, alt_text, caption, credit,
                      cache_status, created_at, updated_at
                    ) VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (article_id, block_id) DO UPDATE SET
                      source_url = EXCLUDED.source_url,
                      display_url = EXCLUDED.display_url,
                      mime_type = EXCLUDED.mime_type,
                      width = EXCLUDED.width,
                      height = EXCLUDED.height,
                      alt_text = EXCLUDED.alt_text,
                      caption = EXCLUDED.caption,
                      credit = EXCLUDED.credit,
                      cache_status = EXCLUDED.cache_status,
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        block.asset_id,
                        job.article_id,
                        block.id,
                        block.source_url,
                        block.display_url,
                        block.mime_type,
                        block.width,
                        block.height,
                        block.alt,
                        block.caption,
                        block.credit,
                        block.cache_status,
                    ),
                )
        cursor.execute(
            """
            UPDATE live_news_content_job
            SET status = 'completed', claimed_at = NULL, worker_id = NULL,
                last_error_code = NULL, last_error_detail = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE article_id = %s
            """,
            (job.article_id,),
        )


def retry_content_job(
    connection: Any,
    job: ContentJob,
    *,
    code: str,
    detail: str,
    next_attempt_at: datetime,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE live_news_content_job
            SET status = 'pending', next_attempt_at = %s,
                claimed_at = NULL, worker_id = NULL,
                last_error_code = %s, last_error_detail = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE article_id = %s
            """,
            (next_attempt_at, code, detail, job.article_id),
        )
        cursor.execute(
            """
            UPDATE live_news
            SET body_status = CASE WHEN body_text IS NULL THEN 'pending' ELSE body_status END,
                body_structure_status = 'pending',
                body_structure_updated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE article_id = %s
            """,
            (job.article_id,),
        )


def finish_content_job(
    connection: Any,
    job: ContentJob,
    *,
    status: JobStatus,
    code: str,
    detail: str,
) -> None:
    if status not in {"blocked", "failed"}:
        raise ValueError("terminal content status must be blocked or failed")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE live_news_content_job
            SET status = %s, claimed_at = NULL, worker_id = NULL,
                last_error_code = %s, last_error_detail = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE article_id = %s
            """,
            (status, code, detail, job.article_id),
        )
        cursor.execute(
            """
            UPDATE live_news
            SET body_status = CASE WHEN body_text IS NULL THEN %s ELSE body_status END,
                body_source = CASE WHEN body_text IS NULL THEN NULL ELSE body_source END,
                body_fetched_at = CASE
                    WHEN body_text IS NULL THEN NULL ELSE body_fetched_at
                END,
                body_content_hash = CASE
                    WHEN body_text IS NULL THEN NULL ELSE body_content_hash
                END,
                body_extraction_version = CASE
                    WHEN body_text IS NULL THEN NULL ELSE body_extraction_version
                END,
                body_structure_status = %s,
                body_structure_updated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE article_id = %s
            """,
            (status, status, job.article_id),
        )


def recover_stale_content_jobs(connection: Any, *, stale_before: datetime) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE live_news_content_job
            SET status = 'pending', claimed_at = NULL, worker_id = NULL,
                next_attempt_at = CURRENT_TIMESTAMP,
                last_error_code = 'stale_claim_recovered',
                last_error_detail = 'worker claim exceeded stale threshold',
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'fetching' AND claimed_at < %s
            """,
            (stale_before,),
        )
        return int(cursor.rowcount)


class PostgresLiveContentStore:
    def __init__(
        self,
        connection_factory: Callable[[], Any],
        allowlist: SourceAllowlist,
    ) -> None:
        self._connection_factory = connection_factory
        self._allowlist = allowlist

    def claim_due(self, worker_id: str, limit: int, now: datetime) -> list[ContentJob]:
        connection = self._connection_factory()
        try:
            with connection.transaction():
                return claim_due_content_jobs(
                    connection,
                    self._allowlist,
                    worker_id=worker_id,
                    limit=limit,
                    now=now,
                )
        finally:
            connection.close()

    def complete(self, job: ContentJob, acquired: AcquiredContent) -> None:
        self._run_in_transaction(complete_content_job, job, acquired)

    def retry(
        self,
        job: ContentJob,
        *,
        code: str,
        detail: str,
        next_attempt_at: datetime,
    ) -> None:
        self._run_in_transaction(
            retry_content_job,
            job,
            code=code,
            detail=detail,
            next_attempt_at=next_attempt_at,
        )

    def finish(
        self,
        job: ContentJob,
        *,
        status: JobStatus,
        code: str,
        detail: str,
    ) -> None:
        self._run_in_transaction(
            finish_content_job,
            job,
            status=status,
            code=code,
            detail=detail,
        )

    def recover_stale(self, stale_before: datetime) -> int:
        connection = self._connection_factory()
        try:
            with connection.transaction():
                return recover_stale_content_jobs(connection, stale_before=stale_before)
        finally:
            connection.close()

    def _run_in_transaction(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        connection = self._connection_factory()
        try:
            with connection.transaction():
                function(connection, *args, **kwargs)
        finally:
            connection.close()
