from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from backend.app.news_spaces.types import (
    DEFAULT_NEWS_SPACE,
    NewsSpace,
    validate_article_id_shape,
)

from .common import ApiModel
from .news_space import normalize_article_identity


class RecommendationClickRequest(ApiModel):
    source_space: NewsSpace = DEFAULT_NEWS_SPACE
    article_id: str
    news_id: str | None = Field(default=None, description="Deprecated MIND compatibility alias")
    event_id: str | None = None
    user_id: int
    request_id: str | None = None
    sponsored_delivery_id: str | None = None
    debug: bool = False
    replay_event_ts: int | None = Field(None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def normalize_article_identity(cls, value: Any) -> Any:
        return normalize_article_identity(value)

    @model_validator(mode="after")
    def validate_replay_event_ts(self) -> RecommendationClickRequest:
        self.article_id = validate_article_id_shape(self.source_space, self.article_id)
        if self.source_space == "live" and self.sponsored_delivery_id is not None:
            raise ValueError("Sponsored identity is only supported for source_space 'mind'")
        if self.replay_event_ts is not None and not self.debug:
            raise ValueError("replay_event_ts requires debug=true")
        return self


class SearchResultClickRequest(ApiModel):
    source_space: NewsSpace = DEFAULT_NEWS_SPACE
    article_id: str
    news_id: str | None = Field(default=None, description="Deprecated MIND compatibility alias")
    event_id: str | None = None
    user_id: int
    query_key: str
    request_id: str | None = None
    sponsored_delivery_id: str | None = None
    debug: bool = False
    replay_event_ts: int | None = Field(None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def normalize_article_identity(cls, value: Any) -> Any:
        return normalize_article_identity(value)

    @model_validator(mode="after")
    def validate_replay_event_ts(self) -> SearchResultClickRequest:
        self.article_id = validate_article_id_shape(self.source_space, self.article_id)
        if self.source_space == "live" and self.sponsored_delivery_id is not None:
            raise ValueError("Sponsored identity is only supported for source_space 'mind'")
        if self.replay_event_ts is not None and not self.debug:
            raise ValueError("replay_event_ts requires debug=true")
        return self


class UpdatedTopicDelta(ApiModel):
    topic_id: int
    delta: float


class RecentClickedNews(ApiModel):
    news_id: str
    click_ts: int


class SearchQueryTopic(ApiModel):
    topic_id: int
    score: float


class NewsTopic(ApiModel):
    topic_id: int


class OverlapTopic(ApiModel):
    topic_id: int
    boost_type: str


class RecommendationClickDebug(ApiModel):
    updated_topics: list[UpdatedTopicDelta]
    recent_clicked_news_tail: list[RecentClickedNews]
    behavior_score: float


class SearchResultClickDebug(ApiModel):
    query_topics: list[SearchQueryTopic]
    news_topics: list[NewsTopic]
    overlap_topics: list[OverlapTopic]
    behavior_score: float


class EventAckResponse(ApiModel):
    ok: bool
    event_type: str
    source_space: NewsSpace = DEFAULT_NEWS_SPACE
    debug: RecommendationClickDebug | SearchResultClickDebug | None = None
