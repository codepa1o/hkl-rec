from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app.live_news.ranking import (
    LiveCandidate,
    diversify_live_candidates,
    score_live_candidate,
)

NOW = datetime(2026, 8, 17, 12, tzinfo=UTC)


def candidate(
    article_id: str,
    *,
    hours_old: int,
    publisher: str = "Reuters",
    language: str = "en",
    quality: float = 1.0,
    title: str | None = None,
) -> LiveCandidate:
    return LiveCandidate(
        article_id=article_id,
        title=title or f"Article {article_id}",
        summary="Complete summary",
        image_url="https://example.invalid/image.jpg",
        publisher=publisher,
        source_domain=publisher.lower().replace(" ", "") + ".example",
        language=language,
        best_timestamp=NOW - timedelta(hours=hours_old),
        discovered_at=NOW - timedelta(hours=hours_old),
        publisher_quality=quality,
        row={},
    )


def test_live_ranking_prefers_fresh_complete_articles() -> None:
    fresh = candidate("L" + "1" * 32, hours_old=1, quality=0.95)
    stale = candidate("L" + "2" * 32, hours_old=48, quality=1.0)

    assert score_live_candidate(fresh, NOW) > score_live_candidate(stale, NOW)


def test_diversification_limits_publisher_runs_and_covers_both_languages() -> None:
    candidates = [
        candidate("L" + f"{index:032x}", hours_old=index, publisher="Reuters")
        for index in range(1, 5)
    ]
    candidates.append(candidate("L" + "f" * 32, hours_old=5, publisher="新华网", language="zh"))

    result = diversify_live_candidates(candidates, limit=5, language="all")

    assert {item.language for item in result} == {"zh", "en"}
    assert all(
        not (result[index].publisher == result[index + 1].publisher == result[index + 2].publisher)
        for index in range(len(result) - 2)
    )
