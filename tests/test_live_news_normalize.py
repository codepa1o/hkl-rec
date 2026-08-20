from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.app.live_news.allowlist import load_allowlist
from backend.app.live_news.normalize import (
    canonicalize_url,
    classify_gal_record,
    content_hash,
    deduplicate_articles,
    live_article_id,
    title_trigram_jaccard,
)
from backend.app.live_news.types import LiveNewsArticle, RejectedGalRecord

NOW = datetime(2026, 8, 17, 2, 16, tzinfo=UTC)
ALLOWLIST = Path("config/live_news_sources.json")


def valid_record(**updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "date": "2026-08-17T02:07:00.000Z",
        "url": "https://www.reuters.com/world/story/?utm_source=x#top",
        "domain": "www.reuters.com",
        "outletName": "Reuters",
        "title": "A current English news test",
        "image": "https://example.invalid/image.jpg",
        "desc": "A complete description used for deterministic hashing.",
        "lang": "en",
        "author": "Reuters",
    }
    record.update(updates)
    return record


def test_normalize_allowlisted_live_article() -> None:
    result = classify_gal_record(
        valid_record(),
        discovered_at=NOW,
        allowlist=load_allowlist(ALLOWLIST),
    )

    assert isinstance(result, LiveNewsArticle)
    assert result.canonical_url == "https://www.reuters.com/world/story/"
    assert result.article_id == live_article_id(result.canonical_url)
    assert result.article_id.startswith("L") and len(result.article_id) == 33
    assert result.published_at_quality == "gdelt_unverified"
    assert result.publisher_quality == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"domain": "unknown.invalid", "url": "https://unknown.invalid/a"}, "domain_not_allowed"),
        ({"lang": "fr"}, "unsupported_language"),
        ({"title": ""}, "missing_title"),
        ({"title": "Page Expired"}, "invalid_page"),
        ({"url": "https://www.reuters.com/topic/world"}, "invalid_page"),
        ({"url": "https://www.reuters.com/world/series/stateside"}, "invalid_page"),
        ({"date": "2026-08-13T00:00:00.000Z"}, "stale_article"),
        ({"date": "not-a-date"}, "invalid_metadata"),
    ],
)
def test_rejects_invalid_gal_records(updates: dict[str, object], reason: str) -> None:
    result = classify_gal_record(
        valid_record(**updates),
        discovered_at=NOW,
        allowlist=load_allowlist(ALLOWLIST),
    )

    assert isinstance(result, RejectedGalRecord)
    assert result.reason == reason


def test_canonicalization_and_hashes_are_deterministic() -> None:
    first = canonicalize_url("HTTPS://WWW.REUTERS.COM/world/story?b=2&utm_medium=email&a=1#section")
    second = canonicalize_url("https://www.reuters.com/world/story?a=1&b=2")

    assert first == second == "https://www.reuters.com/world/story?a=1&b=2"
    assert content_hash("  Headline  ", "Summary\ntext") == content_hash("Headline", "Summary text")


def test_near_title_duplicate_keeps_higher_quality_article() -> None:
    allowlist = load_allowlist(ALLOWLIST)
    lower_quality = classify_gal_record(
        valid_record(
            url="https://www.thepaper.cn/newsDetail_forward_1",
            domain="www.thepaper.cn",
            outletName="澎湃新闻",
            lang="zh",
            title="人工智能产业迎来新的发展阶段",
            desc="",
            image="",
        ),
        discovered_at=NOW,
        allowlist=allowlist,
    )
    higher_quality = classify_gal_record(
        valid_record(
            url="https://www.reuters.com/technology/ai-stage",
            title="人工智能产业迎来新的发展阶段！",
            desc="Complete metadata summary.",
        ),
        discovered_at=NOW + timedelta(minutes=1),
        allowlist=allowlist,
    )
    assert isinstance(lower_quality, LiveNewsArticle)
    assert isinstance(higher_quality, LiveNewsArticle)
    assert title_trigram_jaccard(lower_quality.title, higher_quality.title) >= 0.92

    kept, rejected = deduplicate_articles([lower_quality, higher_quality])

    assert kept == [higher_quality]
    assert rejected[0].reason == "duplicate_content"
