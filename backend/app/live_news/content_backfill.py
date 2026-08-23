from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class BackfillFilters:
    source_domain: str | None = None
    language: Literal["zh", "en"] | None = None
    limit: int = 100

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 10_000:
            raise ValueError("backfill limit must be between 1 and 10000")


def _select_candidates(connection: Any, filters: BackfillFilters) -> list[str]:
    clauses = [
        "news.status = 'active'",
        "news.content_rights <> 'link_only'",
        "news.body_document_version IS DISTINCT FROM 'structured-1'",
        "COALESCE(job.status, '') <> 'fetching'",
        "news.discovered_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'",
    ]
    params: list[Any] = []
    if filters.source_domain:
        clauses.append("news.source_domain = %s")
        params.append(filters.source_domain)
    if filters.language:
        clauses.append("news.language = %s")
        params.append(filters.language)
    params.append(filters.limit)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT news.article_id
            FROM live_news AS news
            LEFT JOIN live_news_content_job AS job ON job.article_id = news.article_id
            WHERE {" AND ".join(clauses)}
            ORDER BY news.discovered_at DESC, news.article_id
            LIMIT %s
            """,
            tuple(params),
        )
        return [str(row["article_id"]) for row in cursor.fetchall()]


def enqueue_structured_backfill(
    connection: Any,
    filters: BackfillFilters,
    *,
    dry_run: bool,
) -> int:
    if dry_run:
        return len(_select_candidates(connection, filters))
    with connection.transaction():
        article_ids = _select_candidates(connection, filters)
        with connection.cursor() as cursor:
            for article_id in article_ids:
                cursor.execute(
                    """
                    INSERT INTO live_news_content_job (
                      article_id, status, attempt_count, next_attempt_at,
                      target_extraction_version, requested_by, created_at, updated_at
                    ) VALUES (
                      %s, 'pending', 0, CURRENT_TIMESTAMP, 'structured-1',
                      'operator_backfill', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (article_id) DO UPDATE SET
                      status = CASE
                        WHEN live_news_content_job.status = 'fetching' THEN 'fetching'
                        ELSE 'pending'
                      END,
                      next_attempt_at = CURRENT_TIMESTAMP,
                      target_extraction_version = 'structured-1',
                      requested_by = 'operator_backfill',
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    (article_id,),
                )
                cursor.execute(
                    """
                    UPDATE live_news
                    SET body_structure_status = 'pending',
                        body_structure_updated_at = CURRENT_TIMESTAMP
                    WHERE article_id = %s
                    """,
                    (article_id,),
                )
        return len(article_ids)
