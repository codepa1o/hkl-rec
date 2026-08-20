from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Any

import pytest

from backend.app.errors import IdempotencyConflictError
from backend.app.events.schema import UserEventMessage
from backend.app.profiles.signals import ProfileSignalConfig, TopicProfileState
from backend.app.repositories import profile_dao
from backend.app.repositories.event_dao import (
    append_recent_query,
    apply_click_profile_update,
    claim_event_id,
    confirm_recent_query,
    record_click_event,
    record_log_only_event,
    record_search_query,
)
from backend.app.repositories.profile_v2_dao import (
    apply_profile_v2_event,
    fetch_topic_profile_state,
    load_profile_v2,
    load_topic_profile_rows,
    reset_profile_projections,
    upsert_topic_profile_state,
)
from backend.app.repositories.search_signal import LEGACY_SEARCH_CONFIG
from backend.app.repositories.sponsored_dao import claim_feed_request, complete_feed_request
from backend.app.schemas.profile import ProfileRecentQuery

requires_postgres = pytest.mark.skipif(
    not os.environ.get("NEWSREC_DATABASE_URL", "").strip(),
    reason="NEWSREC_DATABASE_URL not set",
)

PROFILE_CONFIG = ProfileSignalConfig(
    short_half_life_seconds=100,
    long_half_life_seconds=200,
    long_term_factor=0.25,
)


class RecordingCursor(AbstractContextManager["RecordingCursor"]):
    def __init__(self, *, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> RecordingCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self) -> dict[str, Any] | None:
        return None


class RecordingConnection:
    def __init__(self, *, rowcount: int = 1) -> None:
        self.cursor_value = RecordingCursor(rowcount=rowcount)

    def cursor(self) -> RecordingCursor:
        return self.cursor_value


@pytest.fixture
def isolated_space_user(postgres_connection: Any) -> Iterator[tuple[Any, int, int]]:
    connection = postgres_connection
    connection.rollback()
    user_id = 9_000_000_000 + (uuid.uuid4().int % 100_000_000)
    live_topic_id = user_id + 100_000_000
    mind_topic_id = user_id + 200_000_000
    mind_news_id = f"N{user_id}"
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO system_profile_seed "
            "(seed_key, source_space, topic_weights_json, recent_clicked_news_json, "
            "recent_queries_json, behavior_score, notes) "
            "VALUES ('cold_start_default', 'mind', '[]'::jsonb, '[]'::jsonb, "
            "'[]'::jsonb, 0, 'test seed') "
            "ON CONFLICT (seed_key) DO NOTHING"
        )
        cursor.execute(
            "INSERT INTO app_user (user_id, display_name, is_demo_user, source) "
            "VALUES (%s, %s, false, 'test')",
            (user_id, f"space isolation {user_id}"),
        )
        cursor.execute(
            "INSERT INTO topic "
            "(topic_id, source_space, topic_key, display_name, news_count, source) "
            "VALUES (%s, 'mind', %s, 'MIND isolation', 1, 'test')",
            (mind_topic_id, f"mind-isolation-{user_id}"),
        )
        cursor.execute(
            "INSERT INTO topic "
            "(topic_id, source_space, topic_key, display_name, news_count, source) "
            "VALUES (%s, 'live', %s, 'Live isolation', 0, 'test')",
            (live_topic_id, f"live-isolation-{user_id}"),
        )
        cursor.execute(
            "INSERT INTO mind_news "
            "(news_id, category, subcategory, title, abstract, url, "
            "title_entities, abstract_entities) "
            "VALUES (%s, 'test', 'test', 'Isolation article', '', %s, "
            "'[]'::jsonb, '[]'::jsonb)",
            (mind_news_id, f"https://example.test/{mind_news_id}"),
        )
    try:
        yield connection, user_id, live_topic_id
    finally:
        connection.rollback()


