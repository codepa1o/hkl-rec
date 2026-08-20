from __future__ import annotations

from backend.app.news_spaces.types import DEFAULT_NEWS_SPACE, NewsSpace

from .common import ApiModel


class CategoryItem(ApiModel):
    key: str
    news_count: int


class CategoryListResponse(ApiModel):
    source_space: NewsSpace = DEFAULT_NEWS_SPACE
    items: list[CategoryItem]
