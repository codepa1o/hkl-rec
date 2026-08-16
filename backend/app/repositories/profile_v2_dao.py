from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from backend.app.config import Settings
from backend.app.profiles.signals import (
    ProfileSignalConfig,
    TopicProfileState,
    confidence_from_evidence,
    decayed_topic_state,
    profile_status,
    project_topic_signal,
)
from backend.app.repositories._utils import json_text, parse_json, parse_recent_queries
from backend.app.schemas.profile import (
    ProfileRecentClick,
    ProfileResponse,
    ProfileTermLayer,
    ProfileTopicEvidence,
)

ProfileProjectionSkipReason = Literal["no_signal", "pre_reset", "out_of_order"]


@dataclass(frozen=True, slots=True)
class ProfileProjectionOutcome:
    updated: bool
    reason: ProfileProjectionSkipReason | None
    updated_topic_count: int
    late_topic_count: int


def profile_signal_config(settings: Settings) -> ProfileSignalConfig:
    return ProfileSignalConfig(
        short_half_life_seconds=settings.profile_v2_short_half_life_seconds,
        long_half_life_seconds=settings.profile_v2_long_half_life_seconds,
        long_term_factor=settings.profile_v2_long_term_factor,
    )


def fetch_profile_v2_user_state(
    connection: Any,
    *,
    user_id: int,
    for_update: bool = False,
) -> dict[str, Any]:
    lock_clause = " FOR UPDATE" if for_update else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
              user_id,
              cold_start_seed_key,
              topic_weights_json,
              recent_clicked_news_json,
              recent_queries_json,
              behavior_score,
              last_event_ts,
              profile_v2_evidence_count,
              profile_v2_last_event_ts,
              profile_reset_before_ts,
              profile_v2_updated_at
            FROM user_profile
            WHERE user_id = %s
            {lock_clause}
            """,
            (user_id,),
        )
        row = cast(dict[str, Any] | None, cursor.fetchone())
    if row is None:
        raise LookupError(f"user_profile row not found for user_id={user_id}")
    return row


def topic_state_from_row(row: Mapping[str, Any] | None) -> TopicProfileState:
    if row is None:
        return TopicProfileState()
    signal_counts = parse_json(row.get("evidence_counts_json"), {})
    if not isinstance(signal_counts, dict):
        signal_counts = {}
    return TopicProfileState(
        short_positive_score=float(row.get("short_positive_score") or 0.0),
        short_negative_score=float(row.get("short_negative_score") or 0.0),
        long_positive_score=float(row.get("long_positive_score") or 0.0),
        long_negative_score=float(row.get("long_negative_score") or 0.0),
        positive_evidence_count=int(row.get("positive_evidence_count") or 0),
        negative_evidence_count=int(row.get("negative_evidence_count") or 0),
        signal_counts={str(key): int(value) for key, value in signal_counts.items()},
        last_signal_type=(
            str(row["last_signal_type"]) if row.get("last_signal_type") is not None else None
        ),
        last_event_ts=(int(row["last_event_ts"]) if row.get("last_event_ts") is not None else None),
    )


def fetch_topic_profile_state(
    connection: Any,
    *,
    user_id: int,
    topic_id: int,
    for_update: bool = False,
) -> TopicProfileState:
    lock_clause = " FOR UPDATE" if for_update else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
              short_positive_score,
              short_negative_score,
              long_positive_score,
              long_negative_score,
              positive_evidence_count,
              negative_evidence_count,
              evidence_counts_json,
              last_signal_type,
              last_event_ts
            FROM user_topic_profile
            WHERE user_id = %s AND topic_id = %s
            {lock_clause}
            """,
            (user_id, topic_id),
        )
        row = cast(dict[str, Any] | None, cursor.fetchone())
    return topic_state_from_row(row)


def upsert_topic_profile_state(
    connection: Any,
    *,
    user_id: int,
    topic_id: int,
    state: TopicProfileState,
) -> None:
    if state.last_event_ts is None:
        raise ValueError("projected topic state requires last_event_ts")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO user_topic_profile (
              user_id,
              topic_id,
              short_positive_score,
              short_negative_score,
              long_positive_score,
              long_negative_score,
              positive_evidence_count,
              negative_evidence_count,
              evidence_counts_json,
              last_signal_type,
              last_event_ts,
              updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, topic_id) DO UPDATE SET
              short_positive_score = EXCLUDED.short_positive_score,
              short_negative_score = EXCLUDED.short_negative_score,
              long_positive_score = EXCLUDED.long_positive_score,
              long_negative_score = EXCLUDED.long_negative_score,
              positive_evidence_count = EXCLUDED.positive_evidence_count,
              negative_evidence_count = EXCLUDED.negative_evidence_count,
              evidence_counts_json = EXCLUDED.evidence_counts_json,
              last_signal_type = EXCLUDED.last_signal_type,
              last_event_ts = EXCLUDED.last_event_ts,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                topic_id,
                state.short_positive_score,
                state.short_negative_score,
                state.long_positive_score,
                state.long_negative_score,
                state.positive_evidence_count,
                state.negative_evidence_count,
                json_text(dict(state.signal_counts)),
                state.last_signal_type,
                state.last_event_ts,
            ),
        )