@pytest.mark.postgres
@requires_postgres
def test_profile_creation_mutation_and_reset_are_isolated_by_space(
    isolated_space_user: tuple[Any, int, int],
) -> None:
    connection, user_id, _live_topic_id = isolated_space_user
    mind = profile_dao.ensure_profile_row(connection, user_id, "mind")
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE user_profile SET behavior_score = 9, recent_queries_json = %s::jsonb "
            "WHERE user_id = %s AND source_space = 'mind'",
            ('[{"query_key":"9","query_ts":10}]', user_id),
        )
    existing_mind = profile_dao.ensure_profile_row(connection, user_id, "mind")
    live = profile_dao.ensure_profile_row(connection, user_id, "live")

    assert existing_mind["behavior_score"] == 9
    assert live["source_space"] == "live"
    assert live["cold_start_seed_key"] == "live_cold_start_default"
    assert live["topic_weights_json"] == []
    assert live["recent_clicked_news_json"] == []
    assert live["recent_queries_json"] == []
    assert live["behavior_score"] == 0
    assert live["user_vector_json"] is None

    append_recent_query(connection, live, "1 2", 20, 1.0, source_space="live")
    live = profile_dao.fetch_profile_row(connection, user_id, "live")
    apply_click_profile_update(
        connection,
        live,
        "L550e8400e29b41d4a716446655440000",
        21,
        {},
        2.0,
        1.0,
        source_space="live",
    )

    mind_after_live_updates = profile_dao.fetch_profile_row(connection, user_id, "mind")
    live_after_updates = profile_dao.fetch_profile_row(connection, user_id, "live")
    assert mind_after_live_updates["behavior_score"] == 9
    assert mind_after_live_updates["recent_queries_json"][0]["query_key"] == "9"
    assert live_after_updates["behavior_score"] == 3
    assert live_after_updates["recent_queries_json"][0]["query_key"] == "1 2"
    loaded_live_profile = load_profile_v2(
        connection,
        user_id=user_id,
        source_space="live",
        now_ts=21,
        config=PROFILE_CONFIG,
    )
    assert [item.news_id for item in loaded_live_profile.recent_clicked_news] == [
        "L550e8400e29b41d4a716446655440000"
    ]

    reset_profile_projections(connection, user_id=user_id, source_space="live", reset_ts=30)
    reset_live = profile_dao.fetch_profile_row(connection, user_id, "live")
    unchanged_mind = profile_dao.fetch_profile_row(connection, user_id, "mind")
    assert reset_live["behavior_score"] == 0
    assert reset_live["recent_queries_json"] == []
    assert unchanged_mind["behavior_score"] == 9
    assert mind["source_space"] == "mind"


@pytest.mark.postgres
@requires_postgres
def test_topic_projection_rows_and_loaders_are_isolated_by_space(
    isolated_space_user: tuple[Any, int, int],
) -> None:
    connection, user_id, live_topic_id = isolated_space_user
    profile_dao.ensure_profile_row(connection, user_id, "mind")
    profile_dao.ensure_profile_row(connection, user_id, "live")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT topic_id FROM topic WHERE source_space = 'mind' AND topic_key = %s",
            (f"mind-isolation-{user_id}",),
        )
        mind_topic_id = int(cursor.fetchone()["topic_id"])
        cursor.execute(
            "INSERT INTO query_topic_map "
            "(source_space, query_key, topic_id, score, match_rank, source_method) "
            "VALUES ('mind', '1 2', %s, 0.4, 0, 'test'), "
            "('live', '1 2', %s, 0.9, 0, 'test')",
            (mind_topic_id, live_topic_id),
        )

    mind_state = TopicProfileState(short_positive_score=1, last_event_ts=10)
    live_state = TopicProfileState(short_positive_score=3, last_event_ts=12)
    upsert_topic_profile_state(
        connection,
        user_id=user_id,
        source_space="mind",
        topic_id=mind_topic_id,
        state=mind_state,
    )
    upsert_topic_profile_state(
        connection,
        user_id=user_id,
        source_space="live",
        topic_id=live_topic_id,
        state=live_state,
    )

    assert (
        fetch_topic_profile_state(
            connection, user_id=user_id, source_space="mind", topic_id=mind_topic_id
        ).short_positive_score
        == 1
    )
    with pytest.raises(ValueError, match="source_space"):
        upsert_topic_profile_state(
            connection,
            user_id=user_id,
            source_space="live",
            topic_id=mind_topic_id,
            state=TopicProfileState(short_positive_score=2, last_event_ts=13),
        )
    with pytest.raises(ValueError, match="source_space"):
        apply_profile_v2_event(
            connection,
            user_id=user_id,
            source_space="live",
            event_type="upvote",
            event_ts=14,
            topic_strengths={mind_topic_id: 1.0},
            config=PROFILE_CONFIG,
        )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT profile_v2_evidence_count FROM user_profile "
            "WHERE user_id = %s AND source_space = 'live'",
            (user_id,),
        )
        assert cursor.fetchone()["profile_v2_evidence_count"] == 0
    assert {
        row["topic_id"]
        for row in load_topic_profile_rows(connection, user_id=user_id, source_space="mind")
    } == {mind_topic_id}
    assert {
        row["topic_id"]
        for row in load_topic_profile_rows(connection, user_id=user_id, source_space="live")
    } == {live_topic_id}
    recent_queries = [ProfileRecentQuery(query_key="1 2", query_ts=1)]
    assert profile_dao.load_recent_query_topic_scores(
        connection,
        recent_queries,
        source_space="mind",
        now_ts=1,
        config=LEGACY_SEARCH_CONFIG,
    ) == {mind_topic_id: 0.4}
    assert profile_dao.load_recent_query_topic_scores(
        connection,
        recent_queries,
        source_space="live",
        now_ts=1,
        config=LEGACY_SEARCH_CONFIG,
    ) == {live_topic_id: 0.9}


