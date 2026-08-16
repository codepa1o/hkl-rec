from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from math import exp, tanh
from typing import Literal

ProfileStatus = Literal["cold", "learning", "established"]


@dataclass(frozen=True, slots=True)
class ProfileSignalConfig:
    short_half_life_seconds: int
    long_half_life_seconds: int
    long_term_factor: float


@dataclass(frozen=True, slots=True)
class TopicProfileState:
    short_positive_score: float = 0.0
    short_negative_score: float = 0.0
    long_positive_score: float = 0.0
    long_negative_score: float = 0.0
    positive_evidence_count: int = 0
    negative_evidence_count: int = 0
    signal_counts: Mapping[str, int] = field(default_factory=dict)
    last_signal_type: str | None = None
    last_event_ts: int | None = None

    @property
    def short_net(self) -> float:
        return self.short_positive_score - self.short_negative_score

    @property
    def long_net(self) -> float:
        return self.long_positive_score - self.long_negative_score


def decayed_score(score: float, elapsed_seconds: int, half_life_seconds: int) -> float:
    if half_life_seconds <= 0:
        raise ValueError("half_life_seconds must be positive")
    return score * 2 ** (-max(elapsed_seconds, 0) / half_life_seconds)


def dwell_signal_strength(dwell_ms: int | None) -> float:
    if dwell_ms is None or dwell_ms < 10_000:
        return 0.0
    if dwell_ms < 30_000:
        return 0.25
    if dwell_ms < 120_000:
        return 0.50
    return 0.75


def event_signal_strength(event_type: str, *, dwell_ms: int | None = None) -> float:
    fixed_strengths = {
        "recommendation_click": 1.0,
        "search_result_click": 1.25,
        "upvote": 2.0,
        "downvote": -2.0,
    }
    if event_type == "dwell":
        return dwell_signal_strength(dwell_ms)
    return fixed_strengths.get(event_type, 0.0)


def topic_strengths_for_event(
    event_type: str,
    *,
    article_topic_ids: list[int] | set[int] | tuple[int, ...] = (),
    query_topic_ids: list[int] | set[int] | tuple[int, ...] = (),
    dwell_ms: int | None = None,
) -> dict[int, float]:
    signal = event_signal_strength(event_type, dwell_ms=dwell_ms)
    if signal == 0:
        return {}

    article_topics = {int(topic_id) for topic_id in article_topic_ids}
    strengths = {topic_id: signal for topic_id in article_topics}
    if event_type == "search_result_click":
        for topic_id in {int(value) for value in query_topic_ids} - article_topics:
            strengths[topic_id] = signal * 0.5
    return dict(sorted(strengths.items()))


def decayed_topic_state(
    state: TopicProfileState,
    *,
    now_ts: int,
    short_half_life_seconds: int,
    long_half_life_seconds: int,
) -> TopicProfileState:
    if state.last_event_ts is None:
        return state
    elapsed_seconds = max(now_ts - state.last_event_ts, 0)
    return replace(
        state,
        short_positive_score=decayed_score(
            state.short_positive_score,
            elapsed_seconds,
            short_half_life_seconds,
        ),
        short_negative_score=decayed_score(
            state.short_negative_score,
            elapsed_seconds,
            short_half_life_seconds,
        ),
        long_positive_score=decayed_score(
            state.long_positive_score,
            elapsed_seconds,
            long_half_life_seconds,
        ),
        long_negative_score=decayed_score(
            state.long_negative_score,
            elapsed_seconds,
            long_half_life_seconds,
        ),
    )


def project_topic_signal(
    state: TopicProfileState,
    *,
    signal: float,
    event_type: str,
    event_ts: int,
    short_half_life_seconds: int,
    long_half_life_seconds: int,
    long_term_factor: float,
) -> TopicProfileState | None:
    if state.last_event_ts is not None and event_ts < state.last_event_ts:
        return None
    if not 0 <= long_term_factor <= 1:
        raise ValueError("long_term_factor must be between zero and one")

    decayed = decayed_topic_state(
        state,
        now_ts=event_ts,
        short_half_life_seconds=short_half_life_seconds,
        long_half_life_seconds=long_half_life_seconds,
    )
    if signal == 0:
        return replace(decayed, last_event_ts=event_ts)

    positive_delta = max(signal, 0.0)
    negative_delta = max(-signal, 0.0)
    signal_counts = dict(decayed.signal_counts)
    signal_counts[event_type] = signal_counts.get(event_type, 0) + 1
    return replace(
        decayed,
        short_positive_score=decayed.short_positive_score + positive_delta,
        short_negative_score=decayed.short_negative_score + negative_delta,
        long_positive_score=(decayed.long_positive_score + positive_delta * long_term_factor),
        long_negative_score=(decayed.long_negative_score + negative_delta * long_term_factor),
        positive_evidence_count=(
            decayed.positive_evidence_count + (1 if positive_delta > 0 else 0)
        ),
        negative_evidence_count=(
            decayed.negative_evidence_count + (1 if negative_delta > 0 else 0)
        ),
        signal_counts=signal_counts,
        last_signal_type=event_type,
        last_event_ts=event_ts,
    )


def confidence_from_evidence(evidence_count: int) -> float:
    return 1.0 - exp(-max(evidence_count, 0) / 8.0)


def profile_status(confidence: float) -> ProfileStatus:
    if confidence < 0.25:
        return "cold"
    if confidence < 0.75:
        return "learning"
    return "established"


def combined_topic_score(state: TopicProfileState) -> float:
    return 0.70 * tanh(state.short_net) + 0.30 * tanh(state.long_net)
