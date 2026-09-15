from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from backend.app.live_news.allowlist import SourceAllowlist
from backend.app.live_news.content_dao import ensure_content_job


@dataclass(frozen=True)
class BackfillFilters:
    source_domain: str | None = None
    source_suffix: str | None = None
    language: Literal["zh", "en"] | None = None
    since_days: int = 30
    limit: int = 100

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 10_000:
            raise ValueError("backfill limit must be between 1 and 10000")
        if not 1 <= self.since_days <= 365:
            raise ValueError("since_days must be between 1 and 365")
        if self.source_domain and self.source_suffix:
            raise ValueError("source_domain and source_suffix are mutually exclusive")


def _select_candidates(
    connection: Any,
    filters: BackfillFilters,
    *,
    include_link_only: bool,
) -> list[dict[str, Any]]:
    clauses = [
        "news.status = 'active'",
        "COALESCE(job.status, '') <> 'fetching'",
        "news.discovered_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')",
    ]
    params: list[Any] = [filters.since_days]
    if not include_link_only:
        clauses.extend(
            [
                "news.content_rights <> 'link_only'",
                "news.body_document_version IS DISTINCT FROM 'structured-1'",
            ]
        )
    if filters.source_domain:
        clauses.append("news.source_domain = %s")
        params.append(filters.source_domain)
    if filters.source_suffix:
        clauses.append("(news.source_domain = %s OR news.source_domain LIKE %s)")
        params.extend((filters.source_suffix, f"%.{filters.source_suffix}"))
    if filters.language:
        clauses.append("news.language = %s")
        params.append(filters.language)
    params.append(filters.limit)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT news.article_id, news.source_domain, news.body_document_version
            FROM live_news AS news
            LEFT JOIN live_news_content_job AS job ON job.article_id = news.article_id
            WHERE {" AND ".join(clauses)}
            ORDER BY news.discovered_at DESC, news.article_id
            LIMIT %s
            """,
            tuple(params),
        )
        return [dict(row) for row in cursor.fetchall()]


def enqueue_structured_backfill(
    connection: Any,
    filters: BackfillFilters,
    *,
    dry_run: bool,
    allowlist: SourceAllowlist | None = None,
    local_research_allowed: bool = False,
) -> int:
    def select() -> list[tuple[str, Any]]:
        candidates = _select_candidates(
            connection,
            filters,
            include_link_only=allowlist is not None,
        )
        selected: list[tuple[str, Any]] = []
        if allowlist is None:
            return [(str(row["article_id"]), None) for row in candidates]
        for row in candidates:
            source = allowlist.match(str(row.get("source_domain") or ""))
            if source is None or source.content.mode == "link_only":
                continue
            if source.content.access_scope == "local_research" and not local_research_allowed:
                raise ValueError("local research full text is disabled")
            if row.get("body_document_version") == source.content.target_extraction_version:
                continue
            selected.append((str(row["article_id"]), source.content))
        return selected

    if dry_run:
        return len(select())
    with connection.transaction():
        selected = select()
        if allowlist is not None:
            now = datetime.now(UTC)
            for article_id, policy in selected:
                ensure_content_job(connection, article_id, policy, now=now)
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE live_news_content_job
                        SET requested_by = 'operator_backfill',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE article_id = %s
                        """,
                        (article_id,),
                    )
            return len(selected)
        article_ids = [article_id for article_id, _policy in selected]
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
