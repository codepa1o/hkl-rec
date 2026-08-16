from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

import pytest

from backend.app.config import Settings
from backend.app.repositories import postgres
from backend.app.repositories.postgres import (
    PostgresRuntimeRepository,
    _apply_profile_v2_boost,
    _profile_v2_recall_scores,
)
from backend.app.schemas.feed import FeedItemScores


class SavepointCursor(AbstractContextManager["SavepointCursor"]):
    def __init__(self, statements: list[str]) -> None:
        self.statements = statements

    def __enter__(self) -> SavepointCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        self.statements.append(" ".join(query.split()))


class SavepointConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def cursor(self) -> SavepointCursor:
        return SavepointCursor(self.statements)


def test_default_arm_score_is_unchanged_and_has_no_v2_debug_score() -> None:
    final_score, profile_v2_score = _apply_profile_v2_boost(
        experiment_arm="default",
        final_score=0.625,
        topic_ids={10, 20},
        topic_scores={10: 0.8, 20: -0.3},
        boost=0.1,
    )

    assert final_score == 0.625
    assert profile_v2_score is None


def test_default_scores_serialization_omits_profile_v2_field() -> None:
    payload = FeedItemScores(
        base_recall_score=0.1,
        personalized_topic_score=0.2,
        default_topic_score=0.3,
        topic_match_score=0.4,
        query_recall_boost=0.0,
        final_score=0.5,
    ).model_dump()

    assert "profile_v2_score" not in payload


def test_profile_v2_arm_adds_signed_topic_boost() -> None:
    final_score, profile_v2_score = _apply_profile_v2_boost(
        experiment_arm="profile_v2",
        final_score=0.625,
        topic_ids={10, 20},
        topic_scores={10: 0.8, 20: -0.3},
        boost=0.1,
    )

    assert profile_v2_score == 0.5
    assert final_score == 0.675


def test_empty_profile_v2_keeps_baseline_score_exactly() -> None:
    final_score, profile_v2_score = _apply_profile_v2_boost(
        experiment_arm="profile_v2",
        final_score=0.625,
        topic_ids={10},
        topic_scores={},
        boost=0.1,
    )

    assert final_score == 0.625
    assert profile_v2_score == 0.0


def test_only_top_positive_profile_topics_open_recall() -> None:
    scores = {topic_id: float(topic_id) / 100 for topic_id in range(1, 13)}
    scores[99] = -0.9

    recall_scores = _profile_v2_recall_scores(scores)

    assert list(recall_scores) == [12, 11, 10, 9, 8, 7, 6, 5, 4, 3]
    assert 99 not in recall_scores


def test_positive_profile_v2_topic_adds_a_dedicated_recall_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = object.__new__(PostgresRuntimeRepository)
    repository._settings = Settings(database_url="postgresql://example")

    def fake_topic_recall(
        connection: Any,
        topic_ids: list[int],
        limit: int,
        *,
        as_of_ts: int | None,
    ) -> list[dict[str, Any]]:
        if topic_ids == [12]:
            return [{"answer_id": 501, "hot_score": 8.0}]
        return []

    monkeypatch.setattr(postgres, "load_answer_ids_for_topics", fake_topic_recall)
    monkeypatch.setattr(postgres, "load_hot_fallback_rows", lambda *args, **kwargs: [])

    candidates = repository._load_feed_candidates(
        connection=object(),
        topic_weight_map={},
        query_topic_scores={},
        profile_v2_topic_scores={12: 0.8},
        page_size=1,
        user_id=7004,
        use_als=False,
        as_of_ts=None,
    )

    assert candidates[501]["sources"] == {"profile_v2_topic"}
    assert candidates[501]["is_fallback"] is False


def test_profile_v2_read_failure_rolls_back_to_savepoint_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = object.__new__(PostgresRuntimeRepository)
    repository._settings = Settings(
        database_url="postgresql://example",
        profile_v2_enabled=True,
    )
    connection = SavepointConnection()

    def fail_read(*args: Any, **kwargs: Any) -> dict[int, float]:
        raise RuntimeError("profile projection query failed")

    monkeypatch.setattr(postgres, "load_profile_v2_topic_scores", fail_read)

    scores = repository._load_profile_v2_scores_with_fallback(
        connection,
        user_id=7004,
        now_ts=1234,
    )

    assert scores == {}
    assert connection.statements == [
        "SAVEPOINT profile_v2_read",
        "ROLLBACK TO SAVEPOINT profile_v2_read",
        "RELEASE SAVEPOINT profile_v2_read",
    ]


def test_profile_v2_read_success_releases_savepoint(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = object.__new__(PostgresRuntimeRepository)
    repository._settings = Settings(
        database_url="postgresql://example",
        profile_v2_enabled=True,
    )
    connection = SavepointConnection()
    monkeypatch.setattr(
        postgres,
        "load_profile_v2_topic_scores",
        lambda *args, **kwargs: {10: 0.75},
    )

    scores = repository._load_profile_v2_scores_with_fallback(
        connection,
        user_id=7004,
        now_ts=1234,
    )

    assert scores == {10: 0.75}
    assert connection.statements == [
        "SAVEPOINT profile_v2_read",
        "RELEASE SAVEPOINT profile_v2_read",
    ]
