from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from backend.app.config import Settings
from backend.app.events import consumer
from backend.app.events.consumer import ProfileEventApplier
from backend.app.events.schema import UserEventMessage
from backend.app.repositories.profile_v2_dao import ProfileProjectionOutcome


@dataclass
class FakeMetric:
    values: list[tuple[tuple[tuple[str, str], ...], float]]
    labels_value: tuple[tuple[str, str], ...] = ()

    def labels(self, **labels: str) -> FakeMetric:
        return FakeMetric(self.values, tuple(sorted(labels.items())))

    def inc(self, amount: float = 1.0) -> None:
        self.values.append((self.labels_value, amount))

    def observe(self, value: float) -> None:
        self.values.append((self.labels_value, value))


class FakeConnection:
    def __init__(self) -> None:
        self.began = False
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def begin(self) -> None:
        self.began = True

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> FakeConnection:
        return self.connection


def make_applier(*, enabled: bool) -> ProfileEventApplier:
    applier = object.__new__(ProfileEventApplier)
    applier._settings = Settings(
        database_url="postgresql://example",
        profile_v2_enabled=enabled,
    )
    return applier


def event(event_type: str = "recommendation_click") -> UserEventMessage:
    return UserEventMessage(
        event_id="evt-profile-v2",
        event_type=event_type,
        user_id=7,
        news_id="N12",
        query_key="sports" if event_type == "search_result_click" else None,
        event_ts=1_000,
        dwell_ms=30_000 if event_type == "dwell" else None,
    )


def test_projection_flag_skips_the_v2_dao(monkeypatch: pytest.MonkeyPatch) -> None:
    applier = make_applier(enabled=False)
    monkeypatch.setattr(
        consumer,
        "apply_profile_v2_event_with_outcome",
        lambda *args, **kwargs: pytest.fail("V2 DAO should be disabled"),
    )

    assert applier._project_profile_v2(object(), event(), {10: 1.0}) is False


def test_projection_records_update_and_late_event_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applier = make_applier(enabled=True)
    calls: list[dict[str, Any]] = []
    updates: list[tuple[tuple[tuple[str, str], ...], float]] = []
    late: list[tuple[tuple[tuple[str, str], ...], float]] = []
    duration: list[tuple[tuple[tuple[str, str], ...], float]] = []

    def apply(*args: Any, **kwargs: Any) -> ProfileProjectionOutcome:
        calls.append(kwargs)
        return ProfileProjectionOutcome(
            updated=True,
            reason=None,
            updated_topic_count=1,
            late_topic_count=1,
        )

    monkeypatch.setattr(consumer, "apply_profile_v2_event_with_outcome", apply)
    monkeypatch.setattr(consumer, "PROFILE_V2_PROJECTION_UPDATES", FakeMetric(updates))
    monkeypatch.setattr(consumer, "PROFILE_V2_LATE_EVENTS", FakeMetric(late))
    monkeypatch.setattr(consumer, "PROFILE_V2_PROJECTION_DURATION", FakeMetric(duration))

    assert applier._project_profile_v2(object(), event("upvote"), {10: 2.0}) is True
    assert calls[0]["event_type"] == "upvote"
    assert calls[0]["topic_strengths"] == {10: 2.0}
    assert updates == [((("event_type", "upvote"),), 1.0)]
    assert late == [((("reason", "out_of_order"),), 1.0)]
    assert len(duration) == 1
    assert duration[0][1] >= 0


def test_pre_reset_event_is_recorded_but_v1_projection_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applier = make_applier(enabled=True)
    connection = FakeConnection()
    applier._connection_pool = FakePool(connection)
    project_flags: list[bool] = []
    late: list[tuple[tuple[tuple[str, str], ...], float]] = []

    monkeypatch.setattr(consumer, "claim_event_id", lambda *args: True)
    monkeypatch.setattr(consumer, "profile_event_is_before_reset", lambda *args, **kwargs: True)
    monkeypatch.setattr(consumer, "enqueue_outbox_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(consumer, "PROFILE_V2_LATE_EVENTS", FakeMetric(late))
    monkeypatch.setattr(
        applier,
        "_apply_recommendation_click",
        lambda *args, project_profile: project_flags.append(project_profile),
    )

    assert applier.apply_event(event()) is True
    assert project_flags == [False]
    assert late == [((("reason", "pre_reset"),), 1.0)]
    assert connection.committed is True
    assert connection.rolled_back is False


def test_v2_projection_failure_rolls_back_the_whole_event_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applier = make_applier(enabled=True)
    connection = FakeConnection()
    applier._connection_pool = FakePool(connection)

    monkeypatch.setattr(consumer, "claim_event_id", lambda *args: True)
    monkeypatch.setattr(consumer, "profile_event_is_before_reset", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        applier,
        "_apply_recommendation_click",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("V2 UPSERT failed")),
    )

    with pytest.raises(RuntimeError, match="V2 UPSERT failed"):
        applier.apply_event(event())

    assert connection.began is True
    assert connection.committed is False
    assert connection.rolled_back is True
    assert connection.closed is True
