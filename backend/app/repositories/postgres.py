from __future__ import annotations

import time
from pathlib import Path
from typing import Any, cast

from backend.app.config import Settings, compute_alpha
from backend.app.errors import SearchIndexNotReadyError, UnresolvedQueryError
from backend.app.events.outbox import enqueue_outbox_message
from backend.app.events.schema import UserEventMessage, UserEventType
from backend.app.observability import (
    PROFILE_V2_LATE_EVENTS,
    PROFILE_V2_PROJECTION_DURATION,
    PROFILE_V2_PROJECTION_UPDATES,
    SEARCH_RESOLUTIONS,
    SEARCH_RETRIEVAL_DURATION,
)
from backend.app.profiles.signals import topic_strengths_for_event
from backend.app.repositories._utils import (
    add_feed_candidate,
    is_numeric_query_key,
    new_request_id,
    normalize_query_key,
    parse_topic_weights,
    selected_reason,
    topic_delta_models,
)
from backend.app.repositories.als_recall import get_als_recall
from backend.app.repositories.base import RuntimeRepository
from backend.app.repositories.connection import PostgresConnectionPool, parse_database_url
from backend.app.repositories.content_dao import (
    load_answer_event_counts_as_of,
    load_answer_ids_created_as_of,
    load_answer_ids_for_topics,
    load_answer_rows,
    load_answer_topic_ids,
    load_hot_fallback_rows,
    load_query_topics,
    load_search_candidates,
    load_search_matched_topics,
    load_topics_by_answer,
)
from backend.app.repositories.event_dao import (
    append_recent_query,
    apply_click_profile_update,
    claim_event_id,
    confirm_recent_query,
    record_click_event,
    record_log_only_event,
    record_search_query,
)
from backend.app.repositories.mmr import MMRCandidate, mmr_config, rerank_mmr
from backend.app.repositories.profile_dao import (
    fetch_profile_row,
    load_default_seed_topic_weights,
    load_recent_query_topic_scores,
    profile_from_row,
)
from backend.app.repositories.profile_v2_dao import (
    apply_profile_v2_event_with_outcome,
    profile_event_is_before_reset,
    profile_signal_config,
)
from backend.app.repositories.query_resolver import resolve_search_query
from backend.app.repositories.ranker import (
    build_feature_dict,
    loaded_model_metadata,
    score_candidates,
)
from backend.app.repositories.search_signal import search_signal_config
from backend.app.repositories.sponsored import (
    blend_fixed_slots,
    sponsored_slot_is_reachable,
)
from backend.app.repositories.sponsored_dao import (
    SponsoredDelivery,
    claim_feed_request,
    confirm_sponsored_impression,
    load_sponsored_attribution,
    load_sponsored_candidates,
    load_sponsored_deliveries_for_request,
    record_sponsored_click,
    reserve_sponsored_delivery,
)
from backend.app.schemas.article import ArticleCardResponse
from backend.app.schemas.common import TopicCard
from backend.app.schemas.event import (
    ArticleTopic,
    EventAckResponse,
    OverlapTopic,
    RecommendationClickDebug,
    RecommendationClickRequest,
    SearchQueryTopic,
    SearchResultClickDebug,
    SearchResultClickRequest,
)
from backend.app.schemas.event_track import EventTrackRequest, EventTrackResponse
from backend.app.schemas.feed import (
    ArtifactDebug,
    ColdStartMix,
    FeedDebugPayload,
    FeedExperimentArm,
    FeedItem,
    FeedItemScores,
    FeedProfileSummary,
    FeedResponse,
    RecallCandidateDebug,
    SponsoredCandidateDebug,
    SponsoredFeedMetadata,
)
from backend.app.schemas.persona import PersonaCard, PersonaListResponse
from backend.app.schemas.profile import DebugProfileResponse
from backend.app.schemas.search import (
    SearchArtifactDebug,
    SearchDebugPayload,
    SearchItem,
    SearchItemScores,
    SearchRequest,
    SearchResponse,
    SearchResultSource,
)
from backend.app.schemas.suggestion import SuggestionItem, SuggestionListResponse
from backend.app.search_retrieval import (
    SearchArtifactError,
    load_hybrid_search_index,
)


