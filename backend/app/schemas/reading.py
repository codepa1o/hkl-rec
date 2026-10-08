from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from backend.app.news_spaces.types import NewsSpace, validate_article_id_shape

from .common import ApiModel
from .search import SearchResponse


class ReadingStateRequest(ApiModel):
    source_space: NewsSpace
    article_id: str
    saved: bool | None = None
    read: bool | None = None

    @model_validator(mode="after")
    def validate_change(self) -> ReadingStateRequest:
        validate_article_id_shape(self.source_space, self.article_id)
        if self.saved is None and self.read is None:
            raise ValueError("saved or read must be provided")
        return self


class ReadingStateResponse(ApiModel):
    source_space: NewsSpace
    article_id: str
    saved: bool
    read: bool


class ReadingStateListResponse(ApiModel):
    items: list[ReadingStateResponse]


class ReadingRuleRequest(ApiModel):
    source_space: NewsSpace
    id: int | None = Field(default=None, ge=1)
    target_type: Literal["source", "topic", "keyword"]
    value: str = Field(min_length=1, max_length=200)
    effect: Literal["prefer", "reduce", "block"]
    enabled: bool = True

    @model_validator(mode="after")
    def validate_value(self) -> ReadingRuleRequest:
        self.value = self.value.strip()
        if not self.value:
            raise ValueError("value must not be blank")
        return self


class ReadingRuleDeleteRequest(ApiModel):
    source_space: NewsSpace


class ReadingRuleResponse(ApiModel):
    id: int
    source_space: NewsSpace
    target_type: Literal["source", "topic", "keyword"]
    value: str
    effect: Literal["prefer", "reduce", "block"]
    enabled: bool


class ReadingRuleListResponse(ApiModel):
    items: list[ReadingRuleResponse]


class SavedSearchRequest(ApiModel):
    source_space: NewsSpace
    query: str = Field(min_length=1, max_length=300)
    language: Literal["all", "zh", "en"] = "all"
    category: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")

    @model_validator(mode="after")
    def validate_query(self) -> SavedSearchRequest:
        self.query = self.query.strip()
        if not self.query:
            raise ValueError("query must not be blank")
        if self.source_space == "mind" and self.language != "all":
            raise ValueError("MIND searches do not support language filters")
        return self


class SavedSearchDeleteRequest(ApiModel):
    source_space: NewsSpace


class SavedSearchResponse(ApiModel):
    id: int
    source_space: NewsSpace
    query: str
    language: Literal["all", "zh", "en"]
    category: str | None = None


class SavedSearchListResponse(ApiModel):
    items: list[SavedSearchResponse]


class LibraryItem(ApiModel):
    source_space: NewsSpace
    article_id: str
    saved: bool
    read: bool
    title: str
    url: str
    source_domain: str
    available: bool


class LibraryResponse(ApiModel):
    items: list[LibraryItem]
    has_more: bool


class ReadingSearchRequest(ApiModel):
    source_space: NewsSpace
    query: str = Field(min_length=1, max_length=300)
    event_id: str | None = Field(default=None, min_length=1, max_length=128)
    language: Literal["all", "zh", "en"] = "all"
    category: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    include_hidden: bool = False
    page_size: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def validate_query(self) -> ReadingSearchRequest:
        self.query = self.query.strip()
        if not self.query:
            raise ValueError("query must not be blank")
        if self.source_space == "mind" and self.language != "all":
            raise ValueError("MIND searches do not support language filters")
        return self


class ReadingSearchResponse(SearchResponse):
    hidden_count: int = 0
