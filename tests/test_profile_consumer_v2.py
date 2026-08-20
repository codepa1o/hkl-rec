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
        source_space="mind",
        article_id="N12",
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

    monkeypatch.setattr(consumer, "claim_event_id", lambda *args, **kwargs: True)
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

    monkeypatch.setattr(consumer, "claim_event_id", lambda *args, **kwargs: True)
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


def test_outbound_click_is_claimed_in_space_and_applied_as_log_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applier = make_applier(enabled=True)
    connection = FakeConnection()
    applier._connection_pool = FakePool(connection)
    calls: list[tuple[str, dict[str, Any]]] = []
    outbound = UserEventMessage(
        event_id="evt-outbound",
        event_type="outbound_click",
        user_id=7,
        source_space="live",
        article_id="L550e8400e29b41d4a716446655440000",
        event_ts=1_000,
    )

    def claim(*args: Any, **kwargs: Any) -> bool:
        calls.append(("claim", kwargs))
        return True

    def before_reset(*args: Any, **kwargs: Any) -> bool:
        calls.append(("reset", kwargs))
        return False

    monkeypatch.setattr(consumer, "claim_event_id", claim)
    monkeypatch.setattr(consumer, "profile_event_is_before_reset", before_reset)
    monkeypatch.setattr(consumer, "enqueue_outbox_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        applier,
        "_apply_log_only",
        lambda *args, **kwargs: calls.append(("log", kwargs)),
    )

    assert applier.apply_event(outbound) is True
    assert calls[0] == ("claim", {"source_space": "live"})
    assert calls[1][0] == "reset"
    assert calls[1][1]["source_space"] == "live"
    assert calls[2][0] == "log"
    assert connection.committed is True


def test_live_click_never_loads_mind_topics_and_persists_canonical_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applier = make_applier(enabled=True)
    calls: list[dict[str, Any]] = []
    live_event = UserEventMessage(
        event_id="evt-live-click",
        event_type="recommendation_click",
        user_id=7,
        source_space="live",
        article_id="L550e8400e29b41d4a716446655440000",
        event_ts=1_000,
    )
    monkeypatch.setattr(
        consumer,
        "load_news_topic_ids",
        lambda *args, **kwargs: pytest.fail("live events must not read MIND mappings"),
    )
    monkeypatch.setattr(
        consumer,
        "record_click_event",
        lambda *args, **kwargs: calls.append(kwargs),
    )

    applier._apply_recommendation_click(object(), live_event, project_profile=False)

    assert calls[0]["source_space"] == "live"
    assert calls[0]["article_id"] == live_event.article_id


def test_consumer_training_message_is_schema_v5_and_space_scoped() -> None:
    applier = make_applier(enabled=True)
    live_event = UserEventMessage(
        event_id="evt-live-training",
        event_type="feed_impression",
        user_id=7,
        source_space="live",
        article_id="L550e8400e29b41d4a716446655440000",
        event_ts=1_000,
    )

    training = applier._training_message(live_event)

    assert training is not None
    assert training.schema_version == 5
    assert training.source_space == "live"
    assert training.article_id == live_event.article_id
    assert training.partition_key == "live:7"


def test_duplicate_event_preserves_existing_legacy_training_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applier = make_applier(enabled=True)
    connection = FakeConnection()
    applier._connection_pool = FakePool(connection)
    legacy_training_row = {
        "schema_version": 4,
        "example_id": "evt-profile-v2",
        "user_id": 7,
        "news_id": "N12",
        "event_type": "feed_impression",
        "event_ts": 1_000,
    }
    monkeypatch.setattr(consumer, "claim_event_id", lambda *args, **kwargs: False)

    def existing(*args: Any, **kwargs: Any) -> bool:
        assert legacy_training_row["schema_version"] == 4
        assert kwargs["event_id"] == legacy_training_row["example_id"]
        return True

    monkeypatch.setattr(
        consumer,
        "outbox_message_exists",
        existing,
        raising=False,
    )
    monkeypatch.setattr(
        consumer,
        "enqueue_outbox_message",
        lambda *args, **kwargs: pytest.fail("existing v4 training row must not be rewritten"),
    )

    assert applier.apply_event(event("feed_impression")) is False
    assert connection.committed is True


def test_duplicate_event_backfills_missing_training_outbox_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applier = make_applier(enabled=True)
    connection = FakeConnection()
    applier._connection_pool = FakePool(connection)
    existence = iter([False, True])
    enqueued: list[dict[str, Any]] = []
    monkeypatch.setattr(consumer, "claim_event_id", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        consumer,
        "outbox_message_exists",
        lambda *args, **kwargs: next(existence),
        raising=False,
    )
    monkeypatch.setattr(
        consumer,
        "enqueue_outbox_message",
        lambda *args, **kwargs: enqueued.append(kwargs),
    )

    assert applier.apply_event(event("feed_impression")) is False
    assert applier.apply_event(event("feed_impression")) is False
    assert len(enqueued) == 1
    assert '"schema_version":5' in enqueued[0]["payload_json"]
