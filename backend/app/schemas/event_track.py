from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from backend.app.news_spaces.types import DEFAULT_NEWS_SPACE, NewsSpace, validate_article_id_shape

from .common import ApiModel
from .news_space import normalize_article_identity

EventTrackType = Literal[
    "feed_impression",
    "detail_view",
    "dwell",
    "upvote",
    "downvote",
    "share",
    "recommendation_click",
    "search_result_click",
    "outbound_click",
]


class EventTrackRequest(ApiModel):
    event_id: str | None = None
    user_id: int
    event_type: EventTrackType
    surface: str
    source_space: NewsSpace = DEFAULT_NEWS_SPACE
    article_id: str | None = None
    news_id: str | None = Field(default=None, description="Deprecated MIND compatibility alias")
    query_key: str | None = None
    request_id: str | None = None
    sponsored_delivery_id: str | None = None
    dwell_ms: int | None = Field(None, ge=0, le=86_400_000)
    debug: bool = False
    replay_event_ts: int | None = Field(None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def normalize_article_identity(cls, value: Any) -> Any:
        return normalize_article_identity(value)

    @model_validator(mode="after")
    def validate_event_fields(self) -> EventTrackRequest:
        article_required = {
            "feed_impression",
            "detail_view",
            "dwell",
            "upvote",
            "downvote",
            "share",
            "recommendation_click",
            "search_result_click",
            "outbound_click",
        }
        if self.article_id is not None:
            self.article_id = validate_article_id_shape(self.source_space, self.article_id)
        if self.event_type in article_required and self.article_id is None:
            raise ValueError(f"{self.event_type} requires article_id")
        if self.event_type == "search_result_click" and not self.query_key:
            raise ValueError("search_result_click requires query_key")
        if self.event_type == "dwell" and self.dwell_ms is None:
            raise ValueError("dwell requires dwell_ms")
        if self.source_space == "live" and self.sponsored_delivery_id is not None:
            raise ValueError("Sponsored identity is only supported for source_space 'mind'")
        if self.replay_event_ts is not None and not self.debug:
            raise ValueError("replay_event_ts requires debug=true")
        return self


class EventTrackResponse(ApiModel):
    ok: bool
    event_type: EventTrackType
    source_space: NewsSpace = DEFAULT_NEWS_SPACE
    profile_updated: bool
    behavior_score: float | None = None