def increment_profile_v2_evidence(
    connection: Any,
    *,
    user_id: int,
    event_ts: int,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE user_profile
            SET
              profile_v2_evidence_count = profile_v2_evidence_count + 1,
              profile_v2_last_event_ts = GREATEST(
                COALESCE(profile_v2_last_event_ts, 0),
                %s
              ),
              profile_v2_updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s
            """,
            (event_ts, user_id),
        )


def apply_profile_v2_event(
    connection: Any,
    *,
    user_id: int,
    event_type: str,
    event_ts: int,
    topic_strengths: Mapping[int, float],
    config: ProfileSignalConfig,
) -> bool:
    return apply_profile_v2_event_with_outcome(
        connection,
        user_id=user_id,
        event_type=event_type,
        event_ts=event_ts,
        topic_strengths=topic_strengths,
        config=config,
    ).updated


def profile_event_is_before_reset(
    connection: Any,
    *,
    user_id: int,
    event_ts: int,
) -> bool:
    user_state = fetch_profile_v2_user_state(connection, user_id=user_id, for_update=True)
    reset_before = user_state.get("profile_reset_before_ts")
    return reset_before is not None and event_ts <= int(reset_before)


def apply_profile_v2_event_with_outcome(
    connection: Any,
    *,
    user_id: int,
    event_type: str,
    event_ts: int,
    topic_strengths: Mapping[int, float],
    config: ProfileSignalConfig,
) -> ProfileProjectionOutcome:
    effective_strengths = {
        int(topic_id): float(strength)
        for topic_id, strength in topic_strengths.items()
        if float(strength) != 0.0
    }
    if not effective_strengths:
        return ProfileProjectionOutcome(
            updated=False,
            reason="no_signal",
            updated_topic_count=0,
            late_topic_count=0,
        )

    user_state = fetch_profile_v2_user_state(connection, user_id=user_id, for_update=True)
    reset_before = user_state.get("profile_reset_before_ts")
    if reset_before is not None and event_ts <= int(reset_before):
        return ProfileProjectionOutcome(
            updated=False,
            reason="pre_reset",
            updated_topic_count=0,
            late_topic_count=0,
        )

    updated_topics = 0
    late_topics = 0
    for topic_id, strength in sorted(effective_strengths.items()):
        current = fetch_topic_profile_state(
            connection,
            user_id=user_id,
            topic_id=topic_id,
            for_update=True,
        )
        projected = project_topic_signal(
            current,
            signal=strength,
            event_type=event_type,
            event_ts=event_ts,
            short_half_life_seconds=config.short_half_life_seconds,
            long_half_life_seconds=config.long_half_life_seconds,
            long_term_factor=config.long_term_factor,
        )
        if projected is None:
            late_topics += 1
            continue
        upsert_topic_profile_state(
            connection,
            user_id=user_id,
            topic_id=topic_id,
            state=projected,
        )
        updated_topics += 1

    if updated_topics == 0:
        return ProfileProjectionOutcome(
            updated=False,
            reason="out_of_order" if late_topics else "no_signal",
            updated_topic_count=0,
            late_topic_count=late_topics,
        )
    increment_profile_v2_evidence(connection, user_id=user_id, event_ts=event_ts)
    return ProfileProjectionOutcome(
        updated=True,
        reason=None,
        updated_topic_count=updated_topics,
        late_topic_count=late_topics,
    )


def load_topic_profile_rows(connection: Any, *, user_id: int) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              profile.topic_id,
              topic.display_name,
              profile.short_positive_score,
              profile.short_negative_score,
              profile.long_positive_score,
              profile.long_negative_score,
              profile.positive_evidence_count,
              profile.negative_evidence_count,
              profile.evidence_counts_json,
              profile.last_signal_type,
              profile.last_event_ts
            FROM user_topic_profile AS profile
            JOIN topic ON topic.topic_id = profile.topic_id
            WHERE profile.user_id = %s
            ORDER BY profile.topic_id
            """,
            (user_id,),
        )
        return list(cursor.fetchall())


def _recent_news(value: Any) -> list[ProfileRecentClick]:
    rows = parse_json(value, [])
    result: list[ProfileRecentClick] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        raw_id = row.get("news_id", row.get("answer_id"))
        if raw_id is None:
            continue
        text_id = str(raw_id)
        if text_id.startswith("N"):
            text_id = text_id[1:]
        if not text_id.isdigit():
            continue
        result.append(
            ProfileRecentClick(
                article_id=int(text_id),
                click_ts=int(row.get("click_ts") or 0),
            )
        )
    return result


