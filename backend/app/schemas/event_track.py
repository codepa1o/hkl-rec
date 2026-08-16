from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import ApiModel

EventTrackType = Literal[
    "feed_impression",
    "detail_view",
    "dwell",
    "upvote",
    "downvote",
    "share",
    "recommendation_click",
    "search_result_click",
]


class EventTrackRequest(ApiModel):
    event_id: str | None = None
    user_id: int
    event_type: EventTrackType
    surface: str
    news_id: str | None = Field(None, pattern=r"^N[0-9]+$")
    query_key: str | None = None
    request_id: str | None = None
    sponsored_delivery_id: str | None = None
    dwell_ms: int | None = Field(None, ge=0, le=86_400_000)
    debug: bool = False
    replay_event_ts: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def validate_event_fields(self) -> EventTrackRequest:
        news_required = {
            "feed_impression",
            "detail_view",
            "dwell",
            "upvote",
            "downvote",
            "share",
            "recommendation_click",
            "search_result_click",
        }
        if self.event_type in news_required and self.news_id is None:
            raise ValueError(f"{self.event_type} requires news_id")
        if self.event_type == "search_result_click" and not self.query_key:
            raise ValueError("search_result_click requires query_key")
        if self.event_type == "dwell" and self.dwell_ms is None:
            raise ValueError("dwell requires dwell_ms")
        if self.replay_event_ts is not None and not self.debug:
            raise ValueError("replay_event_ts requires debug=true")
        return self


class EventTrackResponse(ApiModel):
    ok: bool
    event_type: EventTrackType
    profile_updated: bool
    behavior_score: float | None = None
