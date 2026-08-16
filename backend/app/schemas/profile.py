from __future__ import annotations

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