def _topic_item(
    row: Mapping[str, Any],
    state: TopicProfileState,
    *,
    layer: Literal["short", "long"],
) -> ProfileTopicEvidence:
    if layer == "short":
        positive_score = state.short_positive_score
        negative_score = state.short_negative_score
    else:
        positive_score = state.long_positive_score
        negative_score = state.long_negative_score
    topic_id = int(row["topic_id"])
    return ProfileTopicEvidence(
        topic_id=topic_id,
        display_name=str(row.get("display_name") or f"Topic {topic_id}"),
        score=round(positive_score - negative_score, 6),
        positive_score=round(positive_score, 6),
        negative_score=round(negative_score, 6),
        positive_evidence_count=state.positive_evidence_count,
        negative_evidence_count=state.negative_evidence_count,
        signal_counts=dict(state.signal_counts),
        last_signal_type=state.last_signal_type,
        last_event_ts=int(state.last_event_ts or 0),
    )


def _profile_layer(
    rows_and_states: list[tuple[dict[str, Any], TopicProfileState]],
    *,
    layer: Literal["short", "long"],
) -> ProfileTermLayer:
    items = [_topic_item(row, state, layer=layer) for row, state in rows_and_states]
    interests = sorted(
        (item for item in items if item.score > 0.01),
        key=lambda item: (-item.score, item.topic_id),
    )[:10]
    reduced_topics = sorted(
        (item for item in items if item.score < -0.01),
        key=lambda item: (item.score, item.topic_id),
    )[:10]
    return ProfileTermLayer(interests=interests, reduced_topics=reduced_topics)


def load_profile_v2(
    connection: Any,
    *,
    user_id: int,
    now_ts: int,
    config: ProfileSignalConfig,
) -> ProfileResponse:
    user_state = fetch_profile_v2_user_state(connection, user_id=user_id)
    rows = load_topic_profile_rows(connection, user_id=user_id)
    rows_and_states = [
        (
            row,
            decayed_topic_state(
                topic_state_from_row(row),
                now_ts=now_ts,
                short_half_life_seconds=config.short_half_life_seconds,
                long_half_life_seconds=config.long_half_life_seconds,
            ),
        )
        for row in rows
    ]
    evidence_count = int(user_state.get("profile_v2_evidence_count") or 0)
    confidence = confidence_from_evidence(evidence_count)
    return ProfileResponse(
        user_id=int(user_state["user_id"]),
        status=profile_status(confidence),
        confidence=round(confidence, 6),
        evidence_count=evidence_count,
        short_term=_profile_layer(rows_and_states, layer="short"),
        long_term=_profile_layer(rows_and_states, layer="long"),
        recent_clicked_news=_recent_news(user_state.get("recent_clicked_news_json")),
        recent_queries=parse_recent_queries(user_state.get("recent_queries_json")),
        last_updated_at=user_state.get("profile_v2_updated_at"),
    )


def load_profile_seed(connection: Any, *, seed_key: str) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              topic_weights_json,
              recent_clicked_news_json,
              recent_queries_json,
              behavior_score
            FROM system_profile_seed
            WHERE seed_key = %s
            """,
            (seed_key,),
        )
        row = cast(dict[str, Any] | None, cursor.fetchone())
    if row is None:
        raise RuntimeError(f"system_profile_seed[{seed_key!r}] is missing")
    return row


def reset_profile_projections(
    connection: Any,
    *,
    user_id: int,
    reset_ts: int,
) -> None:
    profile = fetch_profile_v2_user_state(connection, user_id=user_id, for_update=True)
    seed_key = str(profile.get("cold_start_seed_key") or "cold_start_default")
    seed = load_profile_seed(connection, seed_key=seed_key)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE user_profile
            SET
              topic_weights_json = %s::jsonb,
              recent_clicked_news_json = %s::jsonb,
              recent_queries_json = %s::jsonb,
              behavior_score = %s,
              last_event_ts = NULL,
              profile_v2_evidence_count = 0,
              profile_v2_last_event_ts = NULL,
              profile_reset_before_ts = %s,
              profile_v2_updated_at = CURRENT_TIMESTAMP,
              updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s
            """,
            (
                json_text(seed.get("topic_weights_json") or []),
                json_text(seed.get("recent_clicked_news_json") or []),
                json_text(seed.get("recent_queries_json") or []),
                float(seed.get("behavior_score") or 0.0),
                reset_ts,
                user_id,
            ),
        )
        cursor.execute(
            "DELETE FROM user_topic_profile WHERE user_id = %s",
            (user_id,),
        )
