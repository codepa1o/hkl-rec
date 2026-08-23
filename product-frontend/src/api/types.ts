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
  source_space: NewsSpace;
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
  source_space: NewsSpace;
  items: SuggestionItem[];
}

export interface ArticleCardResponse {
  source_space: NewsSpace;
  article_id: string;
  news_id?: string | null;
  title: string;
  abstract: string;
  url: string;
  source_domain: string;
  category: string;
  subcategory: string;
  categories: TopicCard[];
  title_entities: ArticleEntity[];
  abstract_entities: ArticleEntity[];
  image_url?: string | null;
  publisher?: string | null;
  language?: "zh" | "en" | null;
  published_at?: string | null;
  discovered_at?: string | null;
  body_text?: string | null;
  body_status?: "metadata_only" | "pending" | "available" | "blocked" | "failed";
  body_source?: "guardian_api" | "rss" | "html" | null;
  content_rights?: "full_text" | "excerpt_only" | "link_only";
  body_document?: StructuredBodyDocument | null;
  body_structure_status?: BodyStructureStatus;
  body_document_version?: string | null;
}

export type BodyStructureStatus =
  | "missing"
  | "pending"
  | "available"
  | "failed"
  | "blocked";

export interface ParagraphContentBlock {
  id: string;
  type: "paragraph";
  text: string;
}

export interface HeadingContentBlock {
  id: string;
  type: "heading";
  level: 2 | 3 | 4;
  text: string;
}

export interface QuoteContentBlock {
  id: string;
  type: "quote";
  text: string;
  attribution: string | null;
}

export interface ListContentBlock {
  id: string;
  type: "list";
  ordered: boolean;
  items: string[];
}

export interface ImageContentBlock {
  id: string;
  type: "image";
  asset_id: string;
  source_url: string;
  display_url: string | null;
  alt: string | null;
  caption: string | null;
  credit: string | null;
  width: number | null;
  height: number | null;
  mime_type: string | null;
  cache_status: "remote_only" | "pending" | "cached" | "failed" | "omitted";
}

export type StructuredContentBlock =
  | ParagraphContentBlock
  | HeadingContentBlock
  | QuoteContentBlock
  | ListContentBlock
  | ImageContentBlock;

export interface StructuredBodyDocument {
  schema_version: 1;
  extraction_version: string;
  source: "guardian_api" | "rss" | "html";
  blocks: StructuredContentBlock[];
}

export interface ContentEnsureResponse {
  article_id: string;
  status: BodyStructureStatus;
  enqueued: boolean;
  retry_after_seconds: number | null;
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
  source_space: NewsSpace;
  article_id: string;
  news_id?: string | null;
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
  image_url?: string | null;
  publisher?: string | null;
  language?: "zh" | "en" | null;
  published_at?: string | null;
  discovered_at?: string | null;
}

export interface FeedResponse {
  source_space: NewsSpace;
  user_id: number;
  request_id: string;
  items: FeedItem[];
  next_cursor: string | null;
  has_more: boolean;
  debug?: unknown;
}

export interface FeedUpdateStatusResponse {
  source_space: NewsSpace;
  has_updates: boolean;
  current_watermark: string | null;
}

export interface SearchItemScores {
  topic_match_score: number;
  bm25_score: number;
  dense_score: number;
  hybrid_score: number;
  final_score: number;
}

export interface SearchItem {
  source_space: NewsSpace;
  article_id: string;
  news_id?: string | null;
  title: string;
  abstract: string;
  url: string;
  source_domain: string;
  category: string;
  subcategory: string;
  categories: TopicCard[];
  scores: SearchItemScores;
  image_url?: string | null;
  publisher?: string | null;
  language?: "zh" | "en" | null;
  published_at?: string | null;
  discovered_at?: string | null;
}

export interface SearchResponse {
  source_space: NewsSpace;
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
  source_space: NewsSpace;
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
  source_space: NewsSpace;
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
  | "search_result_click"
  | "outbound_click";

export interface EventTrackRequest {
  event_id?: string | null;
  user_id: number;
  source_space?: NewsSpace;
  event_type: EventTrackType;
  surface: string;
  news_id?: string | null;
  article_id?: string | null;
  query_key?: string | null;
  request_id?: string | null;
  sponsored_delivery_id?: string | null;
  dwell_ms?: number | null;
  debug?: boolean;
}

export interface EventTrackResponse {
  ok: boolean;
  event_type: EventTrackType;
  source_space: NewsSpace;
  profile_updated: boolean;
  behavior_score: number | null;
}
export type NewsSpace = "mind" | "live";
export type LiveLanguage = "all" | "zh" | "en";

export interface NewsSpaceCapability {
  source_space: NewsSpace;
  enabled: boolean;
}

export interface NewsSpaceListResponse {
  items: NewsSpaceCapability[];
}
