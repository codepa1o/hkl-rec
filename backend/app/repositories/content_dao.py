from __future__ import annotations

from typing import Any

from backend.app.config import SearchRetrievalMode
from backend.app.repositories._utils import parse_json, placeholders
from backend.app.schemas.article import ArticleEntity
from backend.app.schemas.common import TopicCard
from backend.app.schemas.event import SearchQueryTopic
from backend.app.schemas.search import SearchMatchedTopic
from backend.app.search_retrieval import HybridHit


def _category_clause(
    category: str | None,
    *,
    alias: str = "news",
) -> tuple[str, tuple[Any, ...]]:
    if category is None:
        return "", ()
    return f"AND {alias}.category = %s", (category,)


def list_news_categories(connection: Any) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT category AS key, COUNT(*)::BIGINT AS news_count
            FROM mind_news
            WHERE category IS NOT NULL AND category <> ''
            GROUP BY category
            ORDER BY news_count DESC, key ASC
            """
        )
        return list(cursor.fetchall())


def news_category_exists(connection: Any, category: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM mind_news WHERE category = %s) AS exists",
            (category,),
        )
        row = cursor.fetchone()
    return bool(row and row["exists"])


def load_catalog_identity(connection: Any) -> tuple[str, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT normalized_fingerprint, news_count
            FROM mind_catalog_import
            ORDER BY imported_at DESC
            LIMIT 2
            """
        )
        rows = cursor.fetchall()
    if len(rows) != 1:
        raise RuntimeError(f"expected one active MIND catalog, found {len(rows)}")
    return str(rows[0]["normalized_fingerprint"]), int(rows[0]["news_count"])


def parse_mind_entities(value: Any) -> list[ArticleEntity]:
    raw_entities = parse_json(value, [])
    if not isinstance(raw_entities, list):
        return []
    type_names = {"P": "person", "O": "organization", "G": "location"}
    entities: list[ArticleEntity] = []
    seen: set[str] = set()
    for raw in raw_entities:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("Label") or "").strip()
        if not label:
            continue
        type_code = str(raw.get("Type") or "").strip().upper()
        wikidata_id = str(raw.get("WikidataId") or "").strip() or None
        dedupe_key = f"wikidata:{wikidata_id.lower()}" if wikidata_id else f"label:{label.lower()}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        confidence: float | None = None
        try:
            parsed_confidence = float(raw["Confidence"])
            if 0.0 <= parsed_confidence <= 1.0:
                confidence = parsed_confidence
        except (KeyError, TypeError, ValueError):
            pass
        raw_surface_forms = raw.get("SurfaceForms")
        surface_forms = (
            list(
                dict.fromkeys(
                    str(item).strip()
                    for item in raw_surface_forms
                    if isinstance(item, str) and item.strip()
                )
            )
            if isinstance(raw_surface_forms, list)
            else []
        )
        entities.append(
            ArticleEntity(
                label=label,
                entity_type=type_names.get(type_code, "other"),
                type_code=type_code,
                wikidata_id=wikidata_id,
                confidence=confidence,
                surface_forms=surface_forms,
            )
        )
    return entities


def load_news_ids_for_topics(
    connection: Any,
    topic_ids: list[int],
    limit: int,
    *,
    as_of_ts: int | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    if not topic_ids:
        return []
    topic_placeholders = placeholders(topic_ids)
    as_of_clause = (
        "AND stats.first_seen_ts IS NOT NULL AND stats.first_seen_ts <= %s"
        if as_of_ts is not None
        else ""
    )
    category_clause, category_params = _category_clause(category)
    params: tuple[Any, ...] = (*topic_ids,)
    params += category_params
    if as_of_ts is not None:
        params += (as_of_ts,)
    params += (limit,)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT news.news_id, stats.hot_score
            FROM mind_news AS news
            JOIN mind_news_stats AS stats USING (news_id)
            WHERE EXISTS (
                SELECT 1
                FROM mind_news_topic AS mapping
                WHERE mapping.news_id = news.news_id
                  AND mapping.topic_id IN ({topic_placeholders})
            )
              {category_clause}
              {as_of_clause}
            ORDER BY stats.hot_score DESC, news.news_id ASC
            LIMIT %s
            """,
            params,
        )
        return list(cursor.fetchall())


def load_hot_fallback_rows(
    connection: Any,
    limit: int,
    *,
    as_of_ts: int | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    as_of_clause = (
        "AND stats.first_seen_ts IS NOT NULL AND stats.first_seen_ts <= %s"
        if as_of_ts is not None
        else ""
    )
    category_clause, category_params = _category_clause(category)
    params: tuple[Any, ...] = category_params
    if as_of_ts is not None:
        params += (as_of_ts,)
    params += (limit,)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                news.news_id,
                stats.hot_score,
                ROW_NUMBER() OVER (
                    ORDER BY stats.hot_score DESC, news.news_id ASC
                ) AS rank_position
            FROM mind_news AS news
            JOIN mind_news_stats AS stats USING (news_id)
            WHERE TRUE
            {category_clause}
            {as_of_clause}
            ORDER BY stats.hot_score DESC, news.news_id ASC
            LIMIT %s
            """,
            params,
        )
        return list(cursor.fetchall())


