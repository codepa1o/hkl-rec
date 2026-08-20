from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.news_spaces.types import DEFAULT_NEWS_SPACE, validate_article_id_shape
from backend.app.schemas.article import ArticleCardResponse
from backend.app.schemas.category import CategoryListResponse
from backend.app.schemas.feed import FeedItem, FeedResponse
from backend.app.schemas.profile import DebugProfileResponse, ProfileResponse
from backend.app.schemas.search import SearchItem, SearchRequest, SearchResponse
from backend.app.schemas.suggestion import SuggestionListResponse


def test_default_news_space_preserves_mind_compatibility() -> None:
    assert DEFAULT_NEWS_SPACE == "mind"


@pytest.mark.parametrize(
    ("source_space", "article_id"),
    [
        ("mind", "N123"),
        ("live", "L0123456789abcdef0123456789abcdef"),
    ],
)
def test_article_id_shape_is_valid_for_its_source_space(source_space: str, article_id: str) -> None:
    assert validate_article_id_shape(source_space, article_id) == article_id


@pytest.mark.parametrize(
    ("source_space", "article_id"),
    [
        ("mind", "L0123456789abcdef0123456789abcdef"),
        ("live", "N123"),
    ],
)
def test_article_id_shape_rejects_cross_space_ids(source_space: str, article_id: str) -> None:
    with pytest.raises(ValueError, match="does not belong"):
        validate_article_id_shape(source_space, article_id)


def test_article_id_shape_rejects_unsupported_source_space() -> None:
    with pytest.raises(ValueError, match="unsupported source_space: archive"):
        validate_article_id_shape("archive", "N123")


def _feed_item(**overrides: object) -> FeedItem:
    values: dict[str, object] = {
        "news_id": "N123",
        "title": "Title",
        "abstract": "Abstract",
        "url": "https://example.com/article",
        "source_domain": "example.com",
        "category": "news",
        "subcategory": "general",
        "categories": [{"topic_id": 1, "display_name": "News"}],
        "selected_reason": "Because it matches your interests",
        "scores": {
            "base_recall_score": 0.1,
            "personalized_topic_score": 0.2,
            "default_topic_score": 0.3,
            "topic_match_score": 0.4,
            "query_recall_boost": 0.0,
            "final_score": 0.5,
        },
        "recall_sources": ["topic"],
        "is_fallback": False,
    }
    values.update(overrides)
    return FeedItem(**values)


def _search_item(**overrides: object) -> SearchItem:
    values: dict[str, object] = {
        "news_id": "N123",
        "title": "Title",
        "abstract": "Abstract",
        "url": "https://example.com/article",
        "source_domain": "example.com",
        "category": "news",
        "subcategory": "general",
        "categories": [{"topic_id": 1, "display_name": "News"}],
        "scores": {"topic_match_score": 0.4, "final_score": 0.5},
    }
    values.update(overrides)
    return SearchItem(**values)


def _article_card(**overrides: object) -> ArticleCardResponse:
    values: dict[str, object] = {
        "news_id": "N123",
        "title": "Title",
        "abstract": "Abstract",
        "url": "https://example.com/article",
        "source_domain": "example.com",
        "category": "news",
        "subcategory": "general",
        "categories": [{"topic_id": 1, "display_name": "News"}],
        "title_entities": [],
        "abstract_entities": [],
    }
    values.update(overrides)
    return ArticleCardResponse(**values)


type ArticleModel = FeedItem | SearchItem | ArticleCardResponse
type ArticleModelFactory = Callable[..., ArticleModel]

_ARTICLE_MODEL_FACTORIES: list[ArticleModelFactory] = [_feed_item, _search_item, _article_card]


@pytest.mark.parametrize("factory", _ARTICLE_MODEL_FACTORIES)
def test_mind_article_models_accept_legacy_news_id_and_populate_article_id(
    factory: ArticleModelFactory,
) -> None:
    item = factory()

    assert item.source_space == "mind"
    assert item.article_id == "N123"
    with pytest.warns(DeprecationWarning, match="deprecated"):
        assert item.news_id == "N123"


