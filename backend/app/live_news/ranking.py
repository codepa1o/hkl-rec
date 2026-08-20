from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from backend.app.live_news.normalize import title_trigram_jaccard


@dataclass(frozen=True)
class LiveCandidate:
    article_id: str
    title: str
    summary: str
    image_url: str | None
    publisher: str
    source_domain: str
    language: Literal["zh", "en"]
    best_timestamp: datetime
    discovered_at: datetime
    publisher_quality: float
    row: dict[str, Any]


def freshness_score(age_seconds: float) -> float:
    return math.exp(-math.log(2.0) * max(age_seconds, 0.0) / 86_400.0)


def completeness_score(candidate: LiveCandidate) -> float:
    return (
        (0.5 if candidate.summary else 0.0)
        + (0.3 if candidate.image_url else 0.0)
        + (0.2 if candidate.publisher != candidate.source_domain else 0.0)
    )


def score_live_candidate(candidate: LiveCandidate, now: datetime) -> float:
    age = (now - candidate.best_timestamp).total_seconds()
    return round(
        0.65 * freshness_score(age)
        + 0.20 * candidate.publisher_quality
        + 0.15 * completeness_score(candidate),
        8,
    )


def diversify_live_candidates(
    candidates: list[LiveCandidate],
    *,
    limit: int,
    language: Literal["all", "zh", "en"],
    now: datetime | None = None,
) -> list[LiveCandidate]:
    if limit <= 0:
        return []
    reference_time = (
        now
        if now is not None
        else max(
            (candidate.discovered_at for candidate in candidates),
            default=datetime.now().astimezone(),
        )
    )
    filtered = [
        candidate for candidate in candidates if language == "all" or candidate.language == language
    ]
    remaining = sorted(
        filtered,
        key=lambda item: (
            -score_live_candidate(item, reference_time),
            -item.discovered_at.timestamp(),
            item.article_id,
        ),
    )
    selected: list[LiveCandidate] = []
    required_languages = (
        {candidate.language for candidate in remaining} if language == "all" else set()
    )
    while remaining and len(selected) < limit:
        chosen_index: int | None = None
        selected_languages = {candidate.language for candidate in selected}
        missing_languages = required_languages - selected_languages
        for index, candidate in enumerate(remaining):
            if len(selected) >= 2 and all(
                previous.publisher == candidate.publisher for previous in selected[-2:]
            ):
                continue
            if selected and title_trigram_jaccard(selected[-1].title, candidate.title) >= 0.92:
                continue
            if (
                missing_languages
                and len(selected) + len(missing_languages) >= limit
                and candidate.language not in missing_languages
            ):
                continue
            chosen_index = index
            break
        if chosen_index is None:
            chosen_index = 0
        selected.append(remaining.pop(chosen_index))
    return selected
