from __future__ import annotations

from typing import Any

from backend.app.dependencies import get_feed_service, get_product_service
from backend.app.news_spaces.router import NewsSpaceRouter
from backend.app.schemas.article import ArticleCardResponse
from backend.app.schemas.feed import FeedResponse


def test_news_space_router_selects_only_known_space() -> None:
    router = NewsSpaceRouter(mind="mind-handler", live="live-handler")

    assert router.for_space("mind") == "mind-handler"
    assert router.for_space("live") == "live-handler"


def test_feed_route_propagates_source_and_language(unwired_client) -> None:
    class RecordingFeedService:
        def __init__(self) -> None:
            self.arguments: dict[str, Any] | None = None

        def get_feed(self, **arguments: Any) -> FeedResponse:
            self.arguments = arguments
            return FeedResponse(
                source_space=arguments["source_space"],
                user_id=arguments["user_id"],
                request_id="feed-live",
                items=[],
                next_cursor=None,
                has_more=False,
            )

    service = RecordingFeedService()
    unwired_client.app.dependency_overrides[get_feed_service] = lambda: service

    response = unwired_client.get(
        "/feed",
        params={"user_id": 7001, "source_space": "live", "language": "en"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["source_space"] == "live"
    assert service.arguments is not None
    assert service.arguments["source_space"] == "live"
    assert service.arguments["language"] == "en"


def test_unknown_feed_space_is_rejected(unwired_client) -> None:
    response = unwired_client.get(
        "/feed",
        params={"user_id": 7001, "source_space": "other"},
    )

    assert response.status_code == 422


def test_source_qualified_article_route_propagates_identity(unwired_client) -> None:
    class RecordingProductService:
        def __init__(self) -> None:
            self.arguments: tuple[str, str] | None = None

        def get_article_card(
            self,
            source_space: str,
            article_id: str,
        ) -> ArticleCardResponse:
            self.arguments = (source_space, article_id)
            return ArticleCardResponse(
                source_space="live",
                article_id=article_id,
                title="Live article",
                abstract="Summary",
                url="https://example.invalid/live",
                source_domain="example.invalid",
                category="",
                subcategory="",
                categories=[],
                title_entities=[],
                abstract_entities=[],
            )

    service = RecordingProductService()
    unwired_client.app.dependency_overrides[get_product_service] = lambda: service
    article_id = "L550e8400e29b41d4a716446655440000"

    response = unwired_client.get(f"/articles/live/{article_id}")

    assert response.status_code == 200, response.text
    assert service.arguments == ("live", article_id)
    assert response.json()["article_id"] == article_id


def test_news_space_capabilities_default_live_disabled(unwired_client) -> None:
    response = unwired_client.get("/news-spaces")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [
            {"source_space": "mind", "enabled": True},
            {"source_space": "live", "enabled": False},
        ]
    }
