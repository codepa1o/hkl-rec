from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any
from unittest.mock import Mock

from backend.app import errors
from backend.app.dependencies import get_feed_service
from backend.app.repositories.sponsored_dao import (
    claim_feed_request,
    complete_feed_request,
    load_feed_session_news_ids,
)
from backend.app.schemas.feed import FeedResponse
from backend.app.services.feed import FeedService


class RecordingCursor(AbstractContextManager["RecordingCursor"]):
    rowcount = 1

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.one: dict[str, Any] | None = {"cursor_token": None}

    def __enter__(self) -> RecordingCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self) -> dict[str, Any] | None:
        return self.one

    def fetchall(self) -> list[dict[str, Any]]:
        return []


class RecordingConnection:
    def __init__(self) -> None:
        self.cursor_value = RecordingCursor()

    def cursor(self) -> RecordingCursor:
        return self.cursor_value


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
        source_space="mind",
        language="all",
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
        source_space="mind",
        language="all",
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


def test_feed_request_persistence_and_pagination_are_scoped_to_source_space() -> None:
    connection = RecordingConnection()

    claim_feed_request(
        connection,
        request_id="live-feed",
        source_space="live",
        user_id=7001,
        page_size=10,
        debug=False,
        include_sponsored=False,
        experiment_arm="default",
        as_of_ts=None,
    )
    load_feed_session_news_ids(connection, session_id="live-feed", source_space="live")
    complete_feed_request(
        connection,
        request_id="live-feed",
        source_space="live",
        news_ids=["L550e8400e29b41d4a716446655440000"],
        next_cursor=None,
    )

    insert_sql, insert_params = connection.cursor_value.executed[0]
    session_sql, session_params = connection.cursor_value.executed[1]
    complete_sql, complete_params = connection.cursor_value.executed[2]
    assert "source_space" in insert_sql
    assert "live" in insert_params
    assert "source_space = %s" in session_sql
    assert session_params == ("live-feed", "live")
    assert "source_space = %s" in complete_sql
    assert complete_params[-2:] == ("live-feed", "live")
