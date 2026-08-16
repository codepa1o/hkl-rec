from __future__ import annotations

import math

import pytest

from backend.app.profiles.signals import (
    TopicProfileState,
    combined_topic_score,
    confidence_from_evidence,
    decayed_topic_state,
    dwell_signal_strength,
    event_signal_strength,
    profile_status,
    project_topic_signal,
)


def test_event_signal_strengths_match_the_mvp_contract() -> None:
    assert event_signal_strength("recommendation_click") == 1.0
    assert event_signal_strength("search_result_click") == 1.25
    assert event_signal_strength("upvote") == 2.0
    assert event_signal_strength("downvote") == -2.0
    assert event_signal_strength("feed_impression") == 0.0
    assert event_signal_strength("detail_view") == 0.0
    assert event_signal_strength("share") == 0.0


@pytest.mark.parametrize(
    ("dwell_ms", "expected"),
    [
        (None, 0.0),
        (0, 0.0),
        (9_999, 0.0),
        (10_000, 0.25),
        (29_999, 0.25),
        (30_000, 0.50),
        (119_999, 0.50),
        (120_000, 0.75),
    ],
)
def test_dwell_signal_boundaries(dwell_ms: int | None, expected: float) -> None:
    assert dwell_signal_strength(dwell_ms) == expected
    assert event_signal_strength("dwell", dwell_ms=dwell_ms) == expected


def test_positive_and_negative_components_are_projected_independently() -> None:
    positive = project_topic_signal(
        TopicProfileState(),
        signal=2.0,
        event_type="upvote",
        event_ts=100,
        short_half_life_seconds=21_600,
        long_half_life_seconds=2_592_000,
        long_term_factor=0.25,
    )
    assert positive is not None
    assert positive.short_positive_score == 2.0
    assert positive.short_negative_score == 0.0
    assert positive.long_positive_score == 0.5
    assert positive.long_negative_score == 0.0
    assert positive.positive_evidence_count == 1
    assert positive.negative_evidence_count == 0
    assert positive.signal_counts == {"upvote": 1}

    negative = project_topic_signal(
        positive,
        signal=-2.0,
        event_type="downvote",
        event_ts=100,
        short_half_life_seconds=21_600,
        long_half_life_seconds=2_592_000,
        long_term_factor=0.25,
    )
    assert negative is not None
    assert negative.short_positive_score == 2.0
    assert negative.short_negative_score == 2.0
    assert negative.long_positive_score == 0.5
    assert negative.long_negative_score == 0.5
    assert negative.positive_evidence_count == 1
    assert negative.negative_evidence_count == 1
    assert negative.signal_counts == {"upvote": 1, "downvote": 1}


def test_short_and_long_scores_use_their_own_half_lives() -> None:
    state = TopicProfileState(
        short_positive_score=8.0,
        short_negative_score=4.0,
        long_positive_score=8.0,
        long_negative_score=4.0,
        last_event_ts=100,
    )

    projected = project_topic_signal(
        state,
        signal=1.0,
        event_type="recommendation_click",
        event_ts=200,
        short_half_life_seconds=100,
        long_half_life_seconds=200,
        long_term_factor=0.25,
    )

    assert projected is not None
    assert projected.short_positive_score == pytest.approx(5.0)
    assert projected.short_negative_score == pytest.approx(2.0)
    assert projected.long_positive_score == pytest.approx(8.0 * 2 ** -0.5 + 0.25)
    assert projected.long_negative_score == pytest.approx(4.0 * 2 ** -0.5)


def test_zero_signal_decays_existing_state_without_adding_evidence() -> None:
    state = TopicProfileState(
        short_positive_score=2.0,
        long_positive_score=2.0,
        positive_evidence_count=3,
        signal_counts={"upvote": 3},
        last_signal_type="upvote",
        last_event_ts=100,
    )

    projected = project_topic_signal(
        state,
        signal=0.0,
        event_type="feed_impression",
        event_ts=200,
        short_half_life_seconds=100,
        long_half_life_seconds=200,
        long_term_factor=0.25,
    )

    assert projected is not None
    assert projected.short_positive_score == pytest.approx(1.0)
    assert projected.long_positive_score == pytest.approx(2.0 * 2 ** -0.5)
    assert projected.positive_evidence_count == 3
    assert projected.signal_counts == {"upvote": 3}
    assert projected.last_signal_type == "upvote"
    assert projected.last_event_ts == 200


def test_older_event_is_rejected_without_mutating_the_projection() -> None:
    state = TopicProfileState(short_positive_score=1.0, last_event_ts=200)

    assert (
        project_topic_signal(
            state,
            signal=1.0,
            event_type="recommendation_click",
            event_ts=199,
            short_half_life_seconds=21_600,
            long_half_life_seconds=2_592_000,
            long_term_factor=0.25,
        )
        is None
    )


def test_read_time_decay_does_not_change_evidence_metadata() -> None:
    state = TopicProfileState(
        short_positive_score=4.0,
        long_negative_score=2.0,
        positive_evidence_count=2,
        negative_evidence_count=1,
        signal_counts={"recommendation_click": 2, "downvote": 1},
        last_signal_type="downvote",
        last_event_ts=100,
    )

    decayed = decayed_topic_state(
        state,
        now_ts=200,
        short_half_life_seconds=100,
        long_half_life_seconds=200,
    )

    assert decayed.short_positive_score == pytest.approx(2.0)
    assert decayed.long_negative_score == pytest.approx(2.0 * 2 ** -0.5)
    assert decayed.positive_evidence_count == 2
    assert decayed.negative_evidence_count == 1
    assert decayed.signal_counts == state.signal_counts
    assert decayed.last_signal_type == "downvote"
    assert decayed.last_event_ts == 100


def test_confidence_status_and_combined_score_are_stable() -> None:
    assert confidence_from_evidence(0) == 0.0
    assert confidence_from_evidence(-10) == 0.0
    assert profile_status(confidence_from_evidence(1)) == "cold"
    assert profile_status(confidence_from_evidence(8)) == "learning"
    assert profile_status(confidence_from_evidence(12)) == "established"

    state = TopicProfileState(
        short_positive_score=2.0,
        short_negative_score=0.5,
        long_positive_score=1.0,
        long_negative_score=0.25,
    )
    expected = 0.70 * math.tanh(1.5) + 0.30 * math.tanh(0.75)
    assert combined_topic_score(state) == pytest.approx(expected)
