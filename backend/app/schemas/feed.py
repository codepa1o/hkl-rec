from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ApiModel, TopicCard
from .profile import ProfileTopicWeight

FeedExperimentArm = Literal[
    "default",
    "profile_v2",
    "manual",
    "manual_plus_als",
    "lgb_plus_als",
    "lgb_plus_als_plus_search",
    "lgb_plus_als_plus_search_mmr",
    "lgb_plus_als_plus_search_decay_30m",
    "lgb_plus_als_plus_search_decay_4h",
    "lgb_plus_als_plus_search_gated_30m_4h",
    "lgb_plus_als_plus_search_gated_2h_12h",
]


class FeedItemScores(ApiModel):
    base_recall_score: float
    personalized_topic_score: float
    default_topic_score: float
    topic_match_score: float
    query_recall_boost: float
    final_score: float
    profile_v2_score: float | None = Field(default=None, exclude_if=lambda value: value is None)
    sponsored_score: float | None = None


class SponsoredFeedMetadata(ApiModel):
    delivery_id: str
    campaign_id: int
    creative_id: int
    label: str = "Sponsored"


class FeedItem(ApiModel):
    article_id: int
    headline: str
    abstract: str
    source_domain: str
    categories: list[TopicCard]
    selected_reason: str
    scores: FeedItemScores
    recall_sources: list[str]
    is_fallback: bool
    content_type: Literal["organic", "sponsored"] = "organic"
    sponsored: SponsoredFeedMetadata | None = None


class FeedProfileSummary(ApiModel):
    behavior_score: float
    top_topics: list[ProfileTopicWeight]


class RecallCandidateDebug(ApiModel):
    article_id: int
    source: str
    base_recall_score: float


class SponsoredCandidateDebug(ApiModel):
    campaign_id: int
    creative_id: int
    article_id: int
    slot_position: int
    expected_spend_micros: int
    sponsored_score: float


class ArtifactDebug(ApiModel):
    lightgbm_data_fingerprint: str | None = None
    lightgbm_feature_schema_version: int | None = None
    als_data_fingerprint: str | None = None
    als_train_ratio: float | None = None


class ColdStartMix(ApiModel):
    alpha: float
    behavior_score: float
    default_seed_key: str
    default_topic_count: int


class FeedDebugPayload(ApiModel):
    experiment_arm: FeedExperimentArm
    profile_summary: FeedProfileSummary
    recall_candidates: list[RecallCandidateDebug]
    sponsored_candidates: list[SponsoredCandidateDebug] = Field(default_factory=list)
    artifacts: ArtifactDebug
    fallback_used: bool
    cold_start_mix: ColdStartMix


class FeedResponse(ApiModel):
    user_id: int
    request_id: str
    items: list[FeedItem]
    debug: FeedDebugPayload | None = None