class PostgresRuntimeRepository(RuntimeRepository):
    backend_name = "postgresql"

    def __init__(
        self,
        settings: Settings,
    ) -> None:
        if not settings.database_url.strip():
            raise ValueError("NEWSREC_DATABASE_URL is required for PostgresRuntimeRepository")
        self._settings = settings
        self._connection_config = parse_database_url(settings.database_url)
        self._connection_pool = PostgresConnectionPool(
            self._connection_config,
            connect_timeout=settings.postgres_connect_timeout_seconds,
            min_size=settings.postgres_pool_min_size,
            max_connections=settings.postgres_pool_max_connections,
        )

    # ── 公共 API ────────────────────────────────────────────────

    def close(self) -> None:
        self._connection_pool.close()

    def get_feed(
        self,
        user_id: int,
        page_size: int,
        debug: bool,
        experiment_arm: FeedExperimentArm = "default",
        include_sponsored: bool = True,
        request_id: str | None = None,
        as_of_ts: int | None = None,
    ) -> FeedResponse:
        request_id = request_id or new_request_id(self._settings.request_id_prefix, "feed")
        sponsored_enabled = (
            self._settings.sponsored_enabled and include_sponsored and experiment_arm == "default"
        )
        connection = self._connection_pool.connect()
        transaction_started = True
        try:
            connection.begin()
            new_feed_request = claim_feed_request(
                connection,
                request_id=request_id,
                user_id=user_id,
                page_size=page_size,
                debug=debug,
                include_sponsored=include_sponsored,
                experiment_arm=experiment_arm,
                as_of_ts=as_of_ts,
            )
            profile_row = fetch_profile_row(connection, user_id)
            profile = profile_from_row(profile_row)
            topic_weight_map = {item.topic_id: item.weight for item in profile.topic_weights}
            signal_config = search_signal_config(experiment_arm)
            use_search = signal_config is not None
            use_lgb = experiment_arm in {
                "default",
                "lgb_plus_als",
                "lgb_plus_als_plus_search",
                "lgb_plus_als_plus_search_mmr",
                "lgb_plus_als_plus_search_decay_30m",
                "lgb_plus_als_plus_search_decay_4h",
                "lgb_plus_als_plus_search_gated_30m_4h",
                "lgb_plus_als_plus_search_gated_2h_12h",
            }
            require_lgb = use_lgb and experiment_arm != "default"
            use_als = (
                self._settings.als_recall_enabled
                if experiment_arm == "default"
                else experiment_arm != "manual"
            )
            query_topic_scores = (
                load_recent_query_topic_scores(
                    connection,
                    profile.recent_queries,
                    now_ts=as_of_ts if as_of_ts is not None else int(time.time()),
                    config=signal_config,
                )
                if use_search and signal_config is not None
                else {}
            )
            query_recall_topic_scores = (
                load_recent_query_topic_scores(
                    connection,
                    profile.recent_queries,
                    now_ts=as_of_ts if as_of_ts is not None else int(time.time()),
                    config=signal_config,
                    confirmed_only=signal_config.mode == "gated",
                )
                if use_search and signal_config is not None
                else {}
            )
            default_seed_key = (
                profile.cold_start_seed_key or self._settings.cold_start_default_seed_key
            )
            default_topic_weight_map = load_default_seed_topic_weights(
                connection,
                seed_key=default_seed_key,
            )
            alpha = compute_alpha(profile.behavior_score, self._settings)
            cold_start_mix = ColdStartMix(
                alpha=round(alpha, 6),
                behavior_score=round(profile.behavior_score, 6),
                default_seed_key=default_seed_key,
                default_topic_count=len(default_topic_weight_map),
            )

            candidates = self._load_feed_candidates(
                connection=connection,
                topic_weight_map=topic_weight_map,
                query_topic_scores=query_recall_topic_scores,
                page_size=page_size,
                user_id=user_id,
                use_als=use_als,
                as_of_ts=as_of_ts,
            )
            if not candidates:
                if transaction_started:
                    connection.commit()
                return FeedResponse(
                    user_id=user_id,
                    request_id=request_id,
                    items=[],
                    debug=FeedDebugPayload(
                        experiment_arm=experiment_arm,
                        profile_summary=FeedProfileSummary(
                            behavior_score=profile.behavior_score,
                            top_topics=profile.topic_weights,
                        ),
                        recall_candidates=[],
                        sponsored_candidates=[],
                        artifacts=self._artifact_debug(),
                        fallback_used=False,
                        cold_start_mix=cold_start_mix,
                    )
                    if debug
                    else None,
                )

            answer_ids = list(candidates)
            answer_rows = load_answer_rows(connection, answer_ids)
            if as_of_ts is not None:
                event_counts = load_answer_event_counts_as_of(
                    connection,
                    answer_ids,
                    as_of_ts=as_of_ts,
                )
                answer_rows = {
                    answer_id: {
                        **row,
                        **event_counts.get(
                            answer_id,
                            {
                                "hot_score": 0.0,
                                "click_count": 0,
                                "impression_count": 0,
                            },
                        ),
                    }
                    for answer_id, row in answer_rows.items()
                }
            topics_by_answer = load_topics_by_answer(connection, answer_ids)
            max_hot_score = max(
                [float(row.get("hot_score") or 0) for row in answer_rows.values()] + [1.0]
            )

            now_ts = int(time.time())
            feature_now_ts = as_of_ts if as_of_ts is not None else now_ts
            user_topic_count = len(topic_weight_map)

            # ── 为所有候选项构建特征字典 ─────────────────────────────
            feature_dicts: list[dict[str, float]] = []
            candidate_keys: list[tuple[int, Any, Any, set[int], float, list[str], bool]] = []
            for answer_id, candidate in candidates.items():
                row = answer_rows.get(answer_id)
                if row is None:
                    continue
                topics = topics_by_answer.get(answer_id, [])
                topic_ids = {topic.topic_id for topic in topics}
                base_score = (
                    round(
                        float(row.get("hot_score") or candidate["raw_base_score"] or 0)
                        / (float(row.get("hot_score") or candidate["raw_base_score"] or 0) + 100.0),
                        6,
                    )
                    if float(row.get("hot_score") or candidate["raw_base_score"] or 0) > 0
                    else 0.0
                )
                feat = build_feature_dict(
                    article_row=row,
                    topic_ids=topic_ids,
                    topic_weight_map=topic_weight_map,
                    default_topic_weight_map=default_topic_weight_map,
                    query_topic_scores=query_topic_scores,
                    alpha=alpha,
                    max_hot_score=max_hot_score,
                    now_ts=float(feature_now_ts),
                    user_behavior_score=profile.behavior_score,
                    user_topic_count=user_topic_count,
                )
                feature_dicts.append(feat)
                candidate_keys.append(
                    (
                        answer_id,
                        row,
                        topics,
                        topic_ids,
                        base_score,
                        sorted(candidate["sources"]),
                        bool(candidate["is_fallback"]),
                    )
                )

            # ── 批量模型推理 ─────────────────────────────────────────
            model_scores = score_candidates(feature_dicts) if feature_dicts and use_lgb else None
            if require_lgb and model_scores is None:
                raise RuntimeError(
                    "requested LightGBM experiment arm but a compatible model is unavailable"
                )

            # ── 构建 FeedItem 列表 ───────────────────────────────────
            scored_items: list[tuple[FeedItem, RecallCandidateDebug]] = []
            for idx, (
                answer_id,
                row,
                topics,
                topic_ids,
                base_score,
                sources,
                is_fallback,
            ) in enumerate(candidate_keys):
                row = cast(dict[str, Any], row)
                personalized_topic_score = round(
                    sum(topic_weight_map.get(tid, 0.0) for tid in topic_ids), 6
                )
                default_topic_score = round(
                    sum(default_topic_weight_map.get(tid, 0.0) for tid in topic_ids), 6
                )
                topic_match_score = round(
                    alpha * personalized_topic_score + (1.0 - alpha) * default_topic_score, 6
                )
                query_recall_boost = round(
                    sum(query_topic_scores.get(tid, 0.0) for tid in topic_ids), 6
                )
                if model_scores is not None and idx < len(model_scores):
                    final_score = round(float(model_scores[idx]), 6)
                else:
                    # 回退方案：模型尚未训练时使用手工公式
                    final_score = round(base_score + topic_match_score + query_recall_boost, 6)

                item = FeedItem(
                    article_id=answer_id,
                    headline=row.get("headline") or f"Article {answer_id}",
                    abstract=row.get("abstract") or "",
                    source_domain=row.get("source_domain") or "unknown-source",
                    categories=topics,
                    selected_reason=selected_reason(
                        is_fallback=is_fallback,
                        sources=set(sources),
                    ),
                    scores=FeedItemScores(
                        base_recall_score=base_score,
                        personalized_topic_score=personalized_topic_score,
                        default_topic_score=default_topic_score,
                        topic_match_score=topic_match_score,
                        query_recall_boost=query_recall_boost,
                        final_score=final_score,
                    ),
                    recall_sources=sources,
                    is_fallback=is_fallback,
                )
                scored_items.append(
                    (
                        item,
                        RecallCandidateDebug(
                            article_id=answer_id,
                            source="+".join(sources),
                            base_recall_score=base_score,
                        ),
                    )
                )

            scored_items.sort(key=lambda pair: (-pair[0].scores.final_score, pair[0].article_id))
            sponsored_deliveries: list[SponsoredDelivery] = []
            if sponsored_enabled:
                if not new_feed_request:
                    sponsored_deliveries = load_sponsored_deliveries_for_request(
                        connection,
                        request_id=request_id,
                        user_id=user_id,
                    )
                else:
                    target_topic_ids = list(
                        dict.fromkeys(
                            [
                                *topic_weight_map,
                                *query_topic_scores,
                                *default_topic_weight_map,
                            ]
                        )
                    )
                    sponsored_candidates = load_sponsored_candidates(
                        connection,
                        user_id=user_id,
                        target_topic_ids=target_topic_ids,
                        now_ts=now_ts,
                    )
                    slots = sorted(
                        {slot for slot in self._settings.sponsored_slots if 1 <= slot <= page_size}
                    )
                    used_answers: set[int] = set()
                    used_campaigns: set[int] = set()
                    candidate_index = 0
                    organic_answer_ids = {pair[0].article_id for pair in scored_items}
                    for slot in slots:
                        while candidate_index < len(sponsored_candidates):
                            sponsored_candidate = sponsored_candidates[candidate_index]
                            candidate_index += 1
                            if (
                                sponsored_candidate.answer_id in used_answers
                                or sponsored_candidate.campaign_id in used_campaigns
                            ):
                                continue
                            if not sponsored_slot_is_reachable(
                                organic_answer_ids=organic_answer_ids,
                                already_sponsored_answer_ids=used_answers,
                                candidate_answer_id=sponsored_candidate.answer_id,
                                slot_position=slot,
                                sponsored_count=len(sponsored_deliveries),
                            ):
                                continue
                            delivery = reserve_sponsored_delivery(
                                connection,
                                candidate=sponsored_candidate,
                                user_id=user_id,
                                request_id=request_id,
                                slot_position=slot,
                                now_ts=now_ts,
                                pacing_headroom_seconds=(
                                    self._settings.sponsored_pacing_headroom_seconds
                                ),
                            )
                            if delivery is None:
                                continue
                            sponsored_deliveries.append(delivery)
                            used_answers.add(delivery.answer_id)
                            used_campaigns.add(delivery.campaign_id)
                            break

            sponsored_items, sponsored_debug = self._build_sponsored_feed_items(
                connection,
                sponsored_deliveries,
            )
            sponsored_answer_ids = {item.article_id for item in sponsored_items}
            organic_pairs = [
                pair for pair in scored_items if pair[0].article_id not in sponsored_answer_ids
            ]
            organic_limit = max(0, page_size - len(sponsored_items))
            active_mmr_config = mmr_config(experiment_arm)
            if active_mmr_config is None:
                selected_pairs = organic_pairs[:organic_limit]
            else:
                als = get_als_recall()
                mmr_candidates: list[MMRCandidate[tuple[FeedItem, RecallCandidateDebug]]] = [
                    MMRCandidate(
                        article_id=pair[0].article_id,
                        relevance=pair[0].scores.final_score,
                        topic_ids=frozenset(topic.topic_id for topic in pair[0].categories),
                        value=pair,
                    )
                    for pair in organic_pairs
                ]
                selected_pairs = [
                    selection.value
                    for selection in rerank_mmr(
                        mmr_candidates,
                        limit=organic_limit,
                        similarity_penalty=active_mmr_config.similarity_penalty,
                        als_similarity=als.item_cosine_similarity,
                    )
                ]
            organic_items = [pair[0] for pair in selected_pairs]
            selected_items = blend_fixed_slots(
                organic_items,
                {
                    delivery.slot_position: item
                    for delivery, item in zip(
                        sponsored_deliveries,
                        sponsored_items,
                        strict=True,
                    )
                },
                page_size=page_size,
            )
            fallback_used = any(item.is_fallback for item in organic_items)
            if transaction_started:
                connection.commit()

            return FeedResponse(
                user_id=user_id,
                request_id=request_id,
                items=selected_items,
                debug=FeedDebugPayload(
                    experiment_arm=experiment_arm,
                    profile_summary=FeedProfileSummary(
                        behavior_score=profile.behavior_score,
                        top_topics=profile.topic_weights,
                    ),
                    recall_candidates=[pair[1] for pair in scored_items[:50]],
                    sponsored_candidates=sponsored_debug,
                    artifacts=self._artifact_debug(),
                    fallback_used=fallback_used,
                    cold_start_mix=cold_start_mix,
                )
                if debug
                else None,
            )
        except Exception:
            if transaction_started:
                connection.rollback()
            raise
        finally:
            connection.close()

    def search(self, payload: SearchRequest) -> SearchResponse:
        event_ts = (
            payload.replay_event_ts if payload.replay_event_ts is not None else int(time.time())
        )
        connection = self._connection_pool.connect()
        try:
            resolution_started = time.perf_counter()
            try:
                hybrid_index = None
                needs_hybrid_index = self._settings.search_retrieval_mode == "hybrid_v1" and not (
                    payload.query_key and is_numeric_query_key(payload.query_key)
                )
                if needs_hybrid_index:
                    try:
                        hybrid_index = load_hybrid_search_index(
                            Path(self._settings.search_index_dir),
                            expected_source_fingerprint=(self._settings.search_source_fingerprint),
                        )
                    except SearchArtifactError as exc:
                        raise SearchIndexNotReadyError(str(exc)) from exc
                resolution = resolve_search_query(
                    connection,
                    payload.query_key,
                    payload.query_text,
                    retrieval_mode=self._settings.search_retrieval_mode,
                    hybrid_index=hybrid_index,
                    hybrid_limit=max(payload.page_size * 20, 50),
                )
            except UnresolvedQueryError:
                SEARCH_RESOLUTIONS.labels(
                    mode=self._settings.search_retrieval_mode,
                    source="unresolved",
                    outcome="rejected",
                ).inc()
                raise
            except SearchIndexNotReadyError:
                SEARCH_RESOLUTIONS.labels(
                    mode=self._settings.search_retrieval_mode,
                    source="artifact",
                    outcome="error",
                ).inc()
                raise
            else:
                SEARCH_RESOLUTIONS.labels(
                    mode=self._settings.search_retrieval_mode,
                    source=resolution.source,
                    outcome="accepted",
                ).inc()
            finally:
                SEARCH_RETRIEVAL_DURATION.labels(mode=self._settings.search_retrieval_mode).observe(
                    time.perf_counter() - resolution_started
                )
            query_key = resolution.query_key
            event = self._event_message(
                event_type="search_query",
                user_id=payload.user_id,
                event_id=payload.event_id,
                query_key=query_key,
                query_text=payload.query_text,
                request_id=payload.event_id,
                surface="search",
                event_ts=event_ts,
            )
            connection.begin()
            claimed = True
            if self._settings.event_mode != "kafka_async":
                claimed = claim_event_id(connection, event)
                if claimed:
                    profile_row = fetch_profile_row(
                        connection,
                        payload.user_id,
                        for_update=True,
                    )
                    record_search_query(
                        connection=connection,
                        user_id=payload.user_id,
                        query_key=query_key,
                        event_ts=event_ts,
                        external_event_id=event.event_id,
                    )
                    append_recent_query(
                        connection=connection,
                        profile_row=profile_row,
                        query_key=query_key,
                        event_ts=event_ts,
                        behavior_delta=self._settings.search_query_behavior_delta,
                    )

            matched_topics = load_search_matched_topics(connection, query_key)
            search_candidates = load_search_candidates(
                connection=connection,
                query_key=query_key,
                page_size=payload.page_size,
                query_text=payload.query_text,
                retrieval_mode=self._settings.search_retrieval_mode,
                hybrid_hits=resolution.hybrid_hits,
            )
            answer_ids = [answer_id for answer_id in search_candidates]
            answer_rows = load_answer_rows(connection, answer_ids)
            topics_by_answer = load_topics_by_answer(connection, answer_ids)

            scored_items: list[tuple[SearchItem, SearchResultSource]] = []
            for answer_id, candidate in search_candidates.items():
                row = answer_rows.get(answer_id)
                if row is None:
                    continue

                topic_match_score = round(float(candidate["topic_match_score"]), 6)
                bm25_score = round(float(candidate.get("bm25_score") or 0.0), 6)
                dense_score = round(float(candidate.get("dense_score") or 0.0), 6)
                hybrid_score = round(float(candidate.get("hybrid_score") or 0.0), 9)
                final_score = hybrid_score if hybrid_score > 0 else topic_match_score
                item = SearchItem(
                    article_id=answer_id,
                    headline=row.get("headline") or f"Article {answer_id}",
                    abstract=row.get("abstract") or "",
                    source_domain=row.get("source_domain") or "unknown-source",
                    categories=topics_by_answer.get(answer_id, []),
                    scores=SearchItemScores(
                        topic_match_score=topic_match_score,
                        bm25_score=bm25_score,
                        dense_score=dense_score,
                        hybrid_score=hybrid_score,
                        final_score=final_score,
                    ),
                )
                scored_items.append(
                    (
                        item,
                        SearchResultSource(article_id=answer_id, source=candidate["source"]),
                    )
                )

            scored_items.sort(key=lambda pair: (-pair[0].scores.final_score, pair[0].article_id))
            selected = scored_items[: payload.page_size]
            search_artifact = None
            if hybrid_index is not None:
                metadata = hybrid_index.metadata()
                search_artifact = SearchArtifactDebug(
                    model_id=str(metadata["model_id"]),
                    model_revision=str(metadata["model_revision"]),
                    source_fingerprint=str(metadata["source_fingerprint"]),
                )
            response = SearchResponse(
                user_id=payload.user_id,
                request_id=event.event_id,
                query_key=query_key,
                items=[pair[0] for pair in selected],
                debug=SearchDebugPayload(
                    matched_topics=matched_topics,
                    result_sources=[pair[1] for pair in selected],
                    retrieval_mode=self._settings.search_retrieval_mode,
                    resolution_source=resolution.source,
                    resolution_confidence=round(resolution.confidence, 6),
                    artifact=search_artifact,
                )
                if payload.debug
                else None,
            )
            self._enqueue_raw_event(connection, event)
            connection.commit()
            return response
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record_recommendation_click(self, payload: RecommendationClickRequest) -> EventAckResponse:
        event_ts = (
            payload.replay_event_ts if payload.replay_event_ts is not None else int(time.time())
        )
        sponsored_attribution = self._load_sponsored_event_attribution(
            delivery_id=payload.sponsored_delivery_id,
            user_id=payload.user_id,
            article_id=payload.article_id,
        )
        event = self._event_message(
            event_type="recommendation_click",
            user_id=payload.user_id,
            event_id=payload.event_id,
            article_id=payload.article_id,
            request_id=payload.request_id,
            sponsored_delivery_id=payload.sponsored_delivery_id,
            campaign_id=(
                int(sponsored_attribution["campaign_id"])
                if sponsored_attribution is not None
                else None
            ),
            creative_id=(
                int(sponsored_attribution["creative_id"])
                if sponsored_attribution is not None
                else None
            ),
            surface="feed",
            event_ts=event_ts,
        )
        if self._settings.event_mode == "kafka_async":
            self._persist_async_event(event)
            return EventAckResponse(ok=True, event_type="recommendation_click", debug=None)

        connection = self._connection_pool.connect()
        try:
            connection.begin()
            if not claim_event_id(connection, event):
                connection.commit()
                return EventAckResponse(
                    ok=True,
                    event_type="recommendation_click",
                    debug=None,
                )
            project_profile = not profile_event_is_before_reset(
                connection,
                user_id=payload.user_id,
                event_ts=event_ts,
            )
            if not project_profile and self._settings.profile_v2_enabled:
                PROFILE_V2_LATE_EVENTS.labels(reason="pre_reset").inc()
            if payload.sponsored_delivery_id:
                sponsored_attribution = load_sponsored_attribution(
                    connection,
                    delivery_id=payload.sponsored_delivery_id,
                    user_id=payload.user_id,
                    article_id=payload.article_id,
                    for_update=True,
                )
            answer_topic_ids = load_answer_topic_ids(connection, payload.article_id)
            topic_deltas = {
                topic_id: self._settings.recommendation_click_topic_delta
                for topic_id in answer_topic_ids
            }
            record_click_event(
                connection=connection,
                user_id=payload.user_id,
                event_type="recommendation_click",
                article_id=payload.article_id,
                query_key=None,
                request_id=payload.request_id,
                surface="feed",
                event_ts=event_ts,
                topic_ids=answer_topic_ids,
                external_event_id=event.event_id,
                sponsored_delivery_id=event.sponsored_delivery_id,
                campaign_id=event.campaign_id,
                creative_id=event.creative_id,
            )
            if sponsored_attribution is not None:
                record_sponsored_click(
                    connection,
                    attribution=sponsored_attribution,
                    event_ts=event_ts,
                )
            update: dict[str, Any] | None = None
            if project_profile:
                profile_row = fetch_profile_row(connection, payload.user_id, for_update=True)
                update = apply_click_profile_update(
                    connection=connection,
                    profile_row=profile_row,
                    article_id=payload.article_id,
                    event_ts=event_ts,
                    topic_deltas=topic_deltas,
                    behavior_delta=self._settings.recommendation_click_behavior_delta,
                    decay_factor=self._settings.profile_topic_decay,
                )
                self._project_profile_v2(
                    connection,
                    event,
                    topic_strengths_for_event(
                        event.event_type,
                        article_topic_ids=answer_topic_ids,
                    ),
                )
            response = EventAckResponse(
                ok=True,
                event_type="recommendation_click",
                debug=(
                    RecommendationClickDebug(
                        updated_topics=topic_delta_models(topic_deltas),
                        recent_clicked_articles_tail=update["recent_clicked_answers"],
                        behavior_score=update["behavior_score"],
                    )
                    if payload.debug and update is not None
                    else None
                ),
            )
            self._enqueue_raw_event(connection, event)
            connection.commit()
            return response
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record_search_result_click(self, payload: SearchResultClickRequest) -> EventAckResponse:
        query_key = normalize_query_key(payload.query_key)
        event_ts = (
            payload.replay_event_ts if payload.replay_event_ts is not None else int(time.time())
        )
        sponsored_attribution = self._load_sponsored_event_attribution(
            delivery_id=payload.sponsored_delivery_id,
            user_id=payload.user_id,
            article_id=payload.article_id,
        )
        event = self._event_message(
            event_type="search_result_click",
            user_id=payload.user_id,
            event_id=payload.event_id,
            article_id=payload.article_id,
            query_key=query_key,
            request_id=payload.request_id,
            sponsored_delivery_id=payload.sponsored_delivery_id,
            campaign_id=(
                int(sponsored_attribution["campaign_id"])
                if sponsored_attribution is not None
                else None
            ),
            creative_id=(
                int(sponsored_attribution["creative_id"])
                if sponsored_attribution is not None
                else None
            ),
            surface="search",
            event_ts=event_ts,
        )
        if self._settings.event_mode == "kafka_async":
            self._persist_async_event(event)
            return EventAckResponse(ok=True, event_type="search_result_click", debug=None)

        connection = self._connection_pool.connect()
        try:
            connection.begin()
            if not claim_event_id(connection, event):
                connection.commit()
                return EventAckResponse(
                    ok=True,
                    event_type="search_result_click",
                    debug=None,
                )
            project_profile = not profile_event_is_before_reset(
                connection,
                user_id=payload.user_id,
                event_ts=event_ts,
            )
            if not project_profile and self._settings.profile_v2_enabled:
                PROFILE_V2_LATE_EVENTS.labels(reason="pre_reset").inc()
            if payload.sponsored_delivery_id:
                sponsored_attribution = load_sponsored_attribution(
                    connection,
                    delivery_id=payload.sponsored_delivery_id,
                    user_id=payload.user_id,
                    article_id=payload.article_id,
                    for_update=True,
                )
            query_topics: list[SearchQueryTopic] = load_query_topics(connection, query_key)
            answer_topic_ids = load_answer_topic_ids(connection, payload.article_id)
            query_topic_ids = {topic.topic_id for topic in query_topics}
            answer_topic_set = set(answer_topic_ids)
            overlap_topic_ids = query_topic_ids & answer_topic_set
            topic_deltas: dict[int, float] = {}
            for topic_id in query_topic_ids | answer_topic_set:
                topic_deltas[topic_id] = self._settings.search_result_click_topic_delta
            for topic_id in overlap_topic_ids:
                topic_deltas[topic_id] = self._settings.search_result_overlap_topic_delta

            topic_ids = sorted(query_topic_ids | answer_topic_set)
            record_click_event(
                connection=connection,
                user_id=payload.user_id,
                event_type="search_result_click",
                article_id=payload.article_id,
                query_key=query_key,
                request_id=payload.request_id,
                surface="search",
                event_ts=event_ts,
                topic_ids=topic_ids,
                external_event_id=event.event_id,
                sponsored_delivery_id=event.sponsored_delivery_id,
                campaign_id=event.campaign_id,
                creative_id=event.creative_id,
            )
            profile_row = (
                fetch_profile_row(connection, payload.user_id, for_update=True)
                if project_profile
                else None
            )
            if profile_row is not None:
                confirm_recent_query(
                    connection,
                    profile_row,
                    query_key=query_key,
                    event_ts=event_ts,
                )
            if sponsored_attribution is not None:
                record_sponsored_click(
                    connection,
                    attribution=sponsored_attribution,
                    event_ts=event_ts,
                )
            update: dict[str, Any] | None = None
            if profile_row is not None:
                update = apply_click_profile_update(
                    connection=connection,
                    profile_row=profile_row,
                    article_id=payload.article_id,
                    event_ts=event_ts,
                    topic_deltas=topic_deltas,
                    behavior_delta=self._settings.search_result_click_behavior_delta,
                    decay_factor=self._settings.profile_topic_decay,
                )
                self._project_profile_v2(
                    connection,
                    event,
                    topic_strengths_for_event(
                        event.event_type,
                        article_topic_ids=answer_topic_set,
                        query_topic_ids=query_topic_ids,
                    ),
                )
            response = EventAckResponse(
                ok=True,
                event_type="search_result_click",
                debug=(
                    SearchResultClickDebug(
                        query_topics=query_topics,
                        article_topics=[
                            ArticleTopic(topic_id=topic_id) for topic_id in answer_topic_ids
                        ],
                        overlap_topics=[
                            OverlapTopic(topic_id=topic_id, boost_type="strong_confirm")
                            for topic_id in sorted(overlap_topic_ids)
                        ],
                        behavior_score=update["behavior_score"],
                    )
                    if payload.debug and update is not None
                    else None
                ),
            )
            self._enqueue_raw_event(connection, event)
            connection.commit()
            return response
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_debug_profile(self, user_id: int) -> DebugProfileResponse:
        connection = self._connection_pool.connect()
        try:
            return profile_from_row(fetch_profile_row(connection, user_id))
        finally:
            connection.close()

    def list_personas(self, limit: int) -> PersonaListResponse:
        connection = self._connection_pool.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                      au.user_id,
                      au.display_name,
                      up.behavior_score,
                      up.topic_weights_json
                    FROM app_user au
                    JOIN user_profile up ON up.user_id = au.user_id
                    WHERE au.is_demo_user IS TRUE
                    ORDER BY up.behavior_score DESC, au.user_id ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        items: list[PersonaCard] = []
        for row in rows:
            user_id = int(row["user_id"])
            top_topics = parse_topic_weights(row.get("topic_weights_json"))[:10]
            items.append(
                PersonaCard(
                    user_id=user_id,
                    display_name=row.get("display_name") or f"User {user_id}",
                    behavior_score=float(row.get("behavior_score") or 0.0),
                    top_topics=top_topics,
                )
            )
        return PersonaListResponse(items=items)

    def list_search_suggestions(self, limit: int) -> SuggestionListResponse:
        connection = self._connection_pool.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                      query_key,
                      ANY_VALUE(display_query) AS display_query,
                      COUNT(*) AS topic_count
                    FROM query_topic_map
                    GROUP BY query_key
                    ORDER BY topic_count DESC, query_key ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        items = [
            SuggestionItem(
                query_key=str(row["query_key"]),
                label=str(row.get("display_query") or f"Query {row['query_key']}"),
                topic_count=int(row.get("topic_count") or 0),
            )
            for row in rows
        ]
        return SuggestionListResponse(items=items)

    def get_article_card(self, article_id: int) -> ArticleCardResponse:
        connection = self._connection_pool.connect()
        try:
            answer_rows = load_answer_rows(connection, [article_id])
            row = answer_rows.get(article_id)
            if row is None:
                raise LookupError(f"article not found: {article_id}")
            topics_by_answer = load_topics_by_answer(connection, [article_id])
        finally:
            connection.close()

        categories: list[TopicCard] = topics_by_answer.get(article_id, [])
        return ArticleCardResponse(
            article_id=article_id,
            headline=row.get("headline") or f"Article {article_id}",
            abstract=row.get("abstract") or "",
            source_domain=row.get("source_domain") or "unknown-source",
            categories=categories,
        )

    def record_tracked_event(self, payload: EventTrackRequest) -> EventTrackResponse:
        # 将已有完整画像更新逻辑的事件类型交给对应处理器。
        if payload.event_type == "recommendation_click":
            if payload.article_id is None:
                raise ValueError("recommendation_click requires article_id")
            ack = self.record_recommendation_click(
                RecommendationClickRequest(
                    event_id=payload.event_id,
                    user_id=payload.user_id,
                    article_id=payload.article_id,
                    request_id=payload.request_id,
                    sponsored_delivery_id=payload.sponsored_delivery_id,
                    debug=payload.debug,
                    replay_event_ts=payload.replay_event_ts,
                )
            )
            behavior_score = (
                ack.debug.behavior_score
                if isinstance(ack.debug, RecommendationClickDebug)
                else None
            )
            profile_updated = self._settings.event_mode != "kafka_async"
            return EventTrackResponse(
                ok=ack.ok,
                event_type=payload.event_type,
                profile_updated=profile_updated,
                behavior_score=behavior_score,
            )

        if payload.event_type == "search_result_click":
            if payload.article_id is None or not payload.query_key:
                raise ValueError("search_result_click requires article_id and query_key")
            ack = self.record_search_result_click(
                SearchResultClickRequest(
                    event_id=payload.event_id,
                    user_id=payload.user_id,
                    article_id=payload.article_id,
                    query_key=payload.query_key,
                    request_id=payload.request_id,
                    sponsored_delivery_id=payload.sponsored_delivery_id,
                    debug=payload.debug,
                    replay_event_ts=payload.replay_event_ts,
                )
            )
            behavior_score = (
                ack.debug.behavior_score if isinstance(ack.debug, SearchResultClickDebug) else None
            )
            profile_updated = self._settings.event_mode != "kafka_async"
            return EventTrackResponse(
                ok=ack.ok,
                event_type=payload.event_type,
                profile_updated=profile_updated,
                behavior_score=behavior_score,
            )

        if payload.event_type == "upvote":
            if payload.article_id is None:
                raise ValueError("upvote requires article_id")
            # 应用与推荐点击相同的正向画像更新，
            # 但将 user_event 记录标记为 event_type='upvote'，便于分析时区分。
            event_ts = (
                payload.replay_event_ts if payload.replay_event_ts is not None else int(time.time())
            )
            sponsored_attribution = self._load_sponsored_event_attribution(
                delivery_id=payload.sponsored_delivery_id,
                user_id=payload.user_id,
                article_id=payload.article_id,
            )
            event = self._event_message(
                event_type="upvote",
                user_id=payload.user_id,
                event_id=payload.event_id,
                article_id=payload.article_id,
                query_key=payload.query_key,
                request_id=payload.request_id,
                sponsored_delivery_id=payload.sponsored_delivery_id,
                campaign_id=(
                    int(sponsored_attribution["campaign_id"])
                    if sponsored_attribution is not None
                    else None
                ),
                creative_id=(
                    int(sponsored_attribution["creative_id"])
                    if sponsored_attribution is not None
                    else None
                ),
                surface=payload.surface or "home_feed",
                event_ts=event_ts,
                dwell_ms=payload.dwell_ms,
            )
            if self._settings.event_mode == "kafka_async":
                self._persist_async_event(event)
                return EventTrackResponse(
                    ok=True,
                    event_type=payload.event_type,
                    profile_updated=False,
                    behavior_score=None,
                )

            connection = self._connection_pool.connect()
            try:
                connection.begin()
                if not claim_event_id(connection, event):
                    connection.commit()
                    return EventTrackResponse(
                        ok=True,
                        event_type=payload.event_type,
                        profile_updated=True,
                        behavior_score=None,
                    )
                project_profile = not profile_event_is_before_reset(
                    connection,
                    user_id=payload.user_id,
                    event_ts=event_ts,
                )
                if not project_profile and self._settings.profile_v2_enabled:
                    PROFILE_V2_LATE_EVENTS.labels(reason="pre_reset").inc()
                if payload.sponsored_delivery_id:
                    sponsored_attribution = load_sponsored_attribution(
                        connection,
                        delivery_id=payload.sponsored_delivery_id,
                        user_id=payload.user_id,
                        article_id=payload.article_id,
                        for_update=True,
                    )
                answer_topic_ids = load_answer_topic_ids(connection, payload.article_id)
                topic_deltas = {
                    topic_id: self._settings.recommendation_click_topic_delta
                    for topic_id in answer_topic_ids
                }
                record_click_event(
                    connection=connection,
                    user_id=payload.user_id,
                    event_type="upvote",
                    article_id=payload.article_id,
                    query_key=payload.query_key,
                    request_id=payload.request_id,
                    surface=payload.surface or "home_feed",
                    event_ts=event_ts,
                    topic_ids=answer_topic_ids,
                    external_event_id=event.event_id,
                    sponsored_delivery_id=event.sponsored_delivery_id,
                    campaign_id=event.campaign_id,
                    creative_id=event.creative_id,
                )
                if sponsored_attribution is not None:
                    record_sponsored_click(
                        connection,
                        attribution=sponsored_attribution,
                        event_ts=event_ts,
                    )
                update: dict[str, Any] | None = None
                if project_profile:
                    profile_row = fetch_profile_row(
                        connection,
                        payload.user_id,
                        for_update=True,
                    )
                    update = apply_click_profile_update(
                        connection=connection,
                        profile_row=profile_row,
                        article_id=payload.article_id,
                        event_ts=event_ts,
                        topic_deltas=topic_deltas,
                        behavior_delta=self._settings.recommendation_click_behavior_delta,
                        decay_factor=self._settings.profile_topic_decay,
                    )
                    self._project_profile_v2(
                        connection,
                        event,
                        topic_strengths_for_event(
                            event.event_type,
                            article_topic_ids=answer_topic_ids,
                            dwell_ms=event.dwell_ms,
                        ),
                    )
                self._enqueue_raw_event(connection, event)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
            return EventTrackResponse(
                ok=True,
                event_type=payload.event_type,
                profile_updated=update is not None,
                behavior_score=(float(update["behavior_score"]) if update is not None else None),
            )

        # 仅记录日志的事件：feed_impression、detail_view、dwell、downvote、share
        event_ts = (
            payload.replay_event_ts if payload.replay_event_ts is not None else int(time.time())
        )
        if payload.article_id is None:
            raise ValueError(f"{payload.event_type} requires article_id")
        sponsored_attribution = self._load_sponsored_event_attribution(
            delivery_id=payload.sponsored_delivery_id,
            user_id=payload.user_id,
            article_id=payload.article_id,
        )
        event = self._event_message(
            event_type=cast(UserEventType, payload.event_type),
            user_id=payload.user_id,
            event_id=payload.event_id,
            article_id=payload.article_id,
            query_key=payload.query_key,
            request_id=payload.request_id,
            sponsored_delivery_id=payload.sponsored_delivery_id,
            campaign_id=(
                int(sponsored_attribution["campaign_id"])
                if sponsored_attribution is not None
                else None
            ),
            creative_id=(
                int(sponsored_attribution["creative_id"])
                if sponsored_attribution is not None
                else None
            ),
            surface=payload.surface or "home_feed",
            event_ts=event_ts,
            dwell_ms=payload.dwell_ms,
        )
        if self._settings.event_mode == "kafka_async":
            self._persist_async_event(event)
            return EventTrackResponse(
                ok=True,
                event_type=payload.event_type,
                profile_updated=False,
                behavior_score=None,
            )

        connection = self._connection_pool.connect()
        try:
            connection.begin()
            if not claim_event_id(connection, event):
                connection.commit()
                return EventTrackResponse(
                    ok=True,
                    event_type=payload.event_type,
                    profile_updated=False,
                    behavior_score=None,
                )
            project_profile = not profile_event_is_before_reset(
                connection,
                user_id=payload.user_id,
                event_ts=event_ts,
            )
            if not project_profile and self._settings.profile_v2_enabled:
                PROFILE_V2_LATE_EVENTS.labels(reason="pre_reset").inc()
            if payload.sponsored_delivery_id:
                sponsored_attribution = load_sponsored_attribution(
                    connection,
                    delivery_id=payload.sponsored_delivery_id,
                    user_id=payload.user_id,
                    article_id=payload.article_id,
                    for_update=True,
                )
            inserted = record_log_only_event(
                connection=connection,
                user_id=payload.user_id,
                event_type=payload.event_type,
                surface=payload.surface or "home_feed",
                article_id=payload.article_id,
                query_key=payload.query_key,
                request_id=payload.request_id,
                event_ts=event_ts,
                debug_payload_json=None,
                external_event_id=event.event_id,
                sponsored_delivery_id=event.sponsored_delivery_id,
                campaign_id=event.campaign_id,
                creative_id=event.creative_id,
                dwell_ms=event.dwell_ms,
            )
            if (
                inserted
                and payload.event_type == "feed_impression"
                and sponsored_attribution is not None
            ):
                confirm_sponsored_impression(
                    connection,
                    attribution=sponsored_attribution,
                    event_ts=event_ts,
                )
            profile_v2_updated = False
            if inserted and project_profile and payload.event_type in {"dwell", "downvote"}:
                answer_topic_ids = load_answer_topic_ids(connection, payload.article_id)
                profile_v2_updated = self._project_profile_v2(
                    connection,
                    event,
                    topic_strengths_for_event(
                        event.event_type,
                        article_topic_ids=answer_topic_ids,
                        dwell_ms=event.dwell_ms,
                    ),
                )
            self._enqueue_raw_event(connection, event)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return EventTrackResponse(
            ok=True,
            event_type=payload.event_type,
            profile_updated=profile_v2_updated,
            behavior_score=None,
        )

    # ── 编排辅助方法 ────────────────────────────────────────────

    def _project_profile_v2(
        self,
        connection: Any,
        event: UserEventMessage,
        topic_strengths: dict[int, float],
    ) -> bool:
        if not self._settings.profile_v2_enabled:
            return False
        started_at = time.perf_counter()
        try:
            outcome = apply_profile_v2_event_with_outcome(
                connection,
                user_id=event.user_id,
                event_type=event.event_type,
                event_ts=event.event_ts,
                topic_strengths=topic_strengths,
                config=profile_signal_config(self._settings),
            )
        finally:
            PROFILE_V2_PROJECTION_DURATION.observe(time.perf_counter() - started_at)
        if outcome.updated:
            PROFILE_V2_PROJECTION_UPDATES.labels(event_type=event.event_type).inc()
        if outcome.reason in {"pre_reset", "out_of_order"}:
            PROFILE_V2_LATE_EVENTS.labels(reason=outcome.reason).inc()
        elif outcome.late_topic_count:
            PROFILE_V2_LATE_EVENTS.labels(reason="out_of_order").inc()
        return outcome.updated

    def _artifact_debug(self) -> ArtifactDebug:
        lgb_metadata = loaded_model_metadata()
        als_metadata = get_als_recall().metadata()
        return ArtifactDebug(
            lightgbm_data_fingerprint=(
                str(lgb_metadata["data_fingerprint"])
                if lgb_metadata.get("data_fingerprint")
                else None
            ),
            lightgbm_feature_schema_version=(
                int(lgb_metadata["feature_schema_version"])
                if lgb_metadata.get("feature_schema_version") is not None
                else None
            ),
            als_data_fingerprint=(
                str(als_metadata["data_fingerprint"])
                if als_metadata.get("data_fingerprint")
                else None
            ),
            als_train_ratio=(
                float(str(als_metadata["train_ratio"]))
                if als_metadata.get("train_ratio") is not None
                else None
            ),
        )

    def _load_sponsored_event_attribution(
        self,
        *,
        delivery_id: str | None,
        user_id: int,
        article_id: int,
    ) -> dict[str, Any] | None:
        if not delivery_id:
            return None
        connection = self._connection_pool.connect()
        try:
            return load_sponsored_attribution(
                connection,
                delivery_id=delivery_id,
                user_id=user_id,
                article_id=article_id,
            )
        finally:
            connection.close()

    def _build_sponsored_feed_items(
        self,
        connection: Any,
        deliveries: list[SponsoredDelivery],
    ) -> tuple[list[FeedItem], list[SponsoredCandidateDebug]]:
        if not deliveries:
            return [], []
        answer_ids = [delivery.answer_id for delivery in deliveries]
        answer_rows = load_answer_rows(connection, answer_ids)
        topics_by_answer = load_topics_by_answer(connection, answer_ids)
        items: list[FeedItem] = []
        debug_rows: list[SponsoredCandidateDebug] = []
        for delivery in deliveries:
            row = answer_rows.get(delivery.answer_id)
            if row is None:
                raise RuntimeError(f"sponsored creative article is missing: {delivery.answer_id}")
            topics = topics_by_answer.get(delivery.answer_id, [])
            items.append(
                FeedItem(
                    article_id=delivery.answer_id,
                    headline=row.get("headline") or f"Article {delivery.answer_id}",
                    abstract=row.get("abstract") or "",
                    source_domain=row.get("source_domain") or "unknown-source",
                    categories=topics,
                    selected_reason=(
                        f"Sponsored candidate from {delivery.campaign_name}; "
                        "eligible by topic, budget, pacing, and frequency cap."
                    ),
                    scores=FeedItemScores(
                        base_recall_score=0.0,
                        personalized_topic_score=0.0,
                        default_topic_score=0.0,
                        topic_match_score=0.0,
                        query_recall_boost=0.0,
                        final_score=round(delivery.sponsored_score, 6),
                        sponsored_score=round(delivery.sponsored_score, 6),
                    ),
                    recall_sources=["sponsored"],
                    is_fallback=False,
                    content_type="sponsored",
                    sponsored=SponsoredFeedMetadata(
                        delivery_id=delivery.delivery_id,
                        campaign_id=delivery.campaign_id,
                        creative_id=delivery.creative_id,
                    ),
                )
            )
            debug_rows.append(
                SponsoredCandidateDebug(
                    campaign_id=delivery.campaign_id,
                    creative_id=delivery.creative_id,
                    article_id=delivery.answer_id,
                    slot_position=delivery.slot_position,
                    expected_spend_micros=delivery.expected_spend_micros,
                    sponsored_score=round(delivery.sponsored_score, 6),
                )
            )
        return items, debug_rows

    def _event_message(
        self,
        *,
        event_type: UserEventType,
        user_id: int,
        event_ts: int,
        event_id: str | None = None,
        article_id: int | None = None,
        query_key: str | None = None,
        query_text: str | None = None,
        request_id: str | None = None,
        sponsored_delivery_id: str | None = None,
        campaign_id: int | None = None,
        creative_id: int | None = None,
        surface: str = "feed",
        dwell_ms: int | None = None,
    ) -> UserEventMessage:
        message_values: dict[str, Any] = {
            "event_type": event_type,
            "user_id": user_id,
            "article_id": article_id,
            "query_key": query_key,
            "query_text": query_text,
            "request_id": request_id,
            "sponsored_delivery_id": sponsored_delivery_id,
            "campaign_id": campaign_id,
            "creative_id": creative_id,
            "surface": surface,
            "event_ts": event_ts,
            "dwell_ms": dwell_ms,
        }
        if event_id:
            message_values["event_id"] = event_id
        return UserEventMessage(**message_values)

    def _enqueue_raw_event(self, connection: Any, event: UserEventMessage) -> None:
        if not self._settings.kafka_enabled:
            return
        enqueue_outbox_message(
            connection,
            event_id=event.event_id,
            topic=self._settings.kafka_raw_events_topic,
            message_key=event.partition_key,
            payload_json=event.model_dump_json(exclude_none=True),
            payload_fingerprint=event.idempotency_fingerprint,
        )

    def _persist_async_event(self, event: UserEventMessage) -> None:
        connection = self._connection_pool.connect()
        try:
            connection.begin()
            self._enqueue_raw_event(connection, event)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _load_feed_candidates(
        self,
        connection: Any,
        topic_weight_map: dict[int, float],
        query_topic_scores: dict[int, float],
        page_size: int,
        user_id: int,
        use_als: bool,
        as_of_ts: int | None,
    ) -> dict[int, dict[str, Any]]:
        candidates: dict[int, dict[str, Any]] = {}
        profile_topic_ids = list(topic_weight_map)[:10]
        query_topic_ids = list(query_topic_scores)[:20]
        candidate_limit = max(page_size * 20, 50)

        for row in load_answer_ids_for_topics(
            connection,
            profile_topic_ids,
            candidate_limit,
            as_of_ts=as_of_ts,
        ):
            add_feed_candidate(
                candidates,
                answer_id=int(row["answer_id"]),
                source="profile_topic",
                is_fallback=False,
                raw_base_score=float(row.get("hot_score") or 0.0),
            )

        for row in load_answer_ids_for_topics(
            connection,
            query_topic_ids,
            candidate_limit,
            as_of_ts=as_of_ts,
        ):
            add_feed_candidate(
                candidates,
                answer_id=int(row["answer_id"]),
                source="recent_query_topic",
                is_fallback=False,
                raw_base_score=float(row.get("hot_score") or 0.0),
            )

        # ── ALS 协同过滤召回（第 4 个通道）────────────────────────
        if use_als:
            als = get_als_recall()
            als_candidates = als.get_candidates(
                user_id=user_id,
                k=self._settings.als_recall_top_k,
            )
            allowed_als_answer_ids = (
                load_answer_ids_created_as_of(
                    connection,
                    [answer_id for answer_id, _ in als_candidates],
                    as_of_ts=as_of_ts,
                )
                if as_of_ts is not None
                else {answer_id for answer_id, _ in als_candidates}
            )
            for answer_id, sim_score in als_candidates:
                if answer_id not in allowed_als_answer_ids:
                    continue
                add_feed_candidate(
                    candidates,
                    answer_id=answer_id,
                    source="als_cf",
                    is_fallback=False,
                    raw_base_score=float(sim_score),
                )

        non_fallback_count = sum(
            1 for candidate in candidates.values() if not candidate["is_fallback"]
        )
        if non_fallback_count < page_size:
            for row in load_hot_fallback_rows(
                connection,
                max(page_size * 5, 20),
                as_of_ts=as_of_ts,
            ):
                if len(candidates) >= page_size:
                    break
                add_feed_candidate(
                    candidates,
                    answer_id=int(row["answer_id"]),
                    source="hot_or_fresh",
                    is_fallback=True,
                    raw_base_score=float(row.get("hot_score") or 0.0),
                )

        return candidates
