from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from backend.app.news_spaces.types import DEFAULT_NEWS_SPACE, NewsSpace

from .common import ApiModel, TopicCard
from .news_space import CanonicalArticleModel


class SearchRequest(ApiModel):
    source_space: NewsSpace = DEFAULT_NEWS_SPACE
    event_id: str | None = None
    user_id: int
    query_key: str | None = None
    query_text: str | None = None
    page_size: int = Field(10, ge=1, le=50)
    debug: bool = False
    replay_event_ts: int | None = Field(None, ge=0)

    @field_validator("query_key")
    @classmethod
    def normalize_query_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @field_validator("query_text")
    @classmethod
    def normalize_query_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def require_query_key_or_text(self) -> SearchRequest:
        if not self.query_key and not self.query_text:
            raise ValueError("query_key or query_text is required")
        if self.replay_event_ts is not None and not self.debug:
            raise ValueError("replay_event_ts requires debug=true")
        return self


class SearchItemScores(ApiModel):
    topic_match_score: float
    bm25_score: float = 0.0
    dense_score: float = 0.0
    hybrid_score: float = 0.0
    final_score: float


class SearchItem(CanonicalArticleModel):
    title: str
    abstract: str
    url: str
    source_domain: str
    category: str
    subcategory: str
    categories: list[TopicCard]
    scores: SearchItemScores
    image_url: str | None = None
    publisher: str | None = None
    language: Literal["zh", "en"] | None = None
    published_at: datetime | None = None
    discovered_at: datetime | None = None


class SearchMatchedTopic(ApiModel):
    topic_id: int
    score: float
    rank: int


class SearchResultSource(ApiModel):
    news_id: str
    source: str


class SearchArtifactDebug(ApiModel):
    model_id: str
    model_revision: str
    source_fingerprint: str


class SearchDebugPayload(ApiModel):
    matched_topics: list[SearchMatchedTopic]
    result_sources: list[SearchResultSource]
    retrieval_mode: str = "lexical_v1"
    resolution_source: str = "unknown"
    resolution_confidence: float = 0.0
    artifact: SearchArtifactDebug | None = None


class SearchResponse(ApiModel):
    source_space: NewsSpace = DEFAULT_NEWS_SPACE
    user_id: int
    request_id: str
    query_key: str
    items: list[SearchItem]
    debug: SearchDebugPayload | None = None

    @model_validator(mode="after")
    def require_matching_item_source_space(self) -> SearchResponse:
        if any(item.source_space != self.source_space for item in self.items):
            raise ValueError("items must match response source_space")
        return self
