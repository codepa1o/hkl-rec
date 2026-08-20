from __future__ import annotations

from backend.app.news_spaces.types import DEFAULT_NEWS_SPACE, NewsSpace

from .common import ApiModel


class SuggestionItem(ApiModel):
    query_key: str
    label: str
    topic_count: int


class SuggestionListResponse(ApiModel):
    source_space: NewsSpace = DEFAULT_NEWS_SPACE
    items: list[SuggestionItem]
