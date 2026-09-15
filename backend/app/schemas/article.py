from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from backend.app.live_news.content_document import BodyStructureStatus, StructuredBodyDocument

from .common import ApiModel, TopicCard
from .news_space import CanonicalArticleModel


class ArticleEntity(ApiModel):
    label: str
    entity_type: Literal["person", "organization", "location", "other"]
    type_code: str
    wikidata_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    surface_forms: list[str] = Field(default_factory=list)


class ArticleCardResponse(CanonicalArticleModel):
    title: str
    abstract: str
    url: str
    source_domain: str
    category: str
    subcategory: str
    categories: list[TopicCard]
    title_entities: list[ArticleEntity]
    abstract_entities: list[ArticleEntity]
    image_url: str | None = None
    publisher: str | None = None
    language: Literal["zh", "en"] | None = None
    published_at: datetime | None = None
    discovered_at: datetime | None = None
    body_text: str | None = None
    body_status: Literal["metadata_only", "pending", "available", "blocked", "failed"] = (
        "metadata_only"
    )
    body_source: Literal["guardian_api", "rss", "html"] | None = None
    content_rights: Literal["full_text", "excerpt_only", "link_only"] = "link_only"
    body_access_scope: Literal["public", "local_research"] = "public"
    body_document: StructuredBodyDocument | None = None
    body_structure_status: BodyStructureStatus = "missing"
    body_document_version: str | None = None


class ContentEnsureResponse(ApiModel):
    article_id: str
    status: BodyStructureStatus
    enqueued: bool
    retry_after_seconds: int | None = Field(default=None, ge=1, le=300)
