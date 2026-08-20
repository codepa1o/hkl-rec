from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

from backend.app.repositories import profile_dao
from backend.app.repositories.search_signal import LEGACY_SEARCH_CONFIG
from backend.app.schemas.profile import ProfileRecentClick, ProfileRecentQuery


class RecordingCursor(AbstractContextManager["RecordingCursor"]):
    def __init__(
        self,
        rows: list[dict[str, Any] | None],
        many: list[dict[str, Any]] | None = None,
    ) -> None:
        self.rows = rows
        self.many = many or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> RecordingCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows.pop(0)

    def fetchall(self) -> list[dict[str, Any]]:
        return self.many


class RecordingConnection:
    def __init__(
        self,
        rows: list[dict[str, Any] | None],
        many: list[dict[str, Any]] | None = None,
    ) -> None:
        self.cursor_value = RecordingCursor(rows, many)

    def cursor(self) -> RecordingCursor:
        return self.cursor_value


def test_attach_recent_click_titles_preserves_order_and_adds_news_titles():
    attach_titles = getattr(profile_dao, "attach_recent_click_titles", None)
    assert attach_titles is not None

    clicks = [
        ProfileRecentClick(news_id="N1003", click_ts=200),
        ProfileRecentClick(news_id="N11899", click_ts=100),
    ]
    news_rows = {
        "N1003": {"title": "Finance briefing"},
        "N11899": {"title": "Sports roundup"},
    }

    enriched = attach_titles(clicks, news_rows)

    assert [item.news_id for item in enriched] == ["N1003", "N11899"]
    assert [item.title for item in enriched] == ["Finance briefing", "Sports roundup"]


def test_attach_recent_click_titles_never_exposes_internal_id_as_title() -> None:
    clicks = [
        ProfileRecentClick(
            news_id="L0123456789abcdef0123456789abcdef",
            click_ts=200,
        )
    ]

    enriched = profile_dao.attach_recent_click_titles(clicks, {})

    assert enriched[0].title == "新闻标题暂不可用"


def test_fetch_profile_row_scopes_lookup_to_source_space() -> None:
    connection = RecordingConnection(
        [
            {
                "user_id": 7,
                "source_space": "live",
                "cold_start_seed_key": "live_cold_start_default",
                "topic_weights_json": [],
                "recent_clicked_news_json": [],
                "recent_queries_json": [],
                "behavior_score": 0.0,
            }
        ]
    )

    row = profile_dao.fetch_profile_row(connection, 7, "live")

    sql, params = connection.cursor_value.executed[0]
    assert "source_space" in sql
    assert "WHERE user_id = %s AND source_space = %s" in sql
    assert params == (7, "live")
    assert row["source_space"] == "live"


def test_profile_from_row_echoes_source_space() -> None:
    response = profile_dao.profile_from_row(
        {
            "user_id": 7,
            "source_space": "live",
            "cold_start_seed_key": "live_cold_start_default",
            "topic_weights_json": [],
            "recent_clicked_news_json": [],
            "recent_queries_json": [],
            "behavior_score": 0.0,
        }
    )

    assert response.source_space == "live"


def test_default_seed_and_query_topics_are_scoped_to_source_space() -> None:
    seed_connection = RecordingConnection([{"topic_weights_json": []}])
    profile_dao.load_default_seed_topic_weights(
        seed_connection,
        seed_key="live_cold_start_default",
        source_space="live",
    )
    seed_sql, seed_params = seed_connection.cursor_value.executed[0]
    assert "source_space = %s" in seed_sql
    assert seed_params == ("live_cold_start_default", "live")

    query_connection = RecordingConnection(
        [],
        [{"query_key": "markets", "topic_id": 9, "score": 0.8}],
    )
    scores = profile_dao.load_recent_query_topic_scores(
        query_connection,
        [ProfileRecentQuery(query_key="markets", query_ts=1)],
        source_space="live",
        now_ts=1,
        config=LEGACY_SEARCH_CONFIG,
    )
    query_sql, query_params = query_connection.cursor_value.executed[0]
    assert "query_topic_map.source_space = %s" in query_sql
    assert "topic.source_space = %s" in query_sql
    assert query_params[-2:] == ("live", "live")
    assert scores == {9: 0.8}