@pytest.mark.postgres
@requires_postgres
def test_feed_request_and_cursor_claims_cannot_cross_spaces(
    isolated_space_user: tuple[Any, int, int],
) -> None:
    connection, user_id, _live_topic_id = isolated_space_user
    request_id = f"mind-request-{user_id}"
    claim_feed_request(
        connection,
        request_id=request_id,
        source_space="mind",
        user_id=user_id,
        page_size=10,
        debug=False,
        include_sponsored=False,
        experiment_arm="default",
        as_of_ts=None,
    )
    cursor_token = f"mind-cursor-{user_id}"
    complete_feed_request(
        connection,
        request_id=request_id,
        source_space="mind",
        news_ids=[],
        next_cursor=cursor_token,
    )

    with pytest.raises(IdempotencyConflictError):
        claim_feed_request(
            connection,
            request_id=request_id,
            source_space="live",
            user_id=user_id,
            page_size=10,
            debug=False,
            include_sponsored=False,
            experiment_arm="default",
            as_of_ts=None,
        )
    with pytest.raises(IdempotencyConflictError):
        claim_feed_request(
            connection,
            request_id=f"live-request-{user_id}",
            source_space="live",
            user_id=user_id,
            page_size=10,
            debug=False,
            include_sponsored=False,
            experiment_arm="default",
            as_of_ts=None,
            cursor_token=cursor_token,
        )


@pytest.mark.postgres
@requires_postgres
def test_event_rows_store_source_space_and_canonical_article_id(
    isolated_space_user: tuple[Any, int, int],
) -> None:
    connection, user_id, _live_topic_id = isolated_space_user
    with connection.cursor() as cursor:
        cursor.execute("SELECT news_id FROM mind_news LIMIT 1")
        mind_article_id = str(cursor.fetchone()["news_id"])
    live_article_id = "L550e8400e29b41d4a716446655440000"
    mind_event = UserEventMessage(
        event_id=f"mind-event-{user_id}",
        event_type="feed_impression",
        user_id=user_id,
        source_space="mind",
        article_id=mind_article_id,
        news_id=mind_article_id,
        event_ts=100,
    )
    assert claim_event_id(connection, mind_event, source_space="mind")
    with pytest.raises(IdempotencyConflictError):
        claim_event_id(connection, mind_event, source_space="live")

    record_click_event(
        connection,
        user_id,
        "recommendation_click",
        mind_article_id,
        None,
        None,
        "feed",
        101,
        [],
        source_space="mind",
    )
    record_click_event(
        connection,
        user_id,
        "recommendation_click",
        live_article_id,
        None,
        None,
        "feed",
        102,
        [],
        source_space="live",
    )
    record_search_query(connection, user_id, "1 2", 103, source_space="live")
    record_log_only_event(
        connection,
        user_id,
        "detail_view",
        "detail",
        live_article_id,
        None,
        None,
        104,
        None,
        source_space="live",
    )

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT source_space, article_id, event_type FROM user_event "
            "WHERE user_id = %s ORDER BY event_ts",
            (user_id,),
        )
        rows = cursor.fetchall()
        cursor.execute(
            "SELECT source_space FROM event_idempotency WHERE external_event_id = %s",
            (mind_event.event_id,),
        )
        claim = cursor.fetchone()
    assert rows[0]["source_space"] == "mind"
    assert rows[0]["article_id"] == mind_article_id
    assert rows[1]["source_space"] == "live"
    assert rows[1]["article_id"] == live_article_id
    assert rows[2]["event_type"] == "search_query"
    assert rows[2]["article_id"] is None
    assert rows[3]["article_id"] == live_article_id
    assert claim["source_space"] == "mind"


