from __future__ import annotations

from typing import Any, cast

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
    ProfileRecentQuery,
    VectorSummary,
)


def fetch_profile_row(
    connection: Any,
    user_id: int,
    *,
    for_update: bool = False,
) -> dict[str, Any]:
    lock_clause = " FOR UPDATE" if for_update else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
              user_id,
              cold_start_seed_key,
              topic_weights_json,
              recent_clicked_answers_json,
              recent_queries_json,
              behavior_score
            FROM user_profile
            WHERE user_id = %s
            {lock_clause}
            """,
            (user_id,),
        )
        row = cast(dict[str, Any] | None, cursor.fetchone())
    if row is None:
        raise LookupError(f"user_profile row not found for user_id={user_id}")
    return row


def profile_from_row(row: dict[str, Any]) -> DebugProfileResponse:
    topic_weights = parse_topic_weights(row.get("topic_weights_json"))
    recent_clicks = parse_recent_clicks(row.get("recent_clicked_answers_json"))
    recent_queries = parse_recent_queries(row.get("recent_queries_json"))
    return DebugProfileResponse(
        user_id=int(row["user_id"]),
        cold_start_seed_key=row.get("cold_start_seed_key") or "cold_start_default",
        behavior_score=float(row.get("behavior_score") or 0.0),
        topic_weights=topic_weights,
        recent_clicked_articles=recent_clicks,
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
) -> dict[int, float]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT topic_weights_json
            FROM system_profile_seed
            WHERE seed_key = %s
            """,
            (seed_key,),
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
            SELECT query_key, topic_id, score
            FROM query_topic_map
            WHERE query_key IN ({ph})
            ORDER BY query_key, match_rank ASC
            """,
            tuple(query_keys),
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
