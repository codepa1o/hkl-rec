from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.live_news.allowlist import SourceAllowlist
from backend.app.live_news.content_document import StructuredBodyDocument
from backend.app.live_news.ranking import (
    LiveCandidate,
    diversify_live_candidates,
    freshness_score,
    score_live_candidate,
)
from backend.app.news_spaces.types import LiveLanguage, validate_article_id_shape
from backend.app.repositories._utils import new_request_id
from backend.app.repositories.connection import PostgresConnectionPool
from backend.app.repositories.sponsored_dao import (
    claim_feed_request,
    complete_feed_request,
    load_feed_session_news_ids,
)
from backend.app.schemas.article import ArticleCardResponse, ContentEnsureResponse
from backend.app.schemas.category import CategoryListResponse
from backend.app.schemas.feed import (
    FeedItem,
    FeedItemScores,
    FeedResponse,
    FeedUpdateStatusResponse,
)
from backend.app.schemas.search import (
    SearchItem,
    SearchItemScores,
    SearchRequest,
    SearchResponse,
)
from backend.app.schemas.suggestion import SuggestionListResponse

BODY_EXCERPT_LIMIT = 1000


def _visible_body(value: dict[str, Any]) -> str | None:
    if value.get("body_status") != "available":
        return None
    body = str(value.get("body_text") or "")
    rights = str(value.get("content_rights") or "link_only")
    if not body or rights == "link_only":
        return None
    if rights == "full_text" or len(body) <= BODY_EXCERPT_LIMIT:
        return body
    excerpt = body[:BODY_EXCERPT_LIMIT]
    paragraph_end = excerpt.rfind("\n\n")
    return excerpt[:paragraph_end] if paragraph_end >= 700 else excerpt


def _visible_document(value: dict[str, Any]) -> StructuredBodyDocument | None:
    if (
        value.get("content_rights") != "full_text"
        or value.get("body_structure_status") != "available"
        or value.get("body_document_version") != "structured-1"
        or value.get("body_document") is None
    ):
        return None
    try:
        return StructuredBodyDocument.model_validate(value["body_document"])
    except ValidationError:
        return None


