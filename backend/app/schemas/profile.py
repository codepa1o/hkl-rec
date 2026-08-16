from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import ApiModel


class ProfileTopicWeight(ApiModel):
    topic_id: int
    weight: float


class ProfileRecentClick(ApiModel):
    news_id: str
    click_ts: int
    title: str | None = None


class ProfileRecentQuery(ApiModel):
    query_key: str
    query_ts: int
    confirmed_ts: int | None = None


class VectorSummary(ApiModel):
    vector_key_count: int
    top_contributing_topics: list[ProfileTopicWeight]


class DebugProfileResponse(ApiModel):
    user_id: int
    cold_start_seed_key: str
    behavior_score: float
    topic_weights: list[ProfileTopicWeight]
    recent_clicked_news: list[ProfileRecentClick]
    recent_queries: list[ProfileRecentQuery]
    vector_summary: VectorSummary


class ProfileTopicEvidence(ApiModel):
    topic_id: int
    display_name: str
    score: float
    positive_score: float
    negative_score: float
    positive_evidence_count: int
    negative_evidence_count: int
    signal_counts: dict[str, int] = Field(default_factory=dict)
    last_signal_type: str | None = None
    last_event_ts: int


class ProfileTermLayer(ApiModel):
    interests: list[ProfileTopicEvidence] = Field(default_factory=list)
    reduced_topics: list[ProfileTopicEvidence] = Field(default_factory=list)


class ProfileResponse(ApiModel):
    user_id: int
    profile_version: Literal["v2"] = "v2"
    status: Literal["cold", "learning", "established"]
    confidence: float
    evidence_count: int
    short_term: ProfileTermLayer
    long_term: ProfileTermLayer
    recent_clicked_news: list[ProfileRecentClick] = Field(default_factory=list)
    recent_queries: list[ProfileRecentQuery] = Field(default_factory=list)
    last_updated_at: datetime | None = None
