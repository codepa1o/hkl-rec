from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock

from backend.app.config import Settings
from backend.app.dependencies import get_feed_service
from backend.app.live_news.allowlist import SourceAllowlist
from backend.app.news_spaces.live import LiveNewsSpaceRepository
from backend.app.repositories.postgres import PostgresRuntimeRepository
from backend.app.schemas.feed import FeedUpdateStatusResponse


def test_feed_update_route_forwards_the_read_only_query(unwired_client) -> None:
    service = Mock()
    service.get_feed_update_status.return_value = FeedUpdateStatusResponse(
        source_space="live",
        has_updates=True,
        current_watermark=datetime(2026, 8, 20, 1, 5, tzinfo=UTC),
    )
    unwired_client.app.dependency_overrides[get_feed_service] = lambda: service

    response = unwired_client.get(
        "/feed/updates",
        params={
            "user_id": 7248,
            "source_space": "live",
            "language": "zh",
            "since": "2026-08-20T01:00:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "source_space": "live",
        "has_updates": True,
        "current_watermark": "2026-08-20T01:05:00Z",
    }
    service.get_feed_update_status.assert_called_once_with(
        user_id=7248,
        source_space="live",
        language="zh",
        since=datetime(2026, 8, 20, 1, 0, tzinfo=UTC),
        category=None,
    )


def test_mind_update_status_is_constant_and_rejects_live_language(unwired_client) -> None:
    service = Mock()
    service.get_feed_update_status.return_value = FeedUpdateStatusResponse(
        source_space="mind",
        has_updates=False,
        current_watermark=None,
    )
    unwired_client.app.dependency_overrides[get_feed_service] = lambda: service

    response = unwired_client.get(
        "/feed/updates",
        params={
            "user_id": 7248,
            "source_space": "mind",
            "language": "all",
            "since": "2026-08-20T01:00:00Z",
        },
    )
    invalid = unwired_client.get(
        "/feed/updates",
        params={
            "user_id": 7248,
            "source_space": "mind",
            "language": "zh",
            "since": "2026-08-20T01:00:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json()["has_updates"] is False
    assert invalid.status_code == 422


class RecordingCursor:
    def __init__(self, watermark: datetime | None) -> None:
        self.watermark = watermark
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> RecordingCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self) -> dict[str, datetime | None]:
        return {"current_watermark": self.watermark}


class RecordingConnection:
    def __init__(self, watermark: datetime | None) -> None:
        self.cursor_value = RecordingCursor(watermark)
        self.closed = False

    def cursor(self) -> RecordingCursor:
        return self.cursor_value

    def close(self) -> None:
        self.closed = True


class RecordingPool:
    def __init__(self, connection: RecordingConnection) -> None:
        self.connection = connection

    def connect(self) -> RecordingConnection:
        return self.connection


def test_live_update_status_uses_one_select_and_no_write_transaction() -> None:
    since = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
    connection = RecordingConnection(since + timedelta(minutes=5))
    repository = LiveNewsSpaceRepository(
        RecordingPool(connection),  # type: ignore[arg-type]
        Settings(),
        SourceAllowlist(policies=()),
    )

    response = repository.get_feed_update_status(language="zh", since=since)

    assert response == FeedUpdateStatusResponse(
        source_space="live",
        has_updates=True,
        current_watermark=since + timedelta(minutes=5),
    )
    assert connection.closed is True
    assert len(connection.cursor_value.executed) == 1
    sql, params = connection.cursor_value.executed[0]
    assert sql.startswith("SELECT MAX(discovered_at) AS current_watermark FROM live_news")
    assert "status = 'active'" in sql
    assert "discovered_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'" in sql
    assert "language = %s" in sql
    assert params == ("zh",)
    assert all(keyword not in sql for keyword in ("INSERT", "UPDATE", "DELETE"))


def test_postgres_update_status_does_not_create_a_live_profile() -> None:
    since = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
    repository = object.__new__(PostgresRuntimeRepository)
    repository._settings = Settings(live_news_enabled=True)  # type: ignore[attr-defined]
    repository._live_news_space = Mock()  # type: ignore[attr-defined]
    repository._live_news_space.get_feed_update_status.return_value = (  # type: ignore[attr-defined]
        FeedUpdateStatusResponse(
            source_space="live",
            has_updates=False,
            current_watermark=since,
        )
    )
    repository._ensure_live_profile = Mock()  # type: ignore[method-assign]

    repository.get_feed_update_status(7248, "live", "all", since)

    repository._ensure_live_profile.assert_not_called()  # type: ignore[attr-defined]
