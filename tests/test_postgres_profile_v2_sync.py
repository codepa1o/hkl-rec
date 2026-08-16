from __future__ import annotations

from typing import Any

import pytest

from backend.app.config import Settings
from backend.app.repositories import postgres
from backend.app.repositories.postgres import PostgresRuntimeRepository
from backend.app.schemas.event_track import EventTrackRequest
from backend.app.schemas.profile import ProfileResponse, ProfileTermLayer


class FakeConnection:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def begin(self) -> None:
        return None

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        return None


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> FakeConnection:
        return self.connection


def _cold_profile(user_id: int) -> ProfileResponse:
    return ProfileResponse(
        user_id=user_id,
        status="cold",
        confidence=0.0,
        evidence_count=0,
        short_term=ProfileTermLayer(),
        long_term=ProfileTermLayer(),
    )


def test_profile_read_loads_v2_for_requested_user(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = object.__new__(PostgresRuntimeRepository)
    repository._settings = Settings(database_url="postgresql://example")
    connection = FakeConnection()
    repository._connection_pool = FakePool(connection)
    calls: list[tuple[FakeConnection, int, int]] = []

    def fake_load(
        connection_arg: FakeConnection,
        *,
        user_id: int,
        now_ts: int,
        config: Any,
    ) -> ProfileResponse:
        calls.append((connection_arg, user_id, now_ts))
        return _cold_profile(user_id)

    monkeypatch.setattr(postgres.time, "time", lambda: 1234)
    monkeypatch.setattr(postgres, "load_profile_v2", fake_load)

    profile = repository.get_profile(7004)

    assert profile.user_id == 7004
    assert calls == [(connection, 7004, 1234)]
    assert connection.committed is False


def test_profile_reset_commits_seed_restore_and_returns_fresh_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = object.__new__(PostgresRuntimeRepository)
    repository._settings = Settings(database_url="postgresql://example")
    connection = FakeConnection()
    repository._connection_pool = FakePool(connection)
    resets: list[tuple[FakeConnection, int, int]] = []

    monkeypatch.setattr(postgres.time, "time", lambda: 1234)
    monkeypatch.setattr(
        postgres,
        "reset_profile_projections",
        lambda connection_arg, *, user_id, reset_ts: resets.append(
            (connection_arg, user_id, reset_ts)
        ),
    )
    monkeypatch.setattr(
        postgres,
        "load_profile_v2",
        lambda connection_arg, *, user_id, now_ts, config: _cold_profile(user_id),
    )

    profile = repository.reset_profile(7004)

    assert profile.status == "cold"
    assert resets == [(connection, 7004, 1234)]
    assert connection.committed is True
    assert connection.rolled_back is False


def test_profile_reset_rolls_back_when_seed_restore_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = object.__new__(PostgresRuntimeRepository)
    repository._settings = Settings(database_url="postgresql://example")
    connection = FakeConnection()
    repository._connection_pool = FakePool(connection)

    def fail_reset(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("seed unavailable")

    monkeypatch.setattr(postgres, "reset_profile_projections", fail_reset)

    with pytest.raises(RuntimeError, match="seed unavailable"):
        repository.reset_profile(7004)

    assert connection.committed is False
    assert connection.rolled_back is True


def test_sync_upvote_projects_v2_in_the_direct_database_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = object.__new__(PostgresRuntimeRepository)
    repository._settings = Settings(
        database_url="postgresql://example",
        event_mode="sync_postgres",
        profile_v2_enabled=True,
    )
    connection = FakeConnection()
    repository._connection_pool = FakePool(connection)
    repository._load_sponsored_event_attribution = lambda **kwargs: None
    repository._enqueue_raw_event = lambda *args, **kwargs: None
    projected: list[tuple[Any, dict[int, float]]] = []
    repository._project_profile_v2 = lambda conn, evt, strengths: projected.append(
        (evt, strengths)
    )

    monkeypatch.setattr(postgres, "claim_event_id", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        postgres,
        "profile_event_is_before_reset",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(postgres, "fetch_profile_row", lambda *args, **kwargs: {})
    monkeypatch.setattr(postgres, "load_answer_topic_ids", lambda *args, **kwargs: [10, 20])
    monkeypatch.setattr(postgres, "record_click_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(postgres, "record_sponsored_click", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        postgres,
        "apply_click_profile_update",
        lambda *args, **kwargs: {"behavior_score": 5.0},
    )

    response = repository.record_tracked_event(
        EventTrackRequest(
            event_id="sync-upvote-v2",
            user_id=7,
            event_type="upvote",
            surface="feed",
            article_id=12,
        )
    )

    assert response.profile_updated is True
    assert len(projected) == 1
    assert projected[0][0].event_type == "upvote"
    assert projected[0][1] == {10: 2.0, 20: 2.0}
    assert connection.committed is True
    assert connection.rolled_back is False


def test_sync_pre_reset_upvote_records_fact_without_mutating_v1_or_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = object.__new__(PostgresRuntimeRepository)
    repository._settings = Settings(
        database_url="postgresql://example",
        event_mode="sync_postgres",
        profile_v2_enabled=True,
    )
    connection = FakeConnection()
    repository._connection_pool = FakePool(connection)
    repository._load_sponsored_event_attribution = lambda **kwargs: None
    repository._enqueue_raw_event = lambda *args, **kwargs: None
    repository._project_profile_v2 = lambda *args, **kwargs: pytest.fail(
        "pre-reset event must not update V2"
    )

    monkeypatch.setattr(postgres, "claim_event_id", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        postgres,
        "profile_event_is_before_reset",
        lambda *args, **kwargs: True,
        raising=False,
    )
    monkeypatch.setattr(postgres, "fetch_profile_row", lambda *args, **kwargs: {})
    monkeypatch.setattr(postgres, "load_answer_topic_ids", lambda *args, **kwargs: [10])
    monkeypatch.setattr(postgres, "record_click_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(postgres, "record_sponsored_click", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        postgres,
        "apply_click_profile_update",
        lambda *args, **kwargs: pytest.fail("pre-reset event must not update V1"),
    )

    response = repository.record_tracked_event(
        EventTrackRequest(
            event_id="sync-upvote-before-reset",
            user_id=7,
            event_type="upvote",
            surface="feed",
            article_id=12,
            debug=True,
            replay_event_ts=500,
        )
    )

    assert response.profile_updated is False
    assert response.behavior_score is None
    assert connection.committed is True
    assert connection.rolled_back is False
