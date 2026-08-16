from __future__ import annotations

import json
from contextlib import AbstractContextManager
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.app.profiles.signals import ProfileSignalConfig
from backend.app.repositories.profile_v2_dao import (
    apply_profile_v2_event,
    load_profile_v2,
    reset_profile_projections,
)


class FakeCursor(AbstractContextManager["FakeCursor"]):
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self._one: dict[str, Any] | None = None
        self._many: list[dict[str, Any]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        normalized = " ".join(query.split())
        self.connection.statements.append((normalized, params))
        self._one = None
        self._many = []

        if "FROM user_profile" in normalized and normalized.startswith("SELECT"):
            self._one = deepcopy(self.connection.profile)
            return
        if (
            "FROM user_topic_profile" in normalized
            and "topic_id = %s" in normalized
            and normalized.startswith("SELECT")
        ):
            self._one = deepcopy(self.connection.topic_rows.get((int(params[0]), int(params[1]))))
            return
        if normalized.startswith("INSERT INTO user_topic_profile"):
            (
                user_id,
                topic_id,
                short_positive,
                short_negative,
                long_positive,
                long_negative,
                positive_count,
                negative_count,
                signal_counts,
                last_signal_type,
                last_event_ts,
            ) = params
            self.connection.topic_rows[(int(user_id), int(topic_id))] = {
                "user_id": int(user_id),
                "topic_id": int(topic_id),
                "short_positive_score": float(short_positive),
                "short_negative_score": float(short_negative),
                "long_positive_score": float(long_positive),
                "long_negative_score": float(long_negative),
                "positive_evidence_count": int(positive_count),
                "negative_evidence_count": int(negative_count),
                "evidence_counts_json": signal_counts,
                "last_signal_type": last_signal_type,
                "last_event_ts": int(last_event_ts),
            }
            return
        if normalized.startswith("UPDATE user_profile SET profile_v2_evidence_count"):
            event_ts, user_id = params
            assert int(user_id) == int(self.connection.profile["user_id"])
            self.connection.profile["profile_v2_evidence_count"] += 1
            self.connection.profile["profile_v2_last_event_ts"] = int(event_ts)
            self.connection.profile["profile_v2_updated_at"] = datetime.now(UTC)
            return
        if (
            "FROM user_topic_profile AS profile" in normalized
            and normalized.startswith("SELECT")
        ):
            user_id = int(params[0])
            for (row_user_id, topic_id), row in self.connection.topic_rows.items():
                if row_user_id != user_id:
                    continue
                self._many.append(
                    {
                        **deepcopy(row),
                        "display_name": self.connection.topic_names.get(topic_id),
                    }
                )
            return
        if "FROM system_profile_seed" in normalized and normalized.startswith("SELECT"):
            seed_key = str(params[0])
            seed = self.connection.seeds.get(seed_key)
            self._one = deepcopy(seed) if seed is not None else None
            return
        if normalized.startswith("UPDATE user_profile SET topic_weights_json"):
            (
                topic_weights,
                recent_clicks,
                recent_queries,
                behavior_score,
                reset_ts,
                user_id,
            ) = params
            assert int(user_id) == int(self.connection.profile["user_id"])
            self.connection.profile.update(
                {
                    "topic_weights_json": json.loads(topic_weights),
                    "recent_clicked_news_json": json.loads(recent_clicks),
                    "recent_queries_json": json.loads(recent_queries),
                    "behavior_score": float(behavior_score),
                    "last_event_ts": None,
                    "profile_v2_evidence_count": 0,
                    "profile_v2_last_event_ts": None,
                    "profile_reset_before_ts": int(reset_ts),
                    "profile_v2_updated_at": datetime.now(UTC),
                }
            )
            return
        if normalized.startswith("DELETE FROM user_topic_profile"):
            user_id = int(params[0])
            self.connection.topic_rows = {
                key: row for key, row in self.connection.topic_rows.items() if key[0] != user_id
            }
            return
        raise AssertionError(f"unexpected SQL: {normalized}")

    def fetchone(self) -> dict[str, Any] | None:
        return self._one

    def fetchall(self) -> list[dict[str, Any]]:
        return self._many


class FakeConnection:
    def __init__(self) -> None:
        self.profile: dict[str, Any] = {
            "user_id": 7,
            "cold_start_seed_key": "cold_start_default",
            "topic_weights_json": [{"topic_id": 10, "weight": 0.6}],
            "recent_clicked_news_json": [{"news_id": "N12", "click_ts": 90}],
            "recent_queries_json": [{"query_key": "sports", "query_ts": 80}],
            "behavior_score": 4.0,
            "profile_v2_evidence_count": 0,
            "profile_v2_last_event_ts": None,
            "profile_reset_before_ts": None,
            "profile_v2_updated_at": None,
        }
        self.topic_rows: dict[tuple[int, int], dict[str, Any]] = {}
        self.topic_names = {10: "Sports", 20: "Finance", 30: "Travel"}
        self.seeds: dict[str, dict[str, Any]] = {
            "cold_start_default": {
                "topic_weights_json": [{"topic_id": 30, "weight": 0.5}],
                "recent_clicked_news_json": [],
                "recent_queries_json": [],
                "behavior_score": 0.0,
            }
        }
        self.statements: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


CONFIG = ProfileSignalConfig(
    short_half_life_seconds=100,
    long_half_life_seconds=200,
    long_term_factor=0.25,
)


def test_multi_topic_event_increments_user_evidence_once() -> None:
    connection = FakeConnection()

    updated = apply_profile_v2_event(
        connection,
        user_id=7,
        event_type="upvote",
        event_ts=1_000,
        topic_strengths={10: 2.0, 20: 2.0},
        config=CONFIG,
    )

    assert updated is True
    assert connection.profile["profile_v2_evidence_count"] == 1
    assert connection.topic_rows[(7, 10)]["positive_evidence_count"] == 1
    assert connection.topic_rows[(7, 20)]["positive_evidence_count"] == 1
    assert connection.topic_rows[(7, 10)]["long_positive_score"] == 0.5


def test_pre_reset_and_out_of_order_events_do_not_mutate_projection() -> None:
    connection = FakeConnection()
    connection.profile["profile_reset_before_ts"] = 500

    assert (
        apply_profile_v2_event(
            connection,
            user_id=7,
            event_type="upvote",
            event_ts=500,
            topic_strengths={10: 2.0},
            config=CONFIG,
        )
        is False
    )
    assert connection.topic_rows == {}

    connection.profile["profile_reset_before_ts"] = None
    connection.topic_rows[(7, 10)] = {
        "user_id": 7,
        "topic_id": 10,
        "short_positive_score": 1.0,
        "short_negative_score": 0.0,
        "long_positive_score": 0.25,
        "long_negative_score": 0.0,
        "positive_evidence_count": 1,
        "negative_evidence_count": 0,
        "evidence_counts_json": {"recommendation_click": 1},
        "last_signal_type": "recommendation_click",
        "last_event_ts": 900,
    }
    before = deepcopy(connection.topic_rows)

    assert (
        apply_profile_v2_event(
            connection,
            user_id=7,
            event_type="recommendation_click",
            event_ts=899,
            topic_strengths={10: 1.0},
            config=CONFIG,
        )
        is False
    )
    assert connection.topic_rows == before
    assert connection.profile["profile_v2_evidence_count"] == 0


def test_zero_strength_does_not_create_evidence_or_topic_rows() -> None:
    connection = FakeConnection()

    assert (
        apply_profile_v2_event(
            connection,
            user_id=7,
            event_type="dwell",
            event_ts=1_000,
            topic_strengths={10: 0.0},
            config=CONFIG,
        )
        is False
    )
    assert connection.topic_rows == {}
    assert connection.profile["profile_v2_evidence_count"] == 0


def test_read_applies_decay_filters_small_scores_and_never_writes() -> None:
    connection = FakeConnection()
    connection.profile["profile_v2_evidence_count"] = 12
    connection.profile["profile_v2_updated_at"] = datetime(2026, 8, 16, tzinfo=UTC)
    connection.topic_rows = {
        (7, 10): {
            "user_id": 7,
            "topic_id": 10,
            "short_positive_score": 4.0,
            "short_negative_score": 0.0,
            "long_positive_score": 1.0,
            "long_negative_score": 0.0,
            "positive_evidence_count": 2,
            "negative_evidence_count": 0,
            "evidence_counts_json": {"upvote": 2},
            "last_signal_type": "upvote",
            "last_event_ts": 100,
        },
        (7, 20): {
            "user_id": 7,
            "topic_id": 20,
            "short_positive_score": 0.0,
            "short_negative_score": 2.0,
            "long_positive_score": 0.0,
            "long_negative_score": 2.0,
            "positive_evidence_count": 0,
            "negative_evidence_count": 1,
            "evidence_counts_json": {"downvote": 1},
            "last_signal_type": "downvote",
            "last_event_ts": 100,
        },
        (7, 30): {
            "user_id": 7,
            "topic_id": 30,
            "short_positive_score": 0.009,
            "short_negative_score": 0.0,
            "long_positive_score": 0.009,
            "long_negative_score": 0.0,
            "positive_evidence_count": 1,
            "negative_evidence_count": 0,
            "evidence_counts_json": {"dwell": 1},
            "last_signal_type": "dwell",
            "last_event_ts": 200,
        },
    }

    response = load_profile_v2(connection, user_id=7, now_ts=200, config=CONFIG)

    assert response.user_id == 7
    assert response.profile_version == "v2"
    assert response.status == "established"
    assert response.evidence_count == 12
    assert response.short_term.interests[0].topic_id == 10
    assert response.short_term.interests[0].score == pytest.approx(2.0)
    assert response.short_term.reduced_topics[0].topic_id == 20
    assert response.long_term.interests[0].topic_id == 10
    assert response.long_term.reduced_topics[0].topic_id == 20
    assert all(item.topic_id != 30 for item in response.short_term.interests)
    assert response.recent_clicked_news[0].article_id == 12
    assert response.recent_queries[0].query_key == "sports"
    assert response.last_updated_at == datetime(2026, 8, 16, tzinfo=UTC)
    assert not any(
        statement.startswith(("INSERT", "UPDATE", "DELETE"))
        for statement, _params in connection.statements
    )


def test_reset_restores_v1_seed_and_clears_only_v2_projection() -> None:
    connection = FakeConnection()
    connection.topic_rows[(7, 10)] = {"topic_id": 10}
    connection.topic_rows[(99, 20)] = {"topic_id": 20}

    reset_profile_projections(connection, user_id=7, reset_ts=2_000)

    assert connection.profile["topic_weights_json"] == [{"topic_id": 30, "weight": 0.5}]
    assert connection.profile["recent_clicked_news_json"] == []
    assert connection.profile["recent_queries_json"] == []
    assert connection.profile["behavior_score"] == 0.0
    assert connection.profile["profile_v2_evidence_count"] == 0
    assert connection.profile["profile_reset_before_ts"] == 2_000
    assert (7, 10) not in connection.topic_rows
    assert (99, 20) in connection.topic_rows
    assert not any("user_event" in statement for statement, _params in connection.statements)


def test_reset_fails_when_the_configured_seed_is_missing() -> None:
    connection = FakeConnection()
    connection.seeds.clear()

    with pytest.raises(RuntimeError, match="cold_start_default"):
        reset_profile_projections(connection, user_id=7, reset_ts=2_000)
