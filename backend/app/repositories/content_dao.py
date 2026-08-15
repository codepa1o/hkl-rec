from __future__ import annotations

from typing import Any

from backend.app.config import SearchRetrievalMode
from backend.app.repositories._utils import placeholders
from backend.app.schemas.common import TopicCard
from backend.app.schemas.event import SearchQueryTopic
from backend.app.schemas.search import SearchMatchedTopic
from backend.app.search_retrieval import HybridHit


def load_answer_ids_for_topics(
    connection: Any,
    topic_ids: list[int],
    limit: int,
    *,
    as_of_ts: int | None = None,
) -> list[dict[str, Any]]:
    if not topic_ids:
        return []
    ph = placeholders(topic_ids)
    if as_of_ts is None:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT DISTINCT at.answer_id, a.hot_score
                FROM answer_topic at
                JOIN answer a ON a.answer_id = at.answer_id
                WHERE at.topic_id IN ({ph})
                ORDER BY a.hot_score DESC, at.answer_id ASC
                LIMIT %s
                """,
                (*tuple(topic_ids), limit),
            )
            return list(cursor.fetchall())
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT
              at.answer_id,
              (
                COALESCE(stats.click_count, 0) * 10
                + COALESCE(stats.impression_count, 0)
              ) AS hot_score
            FROM answer_topic at
            JOIN answer a ON a.answer_id = at.answer_id
            LEFT JOIN (
              SELECT
                answer_id,
                COUNT(*) FILTER (WHERE event_type = 'feed_impression') AS impression_count,
                COUNT(*) FILTER (WHERE event_type IN (
                  'recommendation_click',
                  'search_result_click',
                  'upvote'
                )) AS click_count
              FROM user_event
              WHERE derived_from_raw IS TRUE
                AND event_ts < %s
                AND answer_id IS NOT NULL
              GROUP BY answer_id
            ) stats ON stats.answer_id = at.answer_id
            WHERE at.topic_id IN ({ph})
              AND (a.create_ts IS NULL OR a.create_ts <= %s)
            ORDER BY hot_score DESC, at.answer_id ASC
            LIMIT %s
            """,
            (as_of_ts, *tuple(topic_ids), as_of_ts, limit),
        )
        return list(cursor.fetchall())


def load_hot_fallback_rows(
    connection: Any,
    limit: int,
    *,
    as_of_ts: int | None = None,
) -> list[dict[str, Any]]:
    if as_of_ts is not None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  a.answer_id,
                  (
                    COALESCE(stats.click_count, 0) * 10
                    + COALESCE(stats.impression_count, 0)
                  ) AS hot_score,
                  ROW_NUMBER() OVER (
                    ORDER BY
                      (
                        COALESCE(stats.click_count, 0) * 10
                        + COALESCE(stats.impression_count, 0)
                      ) DESC,
                      a.answer_id ASC
                  ) AS rank_position
                FROM answer a
                LEFT JOIN (
                  SELECT
                    answer_id,
                    COUNT(*) FILTER (WHERE event_type = 'feed_impression') AS impression_count,
                    COUNT(*) FILTER (WHERE event_type IN (
                      'recommendation_click',
                      'search_result_click',
                      'upvote'
                    )) AS click_count
                  FROM user_event
                  WHERE derived_from_raw IS TRUE
                    AND event_ts < %s
                    AND answer_id IS NOT NULL
                  GROUP BY answer_id
                ) stats ON stats.answer_id = a.answer_id
                WHERE a.is_demo_selected IS TRUE
                  AND (a.create_ts IS NULL OR a.create_ts <= %s)
                ORDER BY hot_score DESC, a.answer_id ASC
                LIMIT %s
                """,
                (as_of_ts, as_of_ts, limit),
            )
            return list(cursor.fetchall())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT answer_id, hot_score, rank_position
            FROM hot_answer_snapshot
            WHERE snapshot_key = (
              SELECT MIN(snapshot_key)
              FROM hot_answer_snapshot
            )
            ORDER BY rank_position ASC
            LIMIT %s
            """,
            (limit,),
        )
        return list(cursor.fetchall())


