from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ApiModel, TopicCard


class ArticleEntity(ApiModel):
    label: str
    entity_type: Literal["person", "organization", "location", "other"]
    type_code: str
    wikidata_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    surface_forms: list[str] = Field(default_factory=list)


class ArticleCardResponse(ApiModel):
    news_id: str = Field(pattern=r"^N[0-9]+$")
    title: str
    abstract: str
    url: str
    source_domain: str
    category: str
    subcategory: str
    categories: list[TopicCard]
    title_entities: list[ArticleEntity]
    abstract_entities: list[ArticleEntity]
