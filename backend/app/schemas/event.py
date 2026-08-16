from __future__ import annotations

from pydantic import Field, model_validator

from .common import ApiModel


class RecommendationClickRequest(ApiModel):
    event_id: str | None = None
    user_id: int
    news_id: str = Field(pattern=r"^N[0-9]+$")
    request_id: str | None = None
    sponsored_delivery_id: str | None = None
    debug: bool = False
    replay_event_ts: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def validate_replay_event_ts(self) -> RecommendationClickRequest:
        if self.replay_event_ts is not None and not self.debug:
            raise ValueError("replay_event_ts requires debug=true")
        return self


class SearchResultClickRequest(ApiModel):
    event_id: str | None = None
    user_id: int
    news_id: str = Field(pattern=r"^N[0-9]+$")
    query_key: str
    request_id: str | None = None
    sponsored_delivery_id: str | None = None
    debug: bool = False
    replay_event_ts: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def validate_replay_event_ts(self) -> SearchResultClickRequest:
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
    debug: RecommendationClickDebug | SearchResultClickDebug | None = None
