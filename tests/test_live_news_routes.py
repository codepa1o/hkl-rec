from __future__ import annotations

from dataclasses import replace

import pytest

from backend.app.config import get_settings
from backend.app.repositories.postgres import PostgresRuntimeRepository
from backend.app.schemas.search import SearchRequest


@pytest.mark.postgres
def test_live_repository_serves_feed_search_and_article(
    seeded_live_articles,
) -> None:
    settings = replace(get_settings(), live_news_enabled=True)
    repository = PostgresRuntimeRepository(settings)
    try:
        feed = repository.get_feed(
            user_id=seeded_live_articles.user_id,
            page_size=10,
            debug=False,
            include_sponsored=True,
            source_space="live",
            language="all",
        )
        assert feed.source_space == "live"
        assert {item.language for item in feed.items} == {"zh", "en"}
        assert all(item.content_type == "organic" and item.sponsored is None for item in feed.items)

        search = repository.search(
            SearchRequest(
                user_id=seeded_live_articles.user_id,
                source_space="live",
                query_text="fixture",
            )
        )
        assert search.source_space == "live"
        assert search.items

        article = repository.get_article_card("live", seeded_live_articles.article_ids[0])
        assert article.source_space == "live"
        assert article.article_id == seeded_live_articles.article_ids[0]
        assert article.title_entities == []
    finally:
        repository.close()
