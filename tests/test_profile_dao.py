from __future__ import annotations

from backend.app.repositories import profile_dao
from backend.app.schemas.profile import ProfileRecentClick


def test_attach_recent_click_titles_preserves_order_and_adds_news_titles():
    attach_titles = getattr(profile_dao, "attach_recent_click_titles", None)
    assert attach_titles is not None

    clicks = [
        ProfileRecentClick(news_id="N1003", click_ts=200),
        ProfileRecentClick(news_id="N11899", click_ts=100),
    ]
    news_rows = {
        "N1003": {"title": "Finance briefing"},
        "N11899": {"title": "Sports roundup"},
    }

    enriched = attach_titles(clicks, news_rows)

    assert [item.news_id for item in enriched] == ["N1003", "N11899"]
    assert [item.title for item in enriched] == ["Finance briefing", "Sports roundup"]