def load_answer_event_counts_as_of(
    connection: Any,
    answer_ids: list[int],
    *,
    as_of_ts: int,
) -> dict[int, dict[str, int | float]]:
    if not answer_ids:
        return {}
    ph = placeholders(answer_ids)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
              answer_id,
              COUNT(*) FILTER (WHERE event_type = 'feed_impression') AS impression_count,
              COUNT(*) FILTER (WHERE event_type IN (
                'recommendation_click',
                'search_result_click',
                'upvote'
              )) AS click_count
            FROM user_event
            WHERE derived_from_raw IS TRUE
              AND event_ts < %s
              AND answer_id IN ({ph})
            GROUP BY answer_id
            """,
            (as_of_ts, *tuple(answer_ids)),
        )
        rows = cursor.fetchall()
    result: dict[int, dict[str, int | float]] = {}
    for row in rows:
        answer_id = int(row["answer_id"])
        click_count = int(row.get("click_count") or 0)
        impression_count = int(row.get("impression_count") or 0)
        result[answer_id] = {
            "click_count": click_count,
            "impression_count": impression_count,
            "hot_score": float(click_count * 10 + impression_count),
        }
    return result


def load_answer_ids_created_as_of(
    connection: Any,
    answer_ids: list[int],
    *,
    as_of_ts: int,
) -> set[int]:
    if not answer_ids:
        return set()
    ph = placeholders(answer_ids)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT answer_id
            FROM answer
            WHERE answer_id IN ({ph})
              AND (create_ts IS NULL OR create_ts <= %s)
            """,
            (*tuple(answer_ids), as_of_ts),
        )
        return {int(row["answer_id"]) for row in cursor.fetchall()}


def load_answer_rows(connection: Any, answer_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not answer_ids:
        return {}
    ph = placeholders(answer_ids)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
              a.answer_id,
              a.question_id,
              a.author_id,
              a.display_summary AS abstract,
              a.hot_score,
              a.click_count,
              a.impression_count,
              a.has_picture,
              a.has_video,
              a.is_high_value,
              a.is_editor_recommended,
              a.create_ts,
              a.likes_count,
              a.collection_count,
              q.display_title AS headline,
              au.display_name AS source_domain,
              au.is_excellent_answerer,
              au.follower_count AS author_follower_count
            FROM answer a
            LEFT JOIN question q ON q.question_id = a.question_id
            LEFT JOIN author au ON au.author_id = a.author_id
            WHERE a.answer_id IN ({ph})
            """,
            tuple(answer_ids),
        )
        return {int(row["answer_id"]): row for row in cursor.fetchall()}


def load_topics_by_answer(
    connection: Any,
    answer_ids: list[int],
) -> dict[int, list[TopicCard]]:
    if not answer_ids:
        return {}
    ph = placeholders(answer_ids)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
              at.answer_id,
              t.topic_id,
              t.display_name
            FROM answer_topic at
            JOIN topic t ON t.topic_id = at.topic_id
            WHERE at.answer_id IN ({ph})
            ORDER BY at.answer_id ASC, at.source_rank ASC, t.topic_id ASC
            """,
            tuple(answer_ids),
        )
        rows = cursor.fetchall()

    topics_by_answer: dict[int, list[TopicCard]] = {}
    for row in rows:
        answer_id = int(row["answer_id"])
        topic_id = int(row["topic_id"])
        topics_by_answer.setdefault(answer_id, []).append(
            TopicCard(
                topic_id=topic_id,
                display_name=row.get("display_name") or f"Topic {topic_id}",
            )
        )
    return topics_by_answer


def load_answer_topic_ids(connection: Any, answer_id: int) -> list[int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT topic_id
            FROM answer_topic
            WHERE answer_id = %s
            ORDER BY source_rank ASC, topic_id ASC
            """,
            (answer_id,),
        )
        return [int(row["topic_id"]) for row in cursor.fetchall()]


def load_query_topics(connection: Any, query_key: str) -> list[SearchQueryTopic]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT topic_id, score
            FROM query_topic_map
            WHERE query_key = %s
            ORDER BY match_rank ASC, score DESC
            LIMIT 20
            """,
            (query_key,),
        )
        rows = cursor.fetchall()
    return [
        SearchQueryTopic(
            topic_id=int(row["topic_id"]),
            score=float(row.get("score") or 0.0),
        )
        for row in rows
    ]