def load_exploration_rows(
    connection: Any,
    *,
    bucket_seed: str,
    limit: int,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Return a deterministic full-catalog slice, including zero-stat news."""
    category_clause, category_params = _category_clause(category)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT news.news_id, stats.hot_score
            FROM mind_news AS news
            JOIN mind_news_stats AS stats USING (news_id)
            WHERE TRUE
            {category_clause}
            ORDER BY md5(news.news_id || %s), news.news_id
            LIMIT %s
            """,
            (*category_params, bucket_seed, limit),
        )
        return list(cursor.fetchall())


def load_unseen_catalog_rows(
    connection: Any,
    *,
    session_id: str,
    bucket_seed: str,
    limit: int,
    as_of_ts: int | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    as_of_clause = (
        "AND stats.first_seen_ts IS NOT NULL AND stats.first_seen_ts <= %s"
        if as_of_ts is not None
        else ""
    )
    category_clause, category_params = _category_clause(category)
    params: tuple[Any, ...] = (session_id, *category_params)
    if as_of_ts is not None:
        params += (as_of_ts,)
    params += (bucket_seed, limit)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT news.news_id, stats.hot_score
            FROM mind_news AS news
            JOIN mind_news_stats AS stats USING (news_id)
            WHERE NOT EXISTS (
                SELECT 1
                FROM feed_request AS request
                CROSS JOIN LATERAL jsonb_array_elements_text(
                  request.returned_news_ids_json
                ) AS returned(news_id)
                WHERE request.session_id = %s
                  AND returned.news_id = news.news_id
            )
              {category_clause}
              {as_of_clause}
            ORDER BY md5(news.news_id || %s), news.news_id
            LIMIT %s
            """,
            params,
        )
        return list(cursor.fetchall())


def load_news_event_counts_as_of(
    connection: Any,
    news_ids: list[str],
    *,
    as_of_ts: int,
) -> dict[str, dict[str, int | float]]:
    if not news_ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                article_id,
                COUNT(*) FILTER (WHERE event_type = 'feed_impression') AS impression_count,
                COUNT(*) FILTER (WHERE event_type IN (
                    'recommendation_click', 'search_result_click', 'upvote'
                )) AS click_count
            FROM user_event
            WHERE derived_from_raw IS TRUE
              AND event_ts < %s
              AND source_space = 'mind'
              AND article_id = ANY(%s)
            GROUP BY article_id
            """,
            (as_of_ts, news_ids),
        )
        rows = cursor.fetchall()
    result: dict[str, dict[str, int | float]] = {}
    for row in rows:
        news_id = str(row["article_id"])
        click_count = int(row.get("click_count") or 0)
        impression_count = int(row.get("impression_count") or 0)
        result[news_id] = {
            "click_count": click_count,
            "impression_count": impression_count,
            "hot_score": float(click_count * 10 + impression_count),
        }
    return result


def load_news_ids_available_as_of(
    connection: Any,
    news_ids: list[str],
    *,
    as_of_ts: int | None,
    category: str | None = None,
) -> set[str]:
    if not news_ids:
        return set()
    category_clause, category_params = _category_clause(category)
    as_of_clause = (
        "AND stats.first_seen_ts IS NOT NULL AND stats.first_seen_ts <= %s"
        if as_of_ts is not None
        else ""
    )
    params: tuple[Any, ...] = (news_ids, *category_params)
    if as_of_ts is not None:
        params += (as_of_ts,)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT news.news_id
            FROM mind_news AS news
            JOIN mind_news_stats AS stats USING (news_id)
            WHERE news.news_id = ANY(%s)
              {category_clause}
              {as_of_clause}
            """,
            params,
        )
        return {str(row["news_id"]) for row in cursor.fetchall()}


def load_news_rows(
    connection: Any,
    news_ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not news_ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                news.news_id,
                news.title,
                news.abstract,
                news.url,
                news.category,
                news.subcategory,
                news.title_entities,
                news.abstract_entities,
                stats.first_seen_ts,
                stats.hot_score,
                stats.click_count,
                stats.impression_count
            FROM mind_news AS news
            JOIN mind_news_stats AS stats USING (news_id)
            WHERE news.news_id = ANY(%s)
            """,
            (news_ids,),
        )
        return {str(row["news_id"]): row for row in cursor.fetchall()}