class LiveNewsSpaceRepository:
    def __init__(
        self,
        connection_pool: PostgresConnectionPool,
        settings: Settings,
        allowlist: SourceAllowlist,
    ) -> None:
        self._connection_pool = connection_pool
        self._settings = settings
        self._allowlist = allowlist

    def get_feed(
        self,
        *,
        user_id: int,
        page_size: int,
        debug: bool,
        request_id: str | None,
        cursor: str | None,
        language: LiveLanguage,
    ) -> FeedResponse:
        request_id = request_id or new_request_id(self._settings.request_id_prefix, "live-feed")
        connection = self._connection_pool.connect()
        try:
            connection.begin()
            claim = claim_feed_request(
                connection,
                request_id=request_id,
                source_space="live",
                user_id=user_id,
                page_size=page_size,
                debug=debug,
                include_sponsored=False,
                experiment_arm="default",
                as_of_ts=None,
                category=f"language:{language}",
                cursor_token=cursor,
            )
            seen = load_feed_session_news_ids(
                connection,
                session_id=claim.session_id,
                source_space="live",
                exclude_request_id=request_id,
            )
            candidates = self._load_candidates(connection, language=language, excluded=seen)
            now = datetime.now(UTC)
            selected = diversify_live_candidates(
                candidates,
                limit=page_size,
                language=language,
                now=now,
            )
            items = [self._feed_item(candidate, now=now) for candidate in selected]
            has_more = len(candidates) > len(selected)
            proposed_cursor = (
                claim.next_cursor
                or new_request_id(self._settings.request_id_prefix, "live-feed-cursor")
                if has_more
                else None
            )
            next_cursor = complete_feed_request(
                connection,
                request_id=request_id,
                source_space="live",
                news_ids=[item.article_id for item in items],
                next_cursor=proposed_cursor,
            )
            connection.commit()
            return FeedResponse(
                source_space="live",
                user_id=user_id,
                request_id=request_id,
                items=items,
                next_cursor=next_cursor,
                has_more=has_more,
                debug=None,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_feed_update_status(
        self,
        *,
        language: LiveLanguage,
        since: datetime,
    ) -> FeedUpdateStatusResponse:
        language_clause = "" if language == "all" else "AND language = %s"
        params: tuple[Any, ...] = () if language == "all" else (language,)
        connection = self._connection_pool.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT MAX(discovered_at) AS current_watermark
                    FROM live_news
                    WHERE status = 'active'
                      AND discovered_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                      {language_clause}
                    """,
                    params,
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        current_watermark = cast(datetime | None, row["current_watermark"] if row else None)
        return FeedUpdateStatusResponse(
            source_space="live",
            has_updates=current_watermark is not None and current_watermark > since,
            current_watermark=current_watermark,
        )

    def search(self, payload: SearchRequest) -> SearchResponse:
        query = " ".join((payload.query_text or payload.query_key or "").split())
        if not query:
            raise ValueError("Live search requires non-empty query text")
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        connection = self._connection_pool.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM live_news
                    WHERE status = 'active'
                      AND discovered_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                      AND (
                        title ILIKE %s ESCAPE '\\'
                        OR summary ILIKE %s ESCAPE '\\'
                        OR publisher ILIKE %s ESCAPE '\\'
                        OR source_domain ILIKE %s ESCAPE '\\'
                      )
                    ORDER BY discovered_at DESC, article_id ASC
                    LIMIT %s
                    """,
                    (pattern, pattern, pattern, pattern, payload.page_size * 10),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        finally:
            connection.close()
        now = datetime.now(UTC)
        lowered = query.casefold()
        ranked: list[tuple[float, SearchItem]] = []
        for row in rows:
            candidate = self._candidate(row)
            title = candidate.title.casefold()
            summary = candidate.summary.casefold()
            publisher = candidate.publisher.casefold()
            domain = candidate.source_domain.casefold()
            lexical = (
                1.0
                if lowered in title
                else 0.7
                if lowered in summary
                else 0.5
                if lowered in publisher
                else 0.4
                if lowered in domain
                else 0.0
            )
            final_score = round(
                0.8 * lexical
                + 0.2 * freshness_score((now - candidate.best_timestamp).total_seconds()),
                8,
            )
            ranked.append((final_score, self._search_item(candidate, final_score)))
        ranked.sort(key=lambda item: (-item[0], item[1].article_id))
        request_id = payload.event_id or new_request_id(
            self._settings.request_id_prefix, "live-search"
        )
        return SearchResponse(
            source_space="live",
            user_id=payload.user_id,
            request_id=request_id,
            query_key=query,
            items=[item for _, item in ranked[: payload.page_size]],
            debug=None,
        )

    def get_article(self, article_id: str) -> ArticleCardResponse:
        validate_article_id_shape("live", article_id)
        connection = self._connection_pool.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM live_news WHERE article_id = %s AND status = 'active'",
                    (article_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if row is None:
            raise LookupError(f"live news not found: {article_id}")
        value = dict(row)
        body_document = _visible_document(value)
        structure_status = value.get("body_structure_status") or "missing"
        if structure_status == "available" and body_document is None:
            structure_status = "failed"
        return ArticleCardResponse(
            source_space="live",
            article_id=article_id,
            title=str(value["title"]),
            abstract=str(value.get("summary") or ""),
            url=str(value["canonical_url"]),
            source_domain=str(value["source_domain"]),
            category="",
            subcategory="",
            categories=[],
            title_entities=[],
            abstract_entities=[],
            image_url=value.get("image_url"),
            publisher=str(value.get("publisher") or value["source_domain"]),
            language=value.get("language"),
            published_at=value.get("published_at"),
            discovered_at=value.get("discovered_at"),
            body_text=_visible_body(value),
            body_status=value.get("body_status") or "metadata_only",
            body_source=value.get("body_source"),
            content_rights=value.get("content_rights") or "link_only",
            body_document=body_document,
            body_structure_status=structure_status,
            body_document_version=(
                str(value["body_document_version"])
                if body_document and value.get("body_document_version")
                else None
            ),
        )

    def validate_article_id(self, article_id: str) -> None:
        self.get_article(article_id)

    def ensure_structured_content(self, article_id: str) -> ContentEnsureResponse:
        validate_article_id_shape("live", article_id)
        connection = self._connection_pool.connect()
        try:
            with connection.transaction(), connection.cursor() as cursor:
                cursor.execute(
                    """
                        SELECT source_domain, content_rights, body_document_version,
                               body_structure_status
                        FROM live_news
                        WHERE article_id = %s AND status = 'active'
                        FOR UPDATE
                        """,
                    (article_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise LookupError(f"live news not found: {article_id}")
                policy = self._allowlist.match(str(row["source_domain"]))
                if (
                    policy is None
                    or policy.content.mode == "link_only"
                    or row["content_rights"] == "link_only"
                ):
                    cursor.execute(
                        """
                            UPDATE live_news
                            SET body_structure_status = 'blocked',
                                body_structure_updated_at = CURRENT_TIMESTAMP
                            WHERE article_id = %s
                            """,
                        (article_id,),
                    )
                    return ContentEnsureResponse(
                        article_id=article_id,
                        status="blocked",
                        enqueued=False,
                        retry_after_seconds=None,
                    )
                if (
                    row["body_structure_status"] == "available"
                    and row["body_document_version"] == "structured-1"
                ):
                    return ContentEnsureResponse(
                        article_id=article_id,
                        status="available",
                        enqueued=False,
                        retry_after_seconds=None,
                    )
                cursor.execute(
                    """
                        INSERT INTO live_news_content_job (
                          article_id, status, attempt_count, next_attempt_at,
                          target_extraction_version, requested_by, created_at, updated_at
                        ) VALUES (
                          %s, 'pending', 0, CURRENT_TIMESTAMP,
                          'structured-1', 'detail_on_demand',
                          CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        ON CONFLICT (article_id) DO UPDATE SET
                          status = CASE
                              WHEN live_news_content_job.status = 'fetching' THEN 'fetching'
                              ELSE 'pending'
                          END,
                          next_attempt_at = CURRENT_TIMESTAMP,
                          target_extraction_version = 'structured-1',
                          requested_by = 'detail_on_demand',
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
            return ContentEnsureResponse(
                article_id=article_id,
                status="pending",
                enqueued=True,
                retry_after_seconds=5,
            )
        finally:
            connection.close()

    def list_categories(self) -> CategoryListResponse:
        return CategoryListResponse(source_space="live", items=[])

    def list_search_suggestions(self) -> SuggestionListResponse:
        return SuggestionListResponse(source_space="live", items=[])

    def _load_candidates(
        self,
        connection: Any,
        *,
        language: LiveLanguage,
        excluded: set[str],
    ) -> list[LiveCandidate]:
        language_clause = "" if language == "all" else "AND language = %s"
        params: list[Any] = [] if language == "all" else [language]
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM live_news
                WHERE status = 'active'
                  AND discovered_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                  {language_clause}
                ORDER BY discovered_at DESC, article_id ASC
                LIMIT 1000
                """,
                tuple(params),
            )
            rows = [dict(row) for row in cursor.fetchall()]
        return [self._candidate(row) for row in rows if str(row["article_id"]) not in excluded]

    def _candidate(self, row: dict[str, Any]) -> LiveCandidate:
        domain = str(row["source_domain"])
        policy = self._allowlist.match(domain)
        discovered_at = cast(datetime, row["discovered_at"])
        best_timestamp = cast(datetime | None, row.get("published_at")) or discovered_at
        return LiveCandidate(
            article_id=str(row["article_id"]),
            title=str(row["title"]),
            summary=str(row.get("summary") or ""),
            image_url=cast(str | None, row.get("image_url")),
            publisher=str(row.get("publisher") or domain),
            source_domain=domain,
            language=cast(Literal["zh", "en"], row["language"]),
            best_timestamp=best_timestamp,
            discovered_at=discovered_at,
            publisher_quality=policy.quality_weight if policy else 0.0,
            row=row,
        )

    @staticmethod
    def _feed_item(candidate: LiveCandidate, *, now: datetime) -> FeedItem:
        final_score = score_live_candidate(candidate, now)
        row = candidate.row
        return FeedItem(
            source_space="live",
            article_id=candidate.article_id,
            title=candidate.title,
            abstract=candidate.summary,
            url=str(row["canonical_url"]),
            source_domain=candidate.source_domain,
            category="",
            subcategory="",
            categories=[],
            selected_reason="live_fresh",
            scores=FeedItemScores(
                base_recall_score=final_score,
                personalized_topic_score=0.0,
                default_topic_score=0.0,
                topic_match_score=0.0,
                query_recall_boost=0.0,
                final_score=final_score,
                profile_v2_score=None,
                sponsored_score=None,
            ),
            recall_sources=["live_freshness"],
            is_fallback=False,
            content_type="organic",
            sponsored=None,
            image_url=candidate.image_url,
            publisher=candidate.publisher,
            language=candidate.language,
            published_at=row.get("published_at"),
            discovered_at=candidate.discovered_at,
        )

    @staticmethod
    def _search_item(candidate: LiveCandidate, final_score: float) -> SearchItem:
        row = candidate.row
        return SearchItem(
            source_space="live",
            article_id=candidate.article_id,
            title=candidate.title,
            abstract=candidate.summary,
            url=str(row["canonical_url"]),
            source_domain=candidate.source_domain,
            category="",
            subcategory="",
            categories=[],
            scores=SearchItemScores(
                topic_match_score=0.0,
                bm25_score=0.0,
                dense_score=0.0,
                hybrid_score=final_score,
                final_score=final_score,
            ),
            image_url=candidate.image_url,
            publisher=candidate.publisher,
            language=candidate.language,
            published_at=row.get("published_at"),
            discovered_at=candidate.discovered_at,
        )