@pytest.mark.parametrize("factory", _ARTICLE_MODEL_FACTORIES)
def test_mind_article_models_accept_canonical_article_id_and_populate_news_id(
    factory: ArticleModelFactory,
) -> None:
    item = factory(article_id="N123", news_id=None)

    assert item.article_id == "N123"
    with pytest.warns(DeprecationWarning, match="deprecated"):
        assert item.news_id == "N123"


@pytest.mark.parametrize("factory", _ARTICLE_MODEL_FACTORIES)
def test_mind_article_models_accept_explicit_canonical_and_legacy_ids(
    factory: ArticleModelFactory,
) -> None:
    item = factory(article_id="N123", news_id="N123")

    assert item.article_id == "N123"


@pytest.mark.parametrize("factory", _ARTICLE_MODEL_FACTORIES)
def test_live_article_models_accept_canonical_article_id(factory: ArticleModelFactory) -> None:
    item = factory(
        source_space="live",
        article_id="L0123456789abcdef0123456789abcdef",
        news_id=None,
    )

    assert item.article_id == "L0123456789abcdef0123456789abcdef"
    with pytest.warns(DeprecationWarning, match="deprecated"):
        assert item.news_id is None


@pytest.mark.parametrize("factory", _ARTICLE_MODEL_FACTORIES)
def test_mind_article_models_reject_mismatched_article_and_news_ids(
    factory: ArticleModelFactory,
) -> None:
    with pytest.raises(ValidationError, match="article_id and news_id"):
        factory(article_id="N124")


@pytest.mark.parametrize("factory", _ARTICLE_MODEL_FACTORIES)
def test_live_article_models_reject_legacy_news_id(factory: ArticleModelFactory) -> None:
    with pytest.raises(ValidationError, match="news_id is only supported for source_space 'mind'"):
        factory(
            source_space="live",
            article_id="L0123456789abcdef0123456789abcdef",
            news_id="L0123456789abcdef0123456789abcdef",
        )


@pytest.mark.parametrize("factory", _ARTICLE_MODEL_FACTORIES)
def test_article_models_require_an_identifier(factory: ArticleModelFactory) -> None:
    with pytest.raises(ValidationError, match="article_id"):
        factory(news_id=None)


def test_feed_response_rejects_items_from_a_different_source_space() -> None:
    with pytest.raises(ValidationError, match="items must match response source_space"):
        FeedResponse(
            source_space="live",
            user_id=1,
            request_id="feed",
            items=[_feed_item()],
        )


def test_search_response_rejects_items_from_a_different_source_space() -> None:
    with pytest.raises(ValidationError, match="items must match response source_space"):
        SearchResponse(
            source_space="live",
            user_id=1,
            request_id="search",
            query_key="query",
            items=[_search_item()],
        )


def test_openapi_marks_article_id_as_required(unwired_client: TestClient) -> None:
    document = unwired_client.get("/openapi.json").json()

    for schema_name in ("FeedItem", "SearchItem", "ArticleCardResponse"):
        assert "article_id" in document["components"]["schemas"][schema_name]["required"]


def test_requests_and_list_profile_responses_default_to_mind() -> None:
    profile = ProfileResponse(
        user_id=1,
        status="cold",
        confidence=0.0,
        evidence_count=0,
        short_term={},
        long_term={},
    )
    debug_profile = DebugProfileResponse(
        user_id=1,
        cold_start_seed_key="default",
        behavior_score=0.0,
        topic_weights=[],
        recent_clicked_news=[],
        recent_queries=[],
        vector_summary={"vector_key_count": 0, "top_contributing_topics": []},
    )

    assert SearchRequest(user_id=1, query_key="query").source_space == "mind"
    assert FeedResponse(user_id=1, request_id="feed", items=[]).source_space == "mind"
    assert (
        SearchResponse(user_id=1, request_id="search", query_key="query", items=[]).source_space
        == "mind"
    )
    assert profile.source_space == "mind"
    assert debug_profile.source_space == "mind"
    assert CategoryListResponse(items=[]).source_space == "mind"
    assert SuggestionListResponse(items=[]).source_space == "mind"
