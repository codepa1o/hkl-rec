from __future__ import annotations

from .common import ApiModel


class CategoryItem(ApiModel):
    key: str
    news_count: int


class CategoryListResponse(ApiModel):
    items: list[CategoryItem]
