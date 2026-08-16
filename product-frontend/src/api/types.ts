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

export interface CategoryItem {
  key: string;
  news_count: number;
}

export interface CategoryListResponse {
  items: CategoryItem[];
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
  news_id: string;
  title: string;
  abstract: string;
  url: string;
  source_domain: string;
  category: string;
  subcategory: string;
  categories: TopicCard[];
  title_entities: ArticleEntity[];
  abstract_entities: ArticleEntity[];
}

export type ArticleEntityType = "person" | "organization" | "location" | "other";

export interface ArticleEntity {
  label: string;
  entity_type: ArticleEntityType;
  type_code: string;
  wikidata_id: string | null;
  confidence: number | null;
  surface_forms: string[];
}

export interface FeedItemScores {
  base_recall_score: number;
  personalized_topic_score: number;
  default_topic_score: number;
  topic_match_score: number;
  query_recall_boost: number;
  final_score: number;
  sponsored_score?: number | null;
}

export interface SponsoredFeedMetadata {
  delivery_id: string;
  campaign_id: number;
  creative_id: number;
  label: string;
}

export interface FeedItem {
  news_id: string;
  title: string;
  abstract: string;
  url: string;
  source_domain: string;
  category: string;
  subcategory: string;
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
  next_cursor: string | null;
  has_more: boolean;
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
  news_id: string;
  title: string;
  abstract: string;
  url: string;
  source_domain: string;
  category: string;
  subcategory: string;
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
  news_id: string;
  title: string | null;
  click_ts: number;
}

export interface ProfileRecentQuery {
  query_key: string;
  query_ts: number;
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
  recent_clicked_news: ProfileRecentClick[];
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
  news_id?: string | null;
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