def test_event_dao_sql_stores_space_and_canonical_article_columns() -> None:
    connection = RecordingConnection()
    event = UserEventMessage(
        event_id="live-claim",
        event_type="feed_impression",
        user_id=7,
        source_space="live",
        article_id="L550e8400e29b41d4a716446655440000",
        event_ts=100,
    )

    assert claim_event_id(connection, event, source_space="live")
    record_search_query(connection, 7, "1 2", 101, source_space="live")
    record_click_event(
        connection,
        7,
        "recommendation_click",
        "L550e8400e29b41d4a716446655440000",
        None,
        None,
        "feed",
        102,
        [],
        source_space="live",
    )
    record_log_only_event(
        connection,
        7,
        "detail_view",
        "detail",
        "L550e8400e29b41d4a716446655440000",
        None,
        None,
        103,
        None,
        source_space="live",
    )

    claim_sql, claim_params = connection.cursor_value.executed[0]
    search_sql, _search_params = connection.cursor_value.executed[1]
    click_sql, click_params = connection.cursor_value.executed[2]
    log_sql, log_params = connection.cursor_value.executed[3]
    assert "source_space" in claim_sql and "live" in claim_params
    assert "source_space" in search_sql and "article_id" not in search_sql
    assert "article_id" in click_sql and click_params[1] == "live"
    assert click_params[4] == "L550e8400e29b41d4a716446655440000"
    assert "article_id" in log_sql and log_params[1] == "live"
    assert log_params[4] == "L550e8400e29b41d4a716446655440000"


def test_append_recent_query_rejects_profile_row_from_another_space_before_writing() -> None:
    connection = RecordingConnection()
    profile_row = {
        "user_id": 7,
        "source_space": "mind",
        "recent_queries_json": [],
        "behavior_score": 1.0,
    }

    with pytest.raises(ValueError, match="source_space"):
        append_recent_query(connection, profile_row, "1 2", 100, 1.0, source_space="live")

    assert connection.cursor_value.executed == []


def test_confirm_recent_query_rejects_profile_row_from_another_space_before_mutating() -> None:
    connection = RecordingConnection()
    profile_row = {
        "user_id": 7,
        "source_space": "mind",
        "recent_queries_json": [{"query_key": "1 2", "query_ts": 90}],
    }

    with pytest.raises(ValueError, match="source_space"):
        confirm_recent_query(connection, profile_row, "1 2", 100, source_space="live")

    assert connection.cursor_value.executed == []
    assert "confirmed_ts" not in profile_row["recent_queries_json"][0]


def test_click_update_rejects_profile_row_from_another_space_before_writing() -> None:
    connection = RecordingConnection()
    profile_row = {
        "user_id": 7,
        "source_space": "mind",
        "topic_weights_json": [],
        "recent_clicked_news_json": [],
        "behavior_score": 1.0,
    }

    with pytest.raises(ValueError, match="source_space"):
        apply_click_profile_update(
            connection,
            profile_row,
            "L550e8400e29b41d4a716446655440000",
            100,
            {},
            1.0,
            1.0,
            source_space="live",
        )

    assert connection.cursor_value.executed == []


@pytest.mark.parametrize("operation", ["append", "confirm", "click"])
def test_profile_mutation_fails_when_the_target_row_is_missing(operation: str) -> None:
    connection = RecordingConnection(rowcount=0)
    profile_row = {
        "user_id": 7,
        "source_space": "live",
        "topic_weights_json": [],
        "recent_clicked_news_json": [],
        "recent_queries_json": [{"query_key": "1 2", "query_ts": 90}],
        "behavior_score": 1.0,
    }

    with pytest.raises(LookupError, match="not found"):
        if operation == "append":
            append_recent_query(connection, profile_row, "3 4", 100, 1.0, source_space="live")
        elif operation == "confirm":
            confirm_recent_query(connection, profile_row, "1 2", 100, source_space="live")
        else:
            apply_click_profile_update(
                connection,
                profile_row,
                "L550e8400e29b41d4a716446655440000",
                100,
                {},
                1.0,
                1.0,
                source_space="live",
            )

    assert len(connection.cursor_value.executed) == 1
