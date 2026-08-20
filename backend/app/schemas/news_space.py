from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from backend.app.news_spaces.types import DEFAULT_NEWS_SPACE, NewsSpace, validate_article_id_shape

from .common import ApiModel


def normalize_article_identity(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    data = value.copy()
    source_space = data.get("source_space", DEFAULT_NEWS_SPACE)
    article_id = data.get("article_id")
    news_id = data.get("news_id")
    if source_space == "mind":
        if article_id is None and news_id is not None:
            data["article_id"] = news_id
        elif article_id is not None and news_id is None:
            data["news_id"] = article_id
        elif article_id is not None and news_id is not None and article_id != news_id:
            raise ValueError("article_id and news_id must match")
    elif source_space == "live" and news_id is not None:
        raise ValueError("news_id is only supported for source_space 'mind'")
    return data


class CanonicalArticleModel(ApiModel):
    source_space: NewsSpace = DEFAULT_NEWS_SPACE
    article_id: str
    news_id: str | None = Field(default=None, deprecated=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_article_id(cls, value: Any) -> Any:
        return normalize_article_identity(value)

    @model_validator(mode="after")
    def validate_article_id(self) -> CanonicalArticleModel:
        self.article_id = validate_article_id_shape(self.source_space, self.article_id)
        return self


class ProfileTargetRequest(ApiModel):
    user_id: int
    source_space: NewsSpace = DEFAULT_NEWS_SPACE


class NewsSpaceCapability(ApiModel):
    source_space: NewsSpace
    enabled: bool


class NewsSpaceListResponse(ApiModel):
    items: list[NewsSpaceCapability]
