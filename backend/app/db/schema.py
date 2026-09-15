from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, JSONB

from backend.app.live_news.topic_schema import define_topic_tables

metadata = MetaData(
    naming_convention={
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ix": "idx_%(table_name)s_%(column_0_name)s",
        "ck": "chk_%(table_name)s_%(constraint_name)s",
    }
)


topic = Table(
    "topic",
    metadata,
    Column("topic_id", BigInteger, primary_key=True, autoincrement=False),
    Column("source_space", String(16), nullable=False, server_default=text("'mind'")),
    Column("topic_key", String(512), nullable=False),
    Column("display_name", String(128)),
    Column("news_count", Integer, nullable=False, server_default=text("0")),
    Column("source", String(32), nullable=False, server_default=text("'mind_small'")),
    UniqueConstraint("source_space", "topic_key", name="uq_topic_space_key"),
    CheckConstraint("source_space IN ('mind', 'live')", name="source_space"),
    comment="News category dimension.",
)

app_user = Table(
    "app_user",
    metadata,
    Column("user_id", BigInteger, primary_key=True, autoincrement=False),
    Column("display_name", String(128)),
    Column("register_ts", BigInteger),
    Column("gender", SmallInteger),
    Column("login_frequency", SmallInteger),
    Column("follower_count", Integer, nullable=False, server_default=text("0")),
    Column("followed_topic_count", Integer, nullable=False, server_default=text("0")),
    Column("comment_count", Integer, nullable=False, server_default=text("0")),
    Column("thanks_received_count", Integer, nullable=False, server_default=text("0")),
    Column("likes_received_count", Integer, nullable=False, server_default=text("0")),
    Column("province", String(64)),
    Column("city", String(64)),
    Column("followed_topic_ids_json", JSONB),
    Column("is_demo_user", Boolean, nullable=False, server_default=text("false")),
    Column("source", String(32), nullable=False, server_default=text("'mind_small'")),
    comment="Research users and MIND-derived profile identities.",
)

auth_user_id_sequence = Table(
    "auth_user_id_sequence",
    metadata,
    Column("sequence_key", String(64), primary_key=True),
    Column("next_user_id", BigInteger, nullable=False),
    comment="Locked ID allocation for users created by the application.",
)

