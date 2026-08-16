export interface TopicCard {
  topic_id: number;
  display_name: string;
}

export interface ProfileTopicWeight {
  topic_id: number;
  weight: number;
}

export interface PersonaCard {
  user_id: number;
  display_name: string;
  behavior_score: number;
  top_topics: ProfileTopicWeight[];
}

export interface PersonaListResponse {
  items: PersonaCard[];
}

export interface AuthUser {
  user_id: number;
  email: string;
  display_name: string;
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface RegisterInput extends LoginInput {
  display_name: string;
}

export interface SuggestionItem {
  query_key: string;
  label: string;
  topic_count: number;
}

export interface SuggestionListResponse {
  items: SuggestionItem[];
}

export interface ArticleCardResponse {
  article_id: number;
  headline: string;
  abstract: string;
  source_domain: string;
  categories: TopicCard[];
}

export interface FeedItemScores {
  base_recall_score: number;
  personalized_topic_score: number;
  default_topic_score: number;
  topic_match_score: number;
  query_recall_boost: number;
  final_score: number;
  profile_v2_score?: number | null;
  sponsored_score?: number | null;
}

export interface SponsoredFeedMetadata {
  delivery_id: string;
  campaign_id: number;
  creative_id: number;
  label: string;
}

export interface FeedItem {
  article_id: number;
  headline: string;
  abstract: string;
  source_domain: string;
  categories: TopicCard[];
  selected_reason: string;
  scores: FeedItemScores;
  recall_sources: string[];
  is_fallback: boolean;
  content_type: "organic" | "sponsored";
  sponsored?: SponsoredFeedMetadata | null;
}

export interface FeedResponse {
  user_id: number;
  request_id: string;
  items: FeedItem[];
  debug?: unknown;
}

export interface SearchItemScores {
  topic_match_score: number;
  bm25_score: number;
  dense_score: number;
  hybrid_score: number;
  final_score: number;
}

export interface SearchItem {
  article_id: number;
  headline: string;
  abstract: string;
  source_domain: string;
  categories: TopicCard[];
  scores: SearchItemScores;
}

export interface SearchResponse {
  user_id: number;
  request_id: string;
  query_key: string;
  items: SearchItem[];
  debug?: unknown;
}

export interface ProfileRecentClick {
  article_id: number;
  click_ts: number;
}

export interface ProfileRecentQuery {
  query_key: string;
  query_ts: number;
  confirmed_ts?: number | null;
}

export type ProfileStatus = "cold" | "learning" | "established";

export interface ProfileTopicEvidence {
  topic_id: number;
  display_name: string;
  score: number;
  positive_score: number;
  negative_score: number;
  positive_evidence_count: number;
  negative_evidence_count: number;
  signal_counts: Record<string, number>;
  last_signal_type?: string | null;
  last_event_ts: number;
}

export interface ProfileTermLayer {
  interests: ProfileTopicEvidence[];
  reduced_topics: ProfileTopicEvidence[];
}

export interface ProfileResponse {
  user_id: number;
  profile_version: "v2";
  status: ProfileStatus;
  confidence: number;
  evidence_count: number;
  short_term: ProfileTermLayer;
  long_term: ProfileTermLayer;
  recent_clicked_news: ProfileRecentClick[];
  recent_queries: ProfileRecentQuery[];
  last_updated_at?: string | null;
}

export interface DebugVectorSummary {
  vector_key_count: number;
  top_contributing_topics: ProfileTopicWeight[];
}

export interface DebugProfileResponse {
  user_id: number;
  cold_start_seed_key: string;
  behavior_score: number;
  topic_weights: ProfileTopicWeight[];
  recent_clicked_articles: ProfileRecentClick[];
  recent_queries: ProfileRecentQuery[];
  vector_summary?: DebugVectorSummary;
}

export type EventTrackType =
  | "feed_impression"
  | "detail_view"
  | "dwell"
  | "upvote"
  | "downvote"
  | "share"
  | "recommendation_click"
  | "search_result_click";

export interface EventTrackRequest {
  event_id?: string | null;
  user_id: number;
  event_type: EventTrackType;
  surface: string;
  article_id?: number | null;
  query_key?: string | null;
  request_id?: string | null;
  sponsored_delivery_id?: string | null;
  dwell_ms?: number | null;
  debug?: boolean;
}

export interface EventTrackResponse {
  ok: boolean;
  event_type: EventTrackType;
  profile_updated: boolean;
  behavior_score: number | null;
}
