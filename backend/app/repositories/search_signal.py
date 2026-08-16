from __future__ import annotations

import math
from dataclasses import dataclass

from backend.app.schemas.feed import FeedExperimentArm
from backend.app.schemas.profile import ProfileRecentQuery


@dataclass(frozen=True)
class SearchSignalConfig:
    mode: str
    query_half_life_seconds: int | None = None
    confirmed_half_life_seconds: int | None = None
    confirmed_multiplier: float = 1.0
    cutoff_half_lives: float = 4.0


LEGACY_SEARCH_CONFIG = SearchSignalConfig(mode="legacy")

SEARCH_SIGNAL_CONFIGS: dict[FeedExperimentArm, SearchSignalConfig] = {
    "default": LEGACY_SEARCH_CONFIG,
    "profile_v2": LEGACY_SEARCH_CONFIG,
    "lgb_plus_als_plus_search": LEGACY_SEARCH_CONFIG,
    "lgb_plus_als_plus_search_mmr": LEGACY_SEARCH_CONFIG,
    "lgb_plus_als_plus_search_decay_30m": SearchSignalConfig(
        mode="decay",
        query_half_life_seconds=30 * 60,
    ),
    "lgb_plus_als_plus_search_decay_4h": SearchSignalConfig(
        mode="decay",
        query_half_life_seconds=4 * 60 * 60,
    ),
    "lgb_plus_als_plus_search_gated_30m_4h": SearchSignalConfig(
        mode="gated",
        query_half_life_seconds=30 * 60,
        confirmed_half_life_seconds=4 * 60 * 60,
        confirmed_multiplier=2.0,
    ),
    "lgb_plus_als_plus_search_gated_2h_12h": SearchSignalConfig(
        mode="gated",
        query_half_life_seconds=2 * 60 * 60,
        confirmed_half_life_seconds=12 * 60 * 60,
        confirmed_multiplier=2.0,
    ),
}


def search_signal_config(arm: FeedExperimentArm) -> SearchSignalConfig | None:
    return SEARCH_SIGNAL_CONFIGS.get(arm)


def query_can_open_recall(
    query: ProfileRecentQuery,
    *,
    config: SearchSignalConfig,
) -> bool:
    return config.mode != "gated" or query.confirmed_ts is not None


def recent_query_multiplier(
    query: ProfileRecentQuery,
    *,
    now_ts: int,
    config: SearchSignalConfig,
) -> float:
    if config.mode == "legacy":
        return 1.0

    origin_ts = query.query_ts
    half_life_seconds = config.query_half_life_seconds
    multiplier = 1.0
    if config.mode == "gated" and query.confirmed_ts is not None:
        origin_ts = query.confirmed_ts
        half_life_seconds = config.confirmed_half_life_seconds
        multiplier = config.confirmed_multiplier
    if not half_life_seconds:
        return 0.0

    age_seconds = max(0, now_ts - origin_ts)
    if age_seconds > half_life_seconds * config.cutoff_half_lives:
        return 0.0
    return multiplier * math.pow(0.5, age_seconds / half_life_seconds)