user_account = Table(
    "user_account",
    metadata,
    Column(
        "user_id",
        BigInteger,
        ForeignKey("app_user.user_id", name="fk_user_account_user"),
        primary_key=True,
    ),
    Column("email", String(254), nullable=False),
    Column("password_hash", String(255), nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("email", name="uq_user_account_email"),
    comment="Login credentials linked one-to-one with recommendation users.",
)

event_idempotency = Table(
    "event_idempotency",
    metadata,
    Column("external_event_id", String(128), primary_key=True),
    Column("payload_fingerprint", String(64), nullable=False),
    Column(
        "user_id",
        BigInteger,
        ForeignKey("app_user.user_id", name="fk_event_idempotency_user"),
        nullable=False,
    ),
    Column("event_type", String(64), nullable=False),
    Column("source_space", String(16), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("source_space IN ('mind', 'live')", name="source_space"),
    Index("idx_event_idempotency_user_created", "user_id", "created_at"),
    comment="Atomic claim table for retry-safe event processing.",
)

feed_request = Table(
    "feed_request",
    metadata,
    Column("request_id", String(128), primary_key=True),
    Column("source_space", String(16), nullable=False),
    Column(
        "user_id",
        BigInteger,
        ForeignKey("app_user.user_id", name="fk_feed_request_user"),
        nullable=False,
    ),
    Column("page_size", Integer, nullable=False),
    Column("debug", Boolean, nullable=False),
    Column("include_sponsored", Boolean, nullable=False),
    Column("experiment_arm", String(64), nullable=False),
    Column("as_of_ts", BigInteger),
    Column("category", String(64)),
    Column("session_id", String(128), nullable=False),
    Column("page_number", Integer, nullable=False, server_default=text("0")),
    Column("cursor_token", String(128)),
    Column("returned_news_ids_json", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("source_space IN ('mind', 'live')", name="source_space"),
    Index("idx_feed_request_user_created", "user_id", "created_at"),
    Index("uq_feed_request_cursor_token", "cursor_token", unique=True),
    Index("idx_feed_request_session_page", "session_id", "page_number"),
    Index("idx_feed_request_space_session", "source_space", "session_id", "page_number"),
    Index("idx_feed_request_category", "category"),
    comment="Idempotency claim for feed loads that may reserve sponsored delivery.",
)

live_news = Table(
    "live_news",
    metadata,
    Column("article_id", String(64), primary_key=True),
    Column("canonical_url", Text, nullable=False, unique=True),
    Column("source_external_id", Text),
    Column("title", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("image_url", Text),
    Column("publisher", Text, nullable=False),
    Column("source_domain", Text, nullable=False),
    Column("language", String(8), nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("published_at_quality", String(32), nullable=False),
    Column("discovered_at", DateTime(timezone=True), nullable=False),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("raw_metadata_json", JSONB, nullable=False),
    Column("body_text", Text),
    Column("body_source", String(32)),
    Column("body_status", String(24), nullable=False, server_default=text("'metadata_only'")),
    Column("body_fetched_at", DateTime(timezone=True)),
    Column("body_content_hash", String(64)),
    Column("body_extraction_version", String(32)),
    Column("content_rights", String(24), nullable=False, server_default=text("'link_only'")),
    Column(
        "body_access_scope",
        String(24),
        nullable=False,
        server_default=text("'public'"),
    ),
    Column("body_document", JSONB),
    Column("body_document_version", String(32)),
    Column("body_document_hash", String(64)),
    Column(
        "body_structure_status",
        String(24),
        nullable=False,
        server_default=text("'missing'"),
    ),
    Column("body_structure_updated_at", DateTime(timezone=True)),
    Column("link_failure_count", Integer, nullable=False, server_default=text("0")),
    Column("last_link_check_at", DateTime(timezone=True)),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("language IN ('zh', 'en')", name="language"),
    CheckConstraint(
        "published_at_quality IN ('gdelt_unverified', 'publisher', 'unknown')",
        name="published_at_quality",
    ),
    CheckConstraint("status IN ('active', 'inactive')", name="status"),
    CheckConstraint(
        "body_source IS NULL OR body_source IN ('guardian_api', 'rss', 'html')",
        name="body_source",
    ),
    CheckConstraint(
        "body_status IN ('metadata_only', 'pending', 'available', 'blocked', 'failed')",
        name="body_status",
    ),
    CheckConstraint(
        "content_rights IN ('full_text', 'excerpt_only', 'link_only')",
        name="content_rights",
    ),
    CheckConstraint(
        "body_access_scope IN ('public', 'local_research')",
        name="body_access_scope",
    ),
    CheckConstraint(
        "body_structure_status IN ('missing', 'pending', 'available', 'failed', 'blocked')",
        name="body_structure_status",
    ),
    CheckConstraint(
        "(body_status = 'available' AND body_text IS NOT NULL "
        "AND body_source IS NOT NULL AND body_fetched_at IS NOT NULL "
        "AND body_content_hash IS NOT NULL AND body_extraction_version IS NOT NULL) "
        "OR (body_status <> 'available' AND body_text IS NULL)",
        name="body_integrity",
    ),
    comment="Canonical catalog of continuously discovered live news articles.",
)
Index(
    "idx_live_news_active_discovered",
    live_news.c.status,
    live_news.c.discovered_at.desc(),
    live_news.c.article_id,
)
Index(
    "idx_live_news_language_discovered",
    live_news.c.language,
    live_news.c.discovered_at.desc(),
    live_news.c.article_id,
)
Index(
    "idx_live_news_domain_discovered",
    live_news.c.source_domain,
    live_news.c.discovered_at.desc(),
    live_news.c.article_id,
)
Index("idx_live_news_content_hash", live_news.c.content_hash)

live_news_content_job = Table(
    "live_news_content_job",
    metadata,
    Column(
        "article_id",
        String(64),
        ForeignKey("live_news.article_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("status", String(16), nullable=False, server_default=text("'pending'")),
    Column("attempt_count", Integer, nullable=False, server_default=text("0")),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False),
    Column("claimed_at", DateTime(timezone=True)),
    Column("worker_id", String(128)),
    Column("last_error_code", String(64)),
    Column("last_error_detail", Text),
    Column(
        "target_extraction_version",
        String(32),
        nullable=False,
        server_default=text("'structured-1'"),
    ),
    Column(
        "requested_by",
        String(24),
        nullable=False,
        server_default=text("'ingest'"),
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("attempt_count >= 0", name="attempt_count"),
    CheckConstraint(
        "status IN ('pending', 'fetching', 'completed', 'blocked', 'failed')",
        name="status",
    ),
    CheckConstraint(
        "requested_by IN ('ingest', 'detail_on_demand', 'operator_backfill', 'version_upgrade')",
        name="requested_by",
    ),
    Index("idx_live_news_content_job_due", "status", "next_attempt_at"),
    comment="Durable acquisition queue for Live article body content.",
)

live_news_content_asset = Table(
    "live_news_content_asset",
    metadata,
    Column("asset_id", String(64), primary_key=True),
    Column(
        "article_id",
        String(64),
        ForeignKey("live_news.article_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("block_id", String(64), nullable=False),
    Column("source_url", Text, nullable=False),
    Column("storage_key", Text),
    Column("display_url", Text),
    Column("mime_type", String(64)),
    Column("width", Integer),
    Column("height", Integer),
    Column("alt_text", Text),
    Column("caption", Text),
    Column("credit", Text),
    Column("content_hash", String(64)),
    Column("cache_status", String(20), nullable=False, server_default=text("'remote_only'")),
    Column("last_error_code", String(64)),
    Column("fetched_at", DateTime(timezone=True)),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("width IS NULL OR width > 0", name="width"),
    CheckConstraint("height IS NULL OR height > 0", name="height"),
    CheckConstraint(
        "cache_status IN ('remote_only', 'pending', 'cached', 'failed', 'omitted')",
        name="cache_status",
    ),
    UniqueConstraint("article_id", "block_id", name="article_block"),
    Index("idx_live_news_content_asset_article", "article_id", "block_id"),
    comment="Ordered image metadata and optional cache references for Live articles.",
)

live_news_source_checkpoint = Table(
    "live_news_source_checkpoint",
    metadata,
    Column("source_name", String(64), primary_key=True),
    Column("last_batch_time", DateTime(timezone=True)),
    Column("last_etag", String(255)),
    Column("last_modified", String(255)),
    Column("last_success_at", DateTime(timezone=True)),
    Column("last_error", Text),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    comment="Per-source cursors and health state for live news discovery.",
)

live_news_import = Table(
    "live_news_import",
    metadata,
    Column("batch_id", String(128), primary_key=True),
    Column("source_url", Text, nullable=False),
    Column("source_sha256", String(64)),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("raw_count", Integer, nullable=False, server_default=text("0")),
    Column("accepted_count", Integer, nullable=False, server_default=text("0")),
    Column("rejected_count", Integer, nullable=False, server_default=text("0")),
    Column(
        "rejection_summary_json",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    ),
    Column("status", String(16), nullable=False),
    Column("error_message", Text),
    CheckConstraint("status IN ('fetching', 'completed', 'failed')", name="status"),
    comment="Audit record for each raw live-news import batch.",
)

mind_news = Table(
    "mind_news",
    metadata,
    Column("news_id", String(32), primary_key=True, autoincrement=False),
    Column("category", Text, nullable=False),
    Column("subcategory", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("abstract", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("title_entities", JSONB, nullable=False),
    Column("abstract_entities", JSONB, nullable=False),
    CheckConstraint("news_id ~ '^N[0-9]+$'", name="news_id"),
    CheckConstraint("jsonb_typeof(title_entities) = 'array'", name="title_entities_array"),
    CheckConstraint("jsonb_typeof(abstract_entities) = 'array'", name="abstract_entities_array"),
    Index("idx_mind_news_category", "category"),
    Index("idx_mind_news_subcategory", "subcategory"),
    comment="Canonical MIND news.tsv rows with exactly the eight source fields.",
)

mind_news_topic = Table(
    "mind_news_topic",
    metadata,
    Column(
        "news_id",
        String(32),
        ForeignKey("mind_news.news_id", name="fk_mind_news_topic_news", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "topic_id",
        BigInteger,
        ForeignKey("topic.topic_id", name="fk_mind_news_topic_topic", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("source_rank", SmallInteger, nullable=False),
    PrimaryKeyConstraint("news_id", "topic_id"),
    UniqueConstraint("news_id", "source_rank", name="uq_mind_news_topic_news_rank"),
    CheckConstraint("source_rank IN (0, 1)", name="source_rank"),
    Index("idx_mind_news_topic_topic", "topic_id", "news_id"),
    comment="Exact category and parent-qualified subcategory links for canonical MIND news.",
)

mind_catalog_import = Table(
    "mind_catalog_import",
    metadata,
    Column("normalized_fingerprint", String(64), primary_key=True),
    Column("dataset", String(32), nullable=False),
    Column("news_count", Integer, nullable=False),
    Column("train_request_count", Integer, nullable=False),
    Column("train_impression_count", BigInteger, nullable=False),
    Column("train_click_count", BigInteger, nullable=False),
    Column("articles_sha256", String(64), nullable=False),
    Column("train_impressions_sha256", String(64), nullable=False),
    Column(
        "imported_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("news_count >= 0", name="news_count"),
    CheckConstraint("train_request_count >= 0", name="train_request_count"),
    CheckConstraint("train_impression_count >= 0", name="train_impression_count"),
    CheckConstraint("train_click_count >= 0", name="train_click_count"),
    comment="Fingerprint and row-count provenance for an imported normalized MIND catalog.",
)

mind_news_stats = Table(
    "mind_news_stats",
    metadata,
    Column(
        "news_id",
        String(32),
        ForeignKey("mind_news.news_id", name="fk_mind_news_stats_news"),
        primary_key=True,
    ),
    Column("first_seen_ts", BigInteger),
    Column("click_count", BigInteger, nullable=False, server_default=text("0")),
    Column("impression_count", BigInteger, nullable=False, server_default=text("0")),
    Column("hot_score", DOUBLE_PRECISION, nullable=False, server_default=text("0")),
    Column(
        "normalized_fingerprint",
        String(64),
        ForeignKey(
            "mind_catalog_import.normalized_fingerprint",
            name="fk_mind_news_stats_import",
        ),
        nullable=False,
    ),
    CheckConstraint("click_count >= 0", name="click_count"),
    CheckConstraint("impression_count >= click_count", name="impression_count"),
    CheckConstraint("hot_score >= 0", name="hot_score"),
    Index("idx_mind_news_stats_hot", "hot_score", "news_id"),
    comment="Train-only serving statistics kept separate from canonical MIND facts.",
)

query_topic_map = Table(
    "query_topic_map",
    metadata,
    Column("source_space", String(16), nullable=False, server_default=text("'mind'")),
    Column("query_key", String(512), nullable=False),
    Column("display_query", String(255)),
    Column("query_tokens_json", JSONB),
    Column(
        "topic_id",
        BigInteger,
        ForeignKey("topic.topic_id", name="fk_query_topic_topic"),
        nullable=False,
    ),
    Column("score", Numeric(10, 6), nullable=False),
    Column("evidence_query_count", Integer, nullable=False, server_default=text("0")),
    Column("evidence_user_count", Integer, nullable=False, server_default=text("0")),
    Column("match_rank", Integer, nullable=False, server_default=text("0")),
    Column(
        "source_method",
        String(64),
        nullable=False,
        server_default=text("'offline_user_topic_cooccurrence'"),
    ),
    PrimaryKeyConstraint("source_space", "query_key", "topic_id"),
    CheckConstraint("source_space IN ('mind', 'live')", name="source_space"),
    Index("idx_query_topic_topic", "topic_id"),
    Index("idx_query_topic_rank", "query_key", "match_rank"),
    comment="English query aliases and category mappings.",
)

system_profile_seed = Table(
    "system_profile_seed",
    metadata,
    Column("seed_key", String(64), primary_key=True),
    Column("source_space", String(16), nullable=False, server_default=text("'mind'")),
    Column("topic_weights_json", JSONB, nullable=False),
    Column("recent_clicked_news_json", JSONB),
    Column("recent_queries_json", JSONB),
    Column("behavior_score", DOUBLE_PRECISION, nullable=False, server_default=text("0")),
    Column("notes", String(255)),
    CheckConstraint("source_space IN ('mind', 'live')", name="source_space"),
    comment="Reusable cold-start or bootstrap profile seeds.",
)

user_profile = Table(
    "user_profile",
    metadata,
    Column(
        "user_id",
        BigInteger,
        ForeignKey("app_user.user_id", name="fk_user_profile_user"),
        nullable=False,
    ),
    Column("source_space", String(16), nullable=False, server_default=text("'mind'")),
    Column(
        "cold_start_seed_key",
        String(64),
        ForeignKey("system_profile_seed.seed_key", name="fk_user_profile_seed"),
        nullable=False,
        server_default=text("'cold_start_default'"),
    ),
    Column("topic_weights_json", JSONB, nullable=False),
    Column("recent_clicked_news_json", JSONB, nullable=False),
    Column("recent_queries_json", JSONB, nullable=False),
    Column("behavior_score", DOUBLE_PRECISION, nullable=False, server_default=text("0")),
    Column("user_vector_json", JSONB),
    Column("notes", String(255)),
    Column("last_event_ts", BigInteger),
    Column("profile_v2_evidence_count", Integer, nullable=False, server_default=text("0")),
    Column("profile_v2_last_event_ts", BigInteger),
    Column("profile_reset_before_ts", BigInteger),
    Column("profile_reset_before_event_id", BigInteger),
    Column("profile_v2_updated_at", DateTime(timezone=True)),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    PrimaryKeyConstraint("user_id", "source_space"),
    CheckConstraint("source_space IN ('mind', 'live')", name="source_space"),
    Index("idx_user_profile_seed", "cold_start_seed_key"),
    comment="Single-table user profile storage.",
)

user_topic_profile = Table(
    "user_topic_profile",
    metadata,
    Column(
        "user_id",
        BigInteger,
        ForeignKey("app_user.user_id", name="fk_user_topic_profile_user"),
        nullable=False,
    ),
    Column("source_space", String(16), nullable=False, server_default=text("'mind'")),
    Column(
        "topic_id",
        BigInteger,
        ForeignKey("topic.topic_id", name="fk_user_topic_profile_topic"),
        nullable=False,
    ),
    Column("short_positive_score", DOUBLE_PRECISION, nullable=False, server_default=text("0")),
    Column("short_negative_score", DOUBLE_PRECISION, nullable=False, server_default=text("0")),
    Column("long_positive_score", DOUBLE_PRECISION, nullable=False, server_default=text("0")),
    Column("long_negative_score", DOUBLE_PRECISION, nullable=False, server_default=text("0")),
    Column("positive_evidence_count", Integer, nullable=False, server_default=text("0")),
    Column("negative_evidence_count", Integer, nullable=False, server_default=text("0")),
    Column(
        "evidence_counts_json",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    ),
    Column("last_signal_type", String(32)),
    Column("last_event_ts", BigInteger, nullable=False),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "short_positive_score >= 0 AND short_negative_score >= 0",
        name="short_scores",
    ),
    CheckConstraint(
        "long_positive_score >= 0 AND long_negative_score >= 0",
        name="long_scores",
    ),
    CheckConstraint(
        "positive_evidence_count >= 0 AND negative_evidence_count >= 0",
        name="evidence_counts",
    ),
    CheckConstraint("source_space IN ('mind', 'live')", name="source_space"),
    PrimaryKeyConstraint("user_id", "source_space", "topic_id"),
    Index("idx_user_topic_profile_user", "user_id"),
    comment="Short- and long-term explainable topic projection for profile V2.",
)

sponsored_campaign = Table(
    "sponsored_campaign",
    metadata,
    Column("campaign_id", BigInteger, primary_key=True, autoincrement=False),
    Column("campaign_name", String(128), nullable=False),
    Column("status", String(16), nullable=False, server_default=text("'draft'")),
    Column("start_ts", BigInteger, nullable=False),
    Column("end_ts", BigInteger, nullable=False),
    Column("daily_budget_micros", BigInteger, nullable=False),
    Column("pacing_mode", String(16), nullable=False, server_default=text("'even'")),
    Column("frequency_cap_per_user_per_day", Integer, nullable=False, server_default=text("2")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("status IN ('draft', 'active', 'paused', 'ended')", name="campaign_status"),
    CheckConstraint("pacing_mode IN ('even', 'asap')", name="campaign_pacing"),
    Index("idx_sponsored_campaign_status_window", "status", "start_ts", "end_ts"),
    comment="Synthetic local sponsored campaigns; not a billing source of truth.",
)

sponsored_campaign_topic = Table(
    "sponsored_campaign_topic",
    metadata,
    Column(
        "campaign_id",
        BigInteger,
        ForeignKey("sponsored_campaign.campaign_id", name="fk_sponsored_campaign_topic_campaign"),
        nullable=False,
    ),
    Column(
        "topic_id",
        BigInteger,
        ForeignKey("topic.topic_id", name="fk_sponsored_campaign_topic_topic"),
        nullable=False,
    ),
    PrimaryKeyConstraint("campaign_id", "topic_id"),
    Index("idx_sponsored_campaign_topic_topic", "topic_id"),
    comment="Normalized topic eligibility for sponsored campaigns.",
)

sponsored_creative = Table(
    "sponsored_creative",
    metadata,
    Column("creative_id", BigInteger, primary_key=True, autoincrement=False),
    Column(
        "campaign_id",
        BigInteger,
        ForeignKey("sponsored_campaign.campaign_id", name="fk_sponsored_creative_campaign"),
        nullable=False,
    ),
    Column(
        "news_id",
        String(32),
        ForeignKey("mind_news.news_id", name="fk_sponsored_creative_news"),
        nullable=False,
    ),
    Column("status", String(16), nullable=False, server_default=text("'active'")),
    Column("bid_micros", BigInteger, nullable=False),
    Column("predicted_ctr", Numeric(10, 8), nullable=False),
    Column("quality_score", Numeric(10, 8), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("campaign_id", "news_id", name="uq_sponsored_creative_campaign_news"),
    CheckConstraint("status IN ('active', 'paused')", name="creative_status"),
    CheckConstraint("bid_micros > 0", name="bid"),
    CheckConstraint("predicted_ctr >= 0 AND predicted_ctr <= 1", name="ctr"),
    CheckConstraint("quality_score >= 0 AND quality_score <= 1", name="quality"),
    Index("idx_sponsored_creative_news", "news_id"),
    comment="Sponsored creatives backed by canonical MIND news rows.",
)

sponsored_campaign_daily_state = Table(
    "sponsored_campaign_daily_state",
    metadata,
    Column(
        "campaign_id",
        BigInteger,
        ForeignKey("sponsored_campaign.campaign_id", name="fk_sponsored_daily_state_campaign"),
        nullable=False,
    ),
    Column("budget_date", Date, nullable=False),
    Column("expected_spend_micros", BigInteger, nullable=False, server_default=text("0")),
    Column("served_impression_count", Integer, nullable=False, server_default=text("0")),
    Column("confirmed_impression_count", Integer, nullable=False, server_default=text("0")),
    Column("click_count", Integer, nullable=False, server_default=text("0")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    PrimaryKeyConstraint("campaign_id", "budget_date"),
    comment="Daily synthetic expected-spend and delivery counters.",
)

sponsored_user_daily_frequency = Table(
    "sponsored_user_daily_frequency",
    metadata,
    Column(
        "campaign_id",
        BigInteger,
        ForeignKey("sponsored_campaign.campaign_id", name="fk_sponsored_frequency_campaign"),
        nullable=False,
    ),
    Column(
        "user_id",
        BigInteger,
        ForeignKey("app_user.user_id", name="fk_sponsored_frequency_user"),
        nullable=False,
    ),
    Column("budget_date", Date, nullable=False),
    Column("served_impression_count", Integer, nullable=False, server_default=text("0")),
    Column("last_served_ts", BigInteger),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    PrimaryKeyConstraint("campaign_id", "user_id", "budget_date"),
    Index("idx_sponsored_frequency_user_date", "user_id", "budget_date"),
    comment="Per-user daily sponsored frequency-cap state.",
)

sponsored_delivery = Table(
    "sponsored_delivery",
    metadata,
    Column("delivery_id", String(128), primary_key=True),
    Column("request_id", String(128), nullable=False),
    Column(
        "user_id",
        BigInteger,
        ForeignKey("app_user.user_id", name="fk_sponsored_delivery_user"),
        nullable=False,
    ),
    Column(
        "campaign_id",
        BigInteger,
        ForeignKey("sponsored_campaign.campaign_id", name="fk_sponsored_delivery_campaign"),
        nullable=False,
    ),
    Column(
        "creative_id",
        BigInteger,
        ForeignKey("sponsored_creative.creative_id", name="fk_sponsored_delivery_creative"),
        nullable=False,
    ),
    Column(
        "news_id",
        String(32),
        ForeignKey("mind_news.news_id", name="fk_sponsored_delivery_news"),
        nullable=False,
    ),
    Column("slot_position", SmallInteger, nullable=False),
    Column("budget_date", Date, nullable=False),
    Column("expected_spend_micros", BigInteger, nullable=False),
    Column("served_ts", BigInteger, nullable=False),
    Column("confirmed_impression_ts", BigInteger),
    Column("clicked_ts", BigInteger),
    Column("delivery_status", String(16), nullable=False, server_default=text("'served'")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("request_id", "creative_id", name="uq_sponsored_delivery_request_creative"),
    CheckConstraint(
        "delivery_status IN ('served', 'confirmed', 'clicked')", name="delivery_status"
    ),
    Index("idx_sponsored_delivery_user_ts", "user_id", "served_ts"),
    Index("idx_sponsored_delivery_campaign_ts", "campaign_id", "served_ts"),
    comment="Server-side sponsored serving ledger and client confirmation state.",
)

user_event = Table(
    "user_event",
    metadata,
    Column("event_id", BigInteger, Identity(), primary_key=True),
    Column("external_event_id", String(128)),
    Column("source_space", String(16), nullable=False),
    Column(
        "user_id",
        BigInteger,
        ForeignKey("app_user.user_id", name="fk_user_event_user"),
        nullable=False,
    ),
    Column("event_type", String(32), nullable=False),
    Column("article_id", String(64)),
    Column(
        "sponsored_delivery_id",
        String(128),
        ForeignKey("sponsored_delivery.delivery_id", name="fk_user_event_sponsored_delivery"),
    ),
    Column(
        "campaign_id",
        BigInteger,
        ForeignKey("sponsored_campaign.campaign_id", name="fk_user_event_campaign"),
    ),
    Column(
        "creative_id",
        BigInteger,
        ForeignKey("sponsored_creative.creative_id", name="fk_user_event_creative"),
    ),
    Column("query_key", String(512)),
    Column("query_tokens_json", JSONB),
    Column("topic_ids_json", JSONB),
    Column("surface", String(32), nullable=False, server_default=text("'feed'")),
    Column("request_id", String(128)),
    Column("dwell_ms", BigInteger),
    Column("derived_from_raw", Boolean, nullable=False, server_default=text("false")),
    Column(
        "source_confidence",
        String(16),
        nullable=False,
        server_default=text("'not_applicable'"),
    ),
    Column("event_ts", BigInteger, nullable=False),
    Column("debug_payload_json", JSONB),
    UniqueConstraint("external_event_id", name="uq_user_event_external_event_id"),
    CheckConstraint(
        "event_type IN ('search_query', 'recommendation_click', 'search_result_click', "
        "'feed_impression', 'detail_view', 'dwell', 'upvote', 'downvote', 'share', "
        "'outbound_click')",
        name="event_type",
    ),
    CheckConstraint(
        "source_confidence IN ('confirmed', 'heuristic', 'not_applicable')",
        name="source_confidence",
    ),
    CheckConstraint(
        "event_type = 'search_query' OR article_id IS NOT NULL",
        name="article_required",
    ),
    CheckConstraint(
        "article_id IS NULL OR "
        "(source_space = 'mind' AND article_id ~ '^N[0-9]+$') OR "
        "(source_space = 'live' AND article_id ~ '^L[0-9a-f]{32}$')",
        name="article_space",
    ),
    CheckConstraint("source_space IN ('mind', 'live')", name="source_space"),
    Index("idx_user_event_user_ts", "user_id", "event_ts"),
    Index("idx_user_event_space_user_ts", "source_space", "user_id", "event_ts"),
    Index("idx_user_event_type_ts", "event_type", "event_ts"),
    Index("idx_user_event_campaign_ts", "campaign_id", "event_ts"),
    comment="Event log for closed-loop updates and replay.",
)

event_outbox = Table(
    "event_outbox",
    metadata,
    Column("outbox_id", BigInteger, Identity(), primary_key=True),
    Column("event_id", String(128), nullable=False),
    Column("topic", String(255), nullable=False),
    Column("message_key", String(255), nullable=False),
    Column("payload_fingerprint", String(64), nullable=False),
    Column("payload_json", JSONB, nullable=False),
    Column("status", String(16), nullable=False, server_default=text("'pending'")),
    Column("attempt_count", Integer, nullable=False, server_default=text("0")),
    Column("available_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("published_at", DateTime),
    Column("last_error", Text),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("event_id", "topic", name="uq_event_outbox_event_topic"),
    CheckConstraint(
        "status IN ('pending', 'publishing', 'published', 'dead')", name="outbox_status"
    ),
    Index("idx_event_outbox_ready", "status", "available_at", "outbox_id"),
    comment="Transactional Kafka outbox with at-least-once delivery.",
)

worker_heartbeat = Table(
    "worker_heartbeat",
    metadata,
    Column("worker_name", String(64), primary_key=True),
    Column("last_seen_at", DateTime, nullable=False),
    Column("last_progress_at", DateTime),
    Column("lag_messages", BigInteger, nullable=False, server_default=text("0")),
    Column("last_error", Text),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    comment="Readiness heartbeat and progress state for local Kafka workers.",
)

define_topic_tables(metadata)
