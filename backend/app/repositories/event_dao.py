from __future__ import annotations

from typing import Any

from backend.app.errors import IdempotencyConflictError
from backend.app.events.schema import UserEventMessage
from backend.app.news_spaces.types import NewsSpace
from backend.app.repositories._utils import (
    json_text,
    parse_json,
    query_tokens,
    updated_topic_weights,
)
from backend.app.schemas.event import RecentClickedNews
from backend.app.schemas.profile import ProfileTopicWeight


def _validate_profile_row_source_space(
    profile_row: dict[str, Any],
    source_space: NewsSpace,
) -> None:
    row_source_space = profile_row.get("source_space")
    if row_source_space != source_space:
        raise ValueError(
            "profile_row source_space does not match mutation source_space: "
            f"{row_source_space!r} != {source_space!r}"
        )


def claim_event_id(
    connection: Any,
    event: UserEventMessage,
    *,
    source_space: NewsSpace = "mind",
) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO event_idempotency (
              external_event_id,
              payload_fingerprint,
              user_id,
              event_type,
              source_space
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (external_event_id) DO NOTHING
            """,
            (
                event.event_id,
                event.idempotency_fingerprint,
                event.user_id,
                event.event_type,
                source_space,
            ),
        )
        inserted = int(cursor.rowcount) == 1
        if inserted:
            return True
        cursor.execute(
            """
            SELECT payload_fingerprint, user_id, event_type, source_space
            FROM event_idempotency
            WHERE external_event_id = %s
            """,
            (event.event_id,),
        )
        existing = cursor.fetchone()
    if existing is None:
        raise RuntimeError(f"idempotency claim disappeared: {event.event_id}")
    if (
        str(existing["payload_fingerprint"]) != event.idempotency_fingerprint
        or int(existing["user_id"]) != event.user_id
        or str(existing["event_type"]) != event.event_type
        or str(existing["source_space"]) != source_space
    ):
        raise IdempotencyConflictError(
            f"event_id reused with conflicting payload: {event.event_id}"
        )
    return False


def record_search_query(
    connection: Any,
    user_id: int,
    query_key: str,
    event_ts: int,
    external_event_id: str | None = None,
    *,
    source_space: NewsSpace = "mind",
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO user_event (
              external_event_id,
              source_space,
              user_id,
              event_type,
              query_key,
              query_tokens_json,
              surface,
              source_confidence,
              event_ts
            )
            VALUES (%s, %s, %s, 'search_query', %s, %s, 'search', 'confirmed', %s)
            """,
            (
                external_event_id,
                source_space,
                user_id,
                query_key,
                json_text(query_tokens(query_key) if source_space == "mind" else []),
                event_ts,
            ),
        )


def append_recent_query(
    connection: Any,
    profile_row: dict[str, Any],
    query_key: str,
    event_ts: int,
    behavior_delta: float,
    *,
    source_space: NewsSpace = "mind",
) -> None:
    _validate_profile_row_source_space(profile_row, source_space)
    recent_queries = parse_json(profile_row.get("recent_queries_json"), [])
    next_recent_queries = [
        {
            "query_key": query_key,
            "query_ts": event_ts,
            "query_tokens": query_tokens(query_key) if source_space == "mind" else [],
        },
        *[
            row
            for row in recent_queries
            if isinstance(row, dict) and str(row.get("query_key") or "") != query_key
        ],
    ]
    next_recent_queries.sort(key=lambda row: int(row.get("query_ts") or 0), reverse=True)
    next_recent_queries = next_recent_queries[:5]
    next_behavior_score = float(profile_row.get("behavior_score") or 0.0) + behavior_delta

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE user_profile
            SET
              recent_queries_json = %s,
              behavior_score = %s,
              last_event_ts = %s
            WHERE user_id = %s AND source_space = %s
            """,
            (
                json_text(next_recent_queries),
                next_behavior_score,
                event_ts,
                int(profile_row["user_id"]),
                source_space,
            ),
        )
        if int(cursor.rowcount) != 1:
            raise LookupError(
                "user_profile row not found for "
                f"user_id={profile_row['user_id']}, source_space={source_space!r}"
            )


def confirm_recent_query(
    connection: Any,
    profile_row: dict[str, Any],
    query_key: str,
    event_ts: int,
    *,
    source_space: NewsSpace = "mind",
) -> None:
    _validate_profile_row_source_space(profile_row, source_space)
    recent_queries = parse_json(profile_row.get("recent_queries_json"), [])
    updated = False
    for row in recent_queries:
        if (
            not updated
            and isinstance(row, dict)
            and str(row.get("query_key") or "") == query_key
            and int(row.get("query_ts") or 0) <= event_ts
        ):
            row["confirmed_ts"] = event_ts
            updated = True
    if not updated:
        return

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE user_profile
            SET recent_queries_json = %s
            WHERE user_id = %s AND source_space = %s
            """,
            (json_text(recent_queries), int(profile_row["user_id"]), source_space),
        )
        if int(cursor.rowcount) != 1:
            raise LookupError(
                "user_profile row not found for "
                f"user_id={profile_row['user_id']}, source_space={source_space!r}"
            )