def load_topics_by_news(
    connection: Any,
    news_ids: list[str],
) -> dict[str, list[TopicCard]]:
    if not news_ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                mapping.news_id,
                topic.topic_id,
                topic.display_name,
                mapping.source_rank
            FROM mind_news_topic AS mapping
            JOIN topic USING (topic_id)
            WHERE mapping.news_id = ANY(%s)
            ORDER BY mapping.news_id, mapping.source_rank, topic.topic_id
            """,
            (news_ids,),
        )
        rows = cursor.fetchall()

    topics_by_news: dict[str, list[TopicCard]] = {}
    for row in rows:
        news_id = str(row["news_id"])
        topic_id = int(row["topic_id"])
        topics_by_news.setdefault(news_id, []).append(
            TopicCard(
                topic_id=topic_id,
                display_name=row.get("display_name") or f"Topic {topic_id}",
            )
        )
    return topics_by_news


def load_news_topic_ids(connection: Any, news_id: str) -> list[int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT topic.topic_id
            FROM mind_news_topic AS mapping
            JOIN topic USING (topic_id)
            WHERE mapping.news_id = %s
            ORDER BY mapping.source_rank, topic.topic_id
            """,
            (news_id,),
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


def _hybrid_news_id(hit: HybridHit) -> str:
    news_id = getattr(hit, "news_id", None)
    if news_id is None:
        raise ValueError("Hybrid search hits must expose canonical news_id")
    return str(news_id)


def load_search_candidates(
    connection: Any,
    query_key: str,
    page_size: int,
    query_text: str | None = None,
    *,
    retrieval_mode: SearchRetrievalMode = "lexical_v1",
    hybrid_hits: tuple[HybridHit, ...] = (),
) -> dict[str, dict[str, Any]]:
    limit = max(page_size * 20, 50)
    if hybrid_hits:
        return {
            _hybrid_news_id(hit): {
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
                news.news_id,
                SUM(query_map.score) AS topic_match_score,
                MAX(stats.hot_score) AS hot_score
            FROM query_topic_map AS query_map
            JOIN mind_news_topic AS mapping ON mapping.topic_id = query_map.topic_id
            JOIN mind_news AS news USING (news_id)
            JOIN mind_news_stats AS stats USING (news_id)
            WHERE query_map.query_key = %s
            GROUP BY news.news_id
            ORDER BY topic_match_score DESC, news.news_id ASC
            LIMIT %s
            """,
            (query_key, limit),
        )
        rows = cursor.fetchall()

    candidates: dict[str, dict[str, Any]] = {
        str(row["news_id"]): {
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
    search_terms = list(
        dict.fromkeys(term for term in (normalized_text, *tokens) if len(term) >= 3)
    )
    if not search_terms:
        return candidates

    predicates: list[str] = []
    predicate_params: list[object] = []
    score_parts: list[str] = []
    score_params: list[object] = []
    for term in search_terms:
        contains = f"%{term}%"
        predicates.append("(LOWER(news.title) LIKE %s OR LOWER(news.abstract) LIKE %s)")
        predicate_params.extend((contains, contains))
        score_parts.append(
            "(CASE WHEN LOWER(news.title) LIKE %s THEN 2 ELSE 0 END "
            "+ CASE WHEN LOWER(news.abstract) LIKE %s THEN 1 ELSE 0 END)"
        )
        score_params.extend((contains, contains))
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                news.news_id,
                ({" + ".join(score_parts)}) AS lexical_score,
                stats.hot_score
            FROM mind_news AS news
            JOIN mind_news_stats AS stats USING (news_id)
            WHERE {" OR ".join(predicates)}
            ORDER BY lexical_score DESC, stats.hot_score DESC, news.news_id ASC
            LIMIT %s
            """,
            (*score_params, *predicate_params, limit),
        )
        lexical_rows = cursor.fetchall()
    for row in lexical_rows:
        news_id = str(row["news_id"])
        lexical_score = float(row.get("lexical_score") or 0.0) / (3.0 * len(search_terms))
        is_new = news_id not in candidates
        candidate = candidates.setdefault(
            news_id,
            {
                "source": "lexical_match",
                "topic_match_score": 0.0,
                "bm25_score": 0.0,
                "dense_score": 0.0,
                "hybrid_score": 0.0,
            },
        )
        if not is_new and "lexical_match" not in str(candidate["source"]):
            candidate["source"] = f"{candidate['source']}+lexical_match"
        candidate["topic_match_score"] = max(float(candidate["topic_match_score"]), lexical_score)
    return candidates
