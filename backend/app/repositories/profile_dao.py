from __future__ import annotations

from typing import Any, cast

from backend.app.news_spaces.types import NewsSpace
from backend.app.repositories._utils import (
    parse_recent_clicks,
    parse_recent_queries,
    parse_topic_weights,
    placeholders,
)
from backend.app.repositories.search_signal import (
    SearchSignalConfig,
    query_can_open_recall,
    recent_query_multiplier,
)
from backend.app.schemas.profile import (
    DebugProfileResponse,
    ProfileRecentClick,
    ProfileRecentQuery,
    VectorSummary,
)


def attach_recent_click_titles(
    recent_clicks: list[ProfileRecentClick],
    news_rows: dict[str, dict[str, Any]],
) -> list[ProfileRecentClick]:
    return [
        click.model_copy(
            update={
                "title": str(
                    news_rows.get(click.news_id, {}).get("title")
                    or click.title
                    or "新闻标题暂不可用"
                )
            }
        )
        for click in recent_clicks
    ]


def enrich_recent_click_titles(
    connection: Any,
    recent_clicks: list[ProfileRecentClick],
    source_space: NewsSpace,
) -> list[ProfileRecentClick]:
    article_ids = [click.news_id for click in recent_clicks]
    if not article_ids:
        return []
    if source_space == "mind":
        query = "SELECT news_id AS article_id, title FROM mind_news WHERE news_id = ANY(%s)"
    else:
        query = "SELECT article_id, title FROM live_news WHERE article_id = ANY(%s)"
    with connection.cursor() as cursor:
        cursor.execute(query, (article_ids,))
        news_rows = {str(row["article_id"]): dict(row) for row in cursor.fetchall()}
    return attach_recent_click_titles(recent_clicks, news_rows)


def fetch_profile_row(
    connection: Any,
    user_id: int,
    source_space: NewsSpace = "mind",
    *,
    for_update: bool = False,
) -> dict[str, Any]:
    lock_clause = " FOR UPDATE" if for_update else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
              user_id,
              source_space,
              cold_start_seed_key,
              topic_weights_json,
              recent_clicked_news_json,
              recent_queries_json,
              behavior_score,
              user_vector_json
            FROM user_profile
            WHERE user_id = %s AND source_space = %s
            {lock_clause}
            """,
            (user_id, source_space),
        )
        row = cast(dict[str, Any] | None, cursor.fetchone())
    if row is None:
        raise LookupError(
            f"user_profile row not found for user_id={user_id}, source_space={source_space!r}"
        )
    return row


def ensure_profile_row(
    connection: Any,
    user_id: int,
    source_space: NewsSpace,
) -> dict[str, Any]:
    seed_key = "live_cold_start_default" if source_space == "live" else "cold_start_default"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO user_profile (
              user_id,
              source_space,
              cold_start_seed_key,
              topic_weights_json,
              recent_clicked_news_json,
              recent_queries_json,
              behavior_score,
              user_vector_json,
              notes
            )
            SELECT
              %s,
              %s,
              seed_key,
              CASE WHEN %s = 'live' THEN '[]'::jsonb ELSE topic_weights_json END,
              '[]'::jsonb,
              '[]'::jsonb,
              0,
              NULL,
              %s
            FROM system_profile_seed
            WHERE seed_key = %s AND source_space = %s
            ON CONFLICT (user_id, source_space) DO NOTHING
            """,
            (
                user_id,
                source_space,
                source_space,
                f"{source_space} cold-start profile",
                seed_key,
                source_space,
            ),
        )
    return fetch_profile_row(connection, user_id, source_space)


def profile_from_row(row: dict[str, Any]) -> DebugProfileResponse:
    topic_weights = parse_topic_weights(row.get("topic_weights_json"))
    recent_clicks = parse_recent_clicks(row.get("recent_clicked_news_json"))
    recent_queries = parse_recent_queries(row.get("recent_queries_json"))
    return DebugProfileResponse(
        source_space=cast(NewsSpace, str(row.get("source_space") or "mind")),
        user_id=int(row["user_id"]),
        cold_start_seed_key=row.get("cold_start_seed_key") or "cold_start_default",
        behavior_score=float(row.get("behavior_score") or 0.0),
        topic_weights=topic_weights,
        recent_clicked_news=recent_clicks,
        recent_queries=recent_queries,
        vector_summary=VectorSummary(
            vector_key_count=len(topic_weights),
            top_contributing_topics=topic_weights,
        ),
    )


def load_default_seed_topic_weights(
    connection: Any,
    *,
    seed_key: str,
    source_space: NewsSpace = "mind",
) -> dict[int, float]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT topic_weights_json
            FROM system_profile_seed
            WHERE seed_key = %s AND source_space = %s
            """,
            (seed_key, source_space),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            f"system_profile_seed[{seed_key!r}] missing — "
            "the PostgreSQL migration must populate the cold-start seed before /feed"
        )
    weights = parse_topic_weights(row.get("topic_weights_json"))
    return {item.topic_id: item.weight for item in weights}


def load_recent_query_topic_scores(
    connection: Any,
    recent_queries: list[ProfileRecentQuery],
    *,
    source_space: NewsSpace = "mind",
    now_ts: int,
    config: SearchSignalConfig,
    confirmed_only: bool = False,
) -> dict[int, float]:
    query_keys = list(dict.fromkeys(item.query_key for item in recent_queries if item.query_key))
    if not query_keys:
        return {}

    ph = placeholders(query_keys)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT query_topic_map.query_key, query_topic_map.topic_id, query_topic_map.score
            FROM query_topic_map
            JOIN topic ON topic.topic_id = query_topic_map.topic_id
            WHERE query_topic_map.query_key IN ({ph})
              AND query_topic_map.source_space = %s
              AND topic.source_space = %s
            ORDER BY query_topic_map.query_key, query_topic_map.match_rank ASC
            """,
            (*query_keys, source_space, source_space),
        )
        rows = cursor.fetchall()

    rows_by_query: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_query.setdefault(str(row["query_key"]), []).append(row)

    scores: dict[int, float] = {}
    for query in recent_queries:
        if confirmed_only and not query_can_open_recall(query, config=config):
            continue
        multiplier = recent_query_multiplier(query, now_ts=now_ts, config=config)
        if multiplier <= 0:
            continue
        for row in rows_by_query.get(query.query_key, []):
            topic_id = int(row["topic_id"])
            effective_score = float(row.get("score") or 0.0) * multiplier
            scores[topic_id] = max(scores.get(topic_id, 0.0), effective_score)
    return scores