def record_click_event(
    connection: Any,
    user_id: int,
    event_type: str,
    news_id: str,
    query_key: str | None,
    request_id: str | None,
    surface: str,
    event_ts: int,
    topic_ids: list[int],
    external_event_id: str | None = None,
    sponsored_delivery_id: str | None = None,
    campaign_id: int | None = None,
    creative_id: int | None = None,
    dwell_ms: int | None = None,
    source_space: NewsSpace = "mind",
    article_id: str | None = None,
) -> None:
    canonical_article_id = article_id or news_id
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO user_event (
              external_event_id,
              source_space,
              user_id,
              event_type,
              article_id,
              sponsored_delivery_id,
              campaign_id,
              creative_id,
              query_key,
              query_tokens_json,
              topic_ids_json,
              surface,
              request_id,
              dwell_ms,
              source_confidence,
              event_ts
            )
            VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, 'confirmed', %s
            )
            """,
            (
                external_event_id,
                source_space,
                user_id,
                event_type,
                canonical_article_id,
                sponsored_delivery_id,
                campaign_id,
                creative_id,
                query_key,
                json_text(query_tokens(query_key) if source_space == "mind" else [])
                if query_key
                else None,
                json_text(topic_ids),
                surface,
                request_id,
                dwell_ms,
                event_ts,
            ),
        )


def record_log_only_event(
    connection: Any,
    user_id: int,
    event_type: str,
    surface: str,
    news_id: str | None,
    query_key: str | None,
    request_id: str | None,
    event_ts: int,
    debug_payload_json: str | None,
    external_event_id: str | None = None,
    sponsored_delivery_id: str | None = None,
    campaign_id: int | None = None,
    creative_id: int | None = None,
    dwell_ms: int | None = None,
    source_space: NewsSpace = "mind",
    article_id: str | None = None,
) -> bool:
    """插入一条 user_event 记录，但不修改 user_profile。

    用于仅记录日志、不更新行为分数或类别权重的产品事件。
    """
    canonical_article_id = article_id or news_id
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO user_event (
              external_event_id,
              source_space,
              user_id,
              event_type,
              article_id,
              sponsored_delivery_id,
              campaign_id,
              creative_id,
              query_key,
              query_tokens_json,
              topic_ids_json,
              surface,
              request_id,
              dwell_ms,
              source_confidence,
              event_ts,
              debug_payload_json
            )
            VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, 'not_applicable', %s, %s
            )
            """,
            (
                external_event_id,
                source_space,
                user_id,
                event_type,
                canonical_article_id,
                sponsored_delivery_id,
                campaign_id,
                creative_id,
                query_key,
                json_text(query_tokens(query_key) if source_space == "mind" else [])
                if query_key
                else None,
                None,
                surface,
                request_id,
                dwell_ms,
                event_ts,
                debug_payload_json,
            ),
        )
        return True