def load_search_matched_topics(
    connection: Any,
    query_key: str,
) -> list[SearchMatchedTopic]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT topic_id, score, match_rank
            FROM query_topic_map
            WHERE query_key = %s
            ORDER BY match_rank ASC, score DESC
            LIMIT 20
            """,
            (query_key,),
        )
        rows = cursor.fetchall()
    return [
        SearchMatchedTopic(
            topic_id=int(row["topic_id"]),
            score=float(row.get("score") or 0.0),
            rank=int(row.get("match_rank") or index + 1),
        )
        for index, row in enumerate(rows)
    ]


def load_search_candidates(
    connection: Any,
    query_key: str,
    page_size: int,
    query_text: str | None = None,
    *,
    retrieval_mode: SearchRetrievalMode = "lexical_v1",
    hybrid_hits: tuple[HybridHit, ...] = (),
) -> dict[int, dict[str, Any]]:
    limit = max(page_size * 20, 50)
    if hybrid_hits:
        return {
            hit.article_id: {
                "source": (
                    "bm25+dense"
                    if hit.bm25_rank is not None and hit.dense_rank is not None
                    else "bm25"
                    if hit.bm25_rank is not None
                    else "dense"
                ),
                "topic_match_score": 0.0,
                "bm25_score": hit.bm25_score,
                "dense_score": hit.dense_score,
                "hybrid_score": hit.fusion_score,
            }
            for hit in hybrid_hits[:limit]
        }

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              at.answer_id,
              SUM(qtm.score) AS topic_match_score,
              MAX(a.hot_score) AS hot_score
            FROM query_topic_map qtm
            JOIN answer_topic at ON at.topic_id = qtm.topic_id
            JOIN answer a ON a.answer_id = at.answer_id
            WHERE qtm.query_key = %s
            GROUP BY at.answer_id
            ORDER BY topic_match_score DESC, at.answer_id ASC
            LIMIT %s
            """,
            (query_key, limit),
        )
        rows = cursor.fetchall()

    candidates = {
        int(row["answer_id"]): {
            "source": "topic_lookup",
            "topic_match_score": float(row.get("topic_match_score") or 0.0),
            "bm25_score": 0.0,
            "dense_score": 0.0,
            "hybrid_score": 0.0,
        }
        for row in rows
    }

    normalized_text = (
        " ".join((query_text or "").lower().split()) if retrieval_mode == "lexical_v1" else ""
    )
    tokens = [token for token in normalized_text.split() if len(token) >= 3][:5]
    search_terms = [term for term in (normalized_text, *tokens) if len(term) >= 3]
    search_terms = list(dict.fromkeys(search_terms))
    if search_terms:
        predicates = []
        predicate_params: list[object] = []
        score_parts = []
        score_params: list[object] = []
        for term in search_terms:
            predicates.append(
                "(LOWER(q.display_title) LIKE %s OR LOWER(a.display_summary) LIKE %s)"
            )
            contains = f"%{term}%"
            predicate_params.extend((contains, contains))
            score_parts.append(
                "(CASE WHEN LOWER(q.display_title) LIKE %s THEN 2 ELSE 0 END "
                "+ CASE WHEN LOWER(a.display_summary) LIKE %s THEN 1 ELSE 0 END)"
            )
            score_params.extend((contains, contains))
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                  a.answer_id,
                  ({" + ".join(score_parts)}) AS lexical_score,
                  a.hot_score
                FROM answer a
                JOIN question q ON q.question_id = a.question_id
                WHERE {" OR ".join(predicates)}
                ORDER BY lexical_score DESC, a.hot_score DESC, a.answer_id ASC
                LIMIT %s
                """,
                (
                    *score_params,
                    *predicate_params,
                    limit,
                ),
            )
            lexical_rows = cursor.fetchall()
        for row in lexical_rows:
            article_id = int(row["answer_id"])
            lexical_score = float(row.get("lexical_score") or 0.0) / (3.0 * len(search_terms))
            is_new = article_id not in candidates
            candidate: dict[str, Any] = candidates.setdefault(
                article_id,
                {
                    "source": "lexical_match",
                    "topic_match_score": 0.0,
                    "bm25_score": 0.0,
                    "dense_score": 0.0,
                    "hybrid_score": 0.0,
                },
            )
            if is_new:
                candidate["source"] = "lexical_match"
            elif "lexical_match" not in str(candidate["source"]):
                candidate["source"] = f"{candidate['source']}+lexical_match"
            candidate["topic_match_score"] = max(
                float(candidate["topic_match_score"]),
                lexical_score,
            )

    return candidates
