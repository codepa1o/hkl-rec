from __future__ import annotations

from dataclasses import replace

import pytest

from backend.app.config import get_settings
from backend.app.errors import IdempotencyConflictError
from backend.app.repositories.postgres import PostgresRuntimeRepository
from backend.app.repositories.profile_dao import ensure_profile_row
from backend.app.repositories.sponsored_dao import claim_feed_request
from backend.app.schemas.event import RecommendationClickRequest, SearchResultClickRequest
from backend.app.schemas.search import SearchRequest


@pytest.mark.postgres
def test_live_click_and_reset_change_only_live_profile(
    postgres_connection,
    seeded_live_articles,
) -> None:
    for source_space in ("mind", "live"):
        ensure_profile_row(postgres_connection, seeded_live_articles.user_id, source_space)
    postgres_connection.commit()
    repository = PostgresRuntimeRepository(replace(get_settings(), live_news_enabled=True))
    try:
        mind_before = repository.get_profile(seeded_live_articles.user_id, "mind")
        live_before = repository.get_profile(seeded_live_articles.user_id, "live")
        live_behavior_before = repository.get_debug_profile(
            seeded_live_articles.user_id, "live"
        ).behavior_score
        feed = repository.get_feed(
            user_id=seeded_live_articles.user_id,
            page_size=10,
            debug=False,
            source_space="live",
            language="all",
        )
        clicked = feed.items[0]

        repository.record_recommendation_click(
            RecommendationClickRequest(
                user_id=seeded_live_articles.user_id,
                source_space="live",
                article_id=clicked.article_id,
                request_id=feed.request_id,
            )
        )

        mind_after = repository.get_profile(seeded_live_articles.user_id, "mind")
        live_after = repository.get_profile(seeded_live_articles.user_id, "live")
        assert mind_after == mind_before
        assert live_before.status == "cold"
        assert live_after.recent_clicked_news[0].news_id == clicked.article_id
        assert live_after.recent_clicked_news[0].title == clicked.title
        assert (
            repository.get_debug_profile(
                seeded_live_articles.user_id,
                "live",
            )
            .recent_clicked_news[0]
            .title
            == clicked.title
        )
        assert (
            repository.get_debug_profile(seeded_live_articles.user_id, "live").behavior_score
            > live_behavior_before
        )

        repository.reset_profile(seeded_live_articles.user_id, "live")
        assert repository.get_profile(seeded_live_articles.user_id, "mind") == mind_before
        assert repository.get_profile(seeded_live_articles.user_id, "live").status == "cold"
    finally:
        repository.close()


@pytest.mark.postgres
def test_cross_space_feed_request_is_rejected_without_profile_write(
    postgres_connection,
    seeded_live_articles,
) -> None:
    ensure_profile_row(postgres_connection, seeded_live_articles.user_id, "live")
    postgres_connection.commit()
    repository = PostgresRuntimeRepository(replace(get_settings(), live_news_enabled=True))
    try:
        live_before = repository.get_profile(seeded_live_articles.user_id, "live")
        claim_feed_request(
            postgres_connection,
            request_id="mind-request-used-as-live",
            source_space="mind",
            user_id=seeded_live_articles.user_id,
            page_size=1,
            debug=False,
            include_sponsored=False,
            experiment_arm="default",
            as_of_ts=None,
        )
        postgres_connection.commit()
        with pytest.raises(IdempotencyConflictError):
            repository.record_recommendation_click(
                RecommendationClickRequest(
                    user_id=seeded_live_articles.user_id,
                    source_space="live",
                    article_id=seeded_live_articles.article_ids[0],
                    request_id="mind-request-used-as-live",
                )
            )
        assert repository.get_profile(seeded_live_articles.user_id, "live") == live_before
    finally:
        repository.close()


@pytest.mark.postgres
def test_live_search_and_click_update_only_live_history(
    postgres_connection,
    seeded_live_articles,
) -> None:
    for source_space in ("mind", "live"):
        ensure_profile_row(postgres_connection, seeded_live_articles.user_id, source_space)
    postgres_connection.commit()
    repository = PostgresRuntimeRepository(replace(get_settings(), live_news_enabled=True))
    try:
        mind_before = repository.get_profile(seeded_live_articles.user_id, "mind")
        result = repository.search(
            SearchRequest(
                user_id=seeded_live_articles.user_id,
                source_space="live",
                query_text="fixture",
            )
        )
        repository.record_search_result_click(
            SearchResultClickRequest(
                user_id=seeded_live_articles.user_id,
                source_space="live",
                article_id=result.items[0].article_id,
                query_key=result.query_key,
                request_id=result.request_id,
            )
        )

        live_after = repository.get_profile(seeded_live_articles.user_id, "live")
        assert live_after.recent_queries[0].query_key == "fixture"
        assert live_after.recent_queries[0].confirmed_ts is not None
        assert live_after.recent_clicked_news[0].news_id == result.items[0].article_id
        assert repository.get_profile(seeded_live_articles.user_id, "mind") == mind_before
    finally:
        repository.close()


@pytest.mark.postgres
def test_async_live_search_click_accepts_pending_search_outbox(
    seeded_live_articles,
) -> None:
    settings = replace(
        get_settings(),
        live_news_enabled=True,
        event_mode="kafka_async",
    )
    repository = PostgresRuntimeRepository(settings)
    try:
        result = repository.search(
            SearchRequest(
                user_id=seeded_live_articles.user_id,
                source_space="live",
                query_text="fixture",
            )
        )

        response = repository.record_search_result_click(
            SearchResultClickRequest(
                user_id=seeded_live_articles.user_id,
                source_space="live",
                article_id=result.items[0].article_id,
                query_key=result.query_key,
                request_id=result.request_id,
            )
        )

        assert response.ok is True
        assert response.source_space == "live"
    finally:
        repository.close()