def apply_click_profile_update(
    connection: Any,
    profile_row: dict[str, Any],
    news_id: str,
    event_ts: int,
    topic_deltas: dict[int, float],
    behavior_delta: float,
    decay_factor: float,
    *,
    source_space: NewsSpace = "mind",
) -> dict[str, Any]:
    _validate_profile_row_source_space(profile_row, source_space)
    current_weights = parse_json(profile_row.get("topic_weights_json"), [])
    next_topic_weights = updated_topic_weights(current_weights, topic_deltas, decay_factor)
    recent_clicks = parse_json(profile_row.get("recent_clicked_news_json"), [])
    next_recent_clicks = [
        {"news_id": news_id, "click_ts": event_ts},
        *[row for row in recent_clicks if isinstance(row, dict)],
    ]
    next_recent_clicks.sort(key=lambda row: int(row.get("click_ts") or 0), reverse=True)
    next_recent_clicks = next_recent_clicks[:10]
    next_behavior_score = float(profile_row.get("behavior_score") or 0.0) + behavior_delta

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE user_profile
            SET
              topic_weights_json = %s,
              recent_clicked_news_json = %s,
              behavior_score = %s,
              last_event_ts = %s
            WHERE user_id = %s AND source_space = %s
            """,
            (
                json_text(next_topic_weights),
                json_text(next_recent_clicks),
                next_behavior_score,
                event_ts,
                int(profile_row["user_id"]),
                source_space,
            ),
        )
        if int(cursor.rowcount) != 1:
            raise LookupError(
                "user_profile row not found for "
                f"user_id={profile_row['user_id']}, source_space={source_space!r}"
            )

    return {
        "topic_weights": [
            ProfileTopicWeight(topic_id=int(row["topic_id"]), weight=float(row["weight"]))
            for row in next_topic_weights
        ],
        "recent_clicked_news": [
            RecentClickedNews(
                news_id=str(row["news_id"]),
                click_ts=int(row.get("click_ts") or 0),
            )
            for row in next_recent_clicks
        ],
        "behavior_score": next_behavior_score,
    }


def validate_feed_request_reference(
    connection: Any,
    *,
    request_id: str,
    source_space: NewsSpace,
    user_id: int,
    article_id: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_space, user_id, returned_news_ids_json
            FROM feed_request
            WHERE request_id = %s
            """,
            (request_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise IdempotencyConflictError(f"unknown feed request_id: {request_id}")
    returned = {str(value) for value in parse_json(row.get("returned_news_ids_json"), [])}
    if (
        str(row["source_space"]) != source_space
        or int(row["user_id"]) != user_id
        or article_id not in returned
    ):
        raise IdempotencyConflictError(
            "feed request does not match event source, user, and article"
        )


def validate_search_request_reference(
    connection: Any,
    *,
    request_id: str,
    source_space: NewsSpace,
    user_id: int,
    query_key: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_space, user_id, query_key
            FROM (
              SELECT source_space, user_id, query_key, 0 AS source_rank
              FROM user_event
              WHERE external_event_id = %s AND event_type = 'search_query'
              UNION ALL
              SELECT
                payload_json ->> 'source_space' AS source_space,
                (payload_json ->> 'user_id')::BIGINT AS user_id,
                payload_json ->> 'query_key' AS query_key,
                1 AS source_rank
              FROM event_outbox
              WHERE event_id = %s
                AND payload_json ->> 'event_type' = 'search_query'
            ) AS request_reference
            ORDER BY source_rank ASC
            LIMIT 1
            """,
            (request_id, request_id),
        )
        row = cursor.fetchone()
    if row is None or (
        str(row["source_space"]) != source_space
        or int(row["user_id"]) != user_id
        or str(row.get("query_key") or "") != query_key
    ):
        raise IdempotencyConflictError(
            "search request does not match event source, user, and query"
        )
