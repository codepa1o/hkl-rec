from __future__ import annotations

from unittest.mock import Mock

from backend.app import errors
from backend.app.dependencies import get_feed_service
from backend.app.schemas.feed import FeedResponse
from backend.app.services.feed import FeedService


def test_feed_response_exposes_cursor_and_completion_state() -> None:
    response = FeedResponse(
        user_id=7001,
        request_id="feed-page-1",
        items=[],
        next_cursor="cursor-page-2",
        has_more=True,
    )

    assert response.next_cursor == "cursor-page-2"
    assert response.has_more is True


def test_feed_service_forwards_cursor_to_repository() -> None:
    repository = Mock()
    repository.get_feed.return_value = FeedResponse(
        user_id=7001,
        request_id="feed-page-2",
        items=[],
        next_cursor=None,
        has_more=False,
    )

    FeedService(repository).get_feed(
        user_id=7001,
        page_size=20,
        debug=True,
        request_id="feed-page-2",
        cursor="cursor-page-2",
        category="sports",
    )

    repository.get_feed.assert_called_once_with(
        user_id=7001,
        page_size=20,
        debug=True,
        experiment_arm="default",
        include_sponsored=True,
        request_id="feed-page-2",
        cursor="cursor-page-2",
        as_of_ts=None,
        category="sports",
    )


def test_feed_route_forwards_category(unwired_client) -> None:
    service = Mock()
    service.get_feed.return_value = FeedResponse(
        user_id=7001,
        request_id="category-feed",
        items=[],
        next_cursor=None,
        has_more=False,
    )
    unwired_client.app.dependency_overrides[get_feed_service] = lambda: service

    response = unwired_client.get(
        "/feed",
        params={"user_id": 7001, "category": "sports"},
    )

    assert response.status_code == 200
    service.get_feed.assert_called_once_with(
        user_id=7001,
        page_size=10,
        debug=False,
        experiment_arm="default",
        include_sponsored=True,
        request_id=None,
        cursor=None,
        as_of_ts=None,
        category="sports",
    )


def test_unknown_category_returns_a_structured_422(unwired_client) -> None:
    service = Mock()
    service.get_feed.side_effect = errors.UnknownCategoryError("not-a-category")
    unwired_client.app.dependency_overrides[get_feed_service] = lambda: service

    response = unwired_client.get(
        "/feed",
        params={"user_id": 7001, "category": "not-a-category"},
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "unknown_category"
