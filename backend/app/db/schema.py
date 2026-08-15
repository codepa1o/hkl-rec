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
    Column("display_name", String(128)),
    Column("answer_count", Integer, nullable=False, server_default=text("0")),
    Column("question_count", Integer, nullable=False, server_default=text("0")),
    Column("source", String(32), nullable=False, server_default=text("'mind_small'")),
    comment="News category dimension.",
)

author = Table(
    "author",
    metadata,
    Column("author_id", BigInteger, primary_key=True, autoincrement=False),
    Column("display_name", String(128)),
    Column("is_excellent_author", Boolean, nullable=False, server_default=text("false")),
    Column("follower_count", Integer, nullable=False, server_default=text("0")),
    Column("is_excellent_answerer", Boolean, nullable=False, server_default=text("false")),
    Column("source", String(32), nullable=False, server_default=text("'mind_small'")),
    comment="Source-domain compatibility records.",
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
    Column("answer_count", Integer, nullable=False, server_default=text("0")),
    Column("question_count", Integer, nullable=False, server_default=text("0")),
    Column("comment_count", Integer, nullable=False, server_default=text("0")),
    Column("thanks_received_count", Integer, nullable=False, server_default=text("0")),
    Column("likes_received_count", Integer, nullable=False, server_default=text("0")),
    Column("province", String(64)),
    Column("city", String(64)),
    Column("followed_topic_ids_json", JSONB),
    Column("is_demo_user", Boolean, nullable=False, server_default=text("false")),
    Column("source", String(32), nullable=False, server_default=text("'mind_small'")),
    comment="MIND-derived demo users and compatibility records.",
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
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Index("idx_event_idempotency_user_created", "user_id", "created_at"),
    comment="Atomic claim table for retry-safe event processing.",
)

feed_request = Table(
    "feed_request",
    metadata,
    Column("request_id", String(128), primary_key=True),
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
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Index("idx_feed_request_user_created", "user_id", "created_at"),
    comment="Idempotency claim for feed loads that may reserve sponsored delivery.",
)

question = Table(
    "question",
    metadata,
    Column("question_id", BigInteger, primary_key=True, autoincrement=False),
    Column("create_ts", BigInteger),
    Column("answer_count", Integer, nullable=False, server_default=text("0")),
    Column("follower_count", Integer, nullable=False, server_default=text("0")),
    Column("invitation_count", Integer, nullable=False, server_default=text("0")),
    Column("comment_count", Integer, nullable=False, server_default=text("0")),
    Column("token_ids_json", JSONB),
    Column("topic_ids_json", JSONB),
    Column("display_title", String(255)),
    Column("source", String(32), nullable=False, server_default=text("'mind_small'")),
    comment="Article headline compatibility table.",
)

answer = Table(
    "answer",
    metadata,
    Column("answer_id", BigInteger, primary_key=True, autoincrement=False),
    Column(
        "question_id",
        BigInteger,
        ForeignKey("question.question_id", name="fk_answer_question"),
    ),
    Column("author_id", BigInteger, ForeignKey("author.author_id", name="fk_answer_author")),
    Column("is_anonymous", Boolean, nullable=False, server_default=text("false")),
    Column("is_high_value", Boolean, nullable=False, server_default=text("false")),
    Column("is_editor_recommended", Boolean, nullable=False, server_default=text("false")),
    Column("create_ts", BigInteger),
    Column("has_picture", Boolean, nullable=False, server_default=text("false")),
    Column("has_video", Boolean, nullable=False, server_default=text("false")),
    Column("thanks_count", Integer, nullable=False, server_default=text("0")),
    Column("likes_count", Integer, nullable=False, server_default=text("0")),
    Column("comment_count", Integer, nullable=False, server_default=text("0")),
    Column("collection_count", Integer, nullable=False, server_default=text("0")),
    Column("dislike_count", Integer, nullable=False, server_default=text("0")),
    Column("report_count", Integer, nullable=False, server_default=text("0")),
    Column("helpless_count", Integer, nullable=False, server_default=text("0")),
    Column("token_ids_json", JSONB),
    Column("topic_ids_json", JSONB),
    Column("display_summary", Text),
    Column("vector_key", String(128)),
    Column("is_demo_selected", Boolean, nullable=False, server_default=text("false")),
    Column("hot_score", DOUBLE_PRECISION, nullable=False, server_default=text("0")),
    Column("click_count", Integer, nullable=False, server_default=text("0")),
    Column("impression_count", Integer, nullable=False, server_default=text("0")),
    Column("source", String(32), nullable=False, server_default=text("'mind_small'")),
    Index("idx_answer_question", "question_id"),
    Index("idx_answer_author", "author_id"),
    Index("idx_answer_hot_score", "hot_score"),
    comment="Main recommendation entity for the project.",
)

question_topic = Table(
    "question_topic",
    metadata,
    Column(
        "question_id",
        BigInteger,
        ForeignKey("question.question_id", name="fk_question_topic_question"),
        nullable=False,
    ),
    Column(
        "topic_id",
        BigInteger,
        ForeignKey("topic.topic_id", name="fk_question_topic_topic"),
        nullable=False,
    ),
    Column("source_rank", SmallInteger, nullable=False, server_default=text("0")),
    PrimaryKeyConstraint("question_id", "topic_id"),
    Index("idx_question_topic_topic", "topic_id"),
    comment="Many-to-many bridge between questions and topics.",
)

answer_topic = Table(
    "answer_topic",
    metadata,
    Column(
        "answer_id",
        BigInteger,
        ForeignKey("answer.answer_id", name="fk_answer_topic_answer"),
        nullable=False,
    ),
    Column(
        "topic_id",
        BigInteger,
        ForeignKey("topic.topic_id", name="fk_answer_topic_topic"),
        nullable=False,
    ),
    Column("source_rank", SmallInteger, nullable=False, server_default=text("0")),
    PrimaryKeyConstraint("answer_id", "topic_id"),
    Index("idx_answer_topic_topic", "topic_id"),
    comment="Many-to-many bridge between answers and topics.",
)

query_topic_map = Table(
    "query_topic_map",
    metadata,
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
    PrimaryKeyConstraint("query_key", "topic_id"),
    Index("idx_query_topic_topic", "topic_id"),
    Index("idx_query_topic_rank", "query_key", "match_rank"),
    comment="English query aliases and category mappings.",
)

hot_answer_snapshot = Table(
    "hot_answer_snapshot",
    metadata,
    Column("snapshot_key", String(64), nullable=False),
    Column("rank_position", Integer, nullable=False),
    Column(
        "answer_id",
        BigInteger,
        ForeignKey("answer.answer_id", name="fk_hot_answer_snapshot_answer"),
        nullable=False,
    ),
    Column("hot_score", DOUBLE_PRECISION, nullable=False),
    Column("click_count", Integer, nullable=False, server_default=text("0")),
    Column("impression_count", Integer, nullable=False, server_default=text("0")),
    Column(
        "source_window",
        String(64),
        nullable=False,
        server_default=text("'selected_mind_impressions'"),
    ),
    PrimaryKeyConstraint("snapshot_key", "rank_position"),
    UniqueConstraint("snapshot_key", "answer_id", name="uq_hot_snapshot_answer"),
    Index("idx_hot_answer_answer", "answer_id"),
    comment="Fallback pool for hot articles.",
)

system_profile_seed = Table(
    "system_profile_seed",
    metadata,
    Column("seed_key", String(64), primary_key=True),
    Column("topic_weights_json", JSONB, nullable=False),
    Column("recent_clicked_answers_json", JSONB),
    Column("recent_queries_json", JSONB),
    Column("behavior_score", DOUBLE_PRECISION, nullable=False, server_default=text("0")),
    Column("notes", String(255)),
    comment="Reusable cold-start or bootstrap profile seeds.",
)

user_profile = Table(
    "user_profile",
    metadata,
    Column(
        "user_id",
        BigInteger,
        ForeignKey("app_user.user_id", name="fk_user_profile_user"),
        primary_key=True,
    ),
    Column(
        "cold_start_seed_key",
        String(64),
        ForeignKey("system_profile_seed.seed_key", name="fk_user_profile_seed"),
        nullable=False,
        server_default=text("'cold_start_default'"),
    ),
    Column("topic_weights_json", JSONB, nullable=False),
    Column("recent_clicked_answers_json", JSONB, nullable=False),
    Column("recent_queries_json", JSONB, nullable=False),
    Column("behavior_score", DOUBLE_PRECISION, nullable=False, server_default=text("0")),
    Column("user_vector_json", JSONB),
    Column("notes", String(255)),
    Column("last_event_ts", BigInteger),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Index("idx_user_profile_seed", "cold_start_seed_key"),
    comment="Single-table user profile storage.",
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
        "answer_id",
        BigInteger,
        ForeignKey("answer.answer_id", name="fk_sponsored_creative_answer"),
        nullable=False,
    ),
    Column("status", String(16), nullable=False, server_default=text("'active'")),
    Column("bid_micros", BigInteger, nullable=False),
    Column("predicted_ctr", Numeric(10, 8), nullable=False),
    Column("quality_score", Numeric(10, 8), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("campaign_id", "answer_id", name="uq_sponsored_creative_campaign_answer"),
    CheckConstraint("status IN ('active', 'paused')", name="creative_status"),
    CheckConstraint("bid_micros > 0", name="bid"),
    CheckConstraint("predicted_ctr >= 0 AND predicted_ctr <= 1", name="ctr"),
    CheckConstraint("quality_score >= 0 AND quality_score <= 1", name="quality"),
    Index("idx_sponsored_creative_answer", "answer_id"),
    comment="Sponsored creatives backed by existing answer cards.",
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
        "answer_id",
        BigInteger,
        ForeignKey("answer.answer_id", name="fk_sponsored_delivery_answer"),
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
    Column(
        "user_id",
        BigInteger,
        ForeignKey("app_user.user_id", name="fk_user_event_user"),
        nullable=False,
    ),
    Column("event_type", String(32), nullable=False),
    Column("answer_id", BigInteger, ForeignKey("answer.answer_id", name="fk_user_event_answer")),
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
        "'feed_impression', 'detail_view', 'dwell', 'upvote', 'downvote', 'share')",
        name="event_type",
    ),
    CheckConstraint(
        "source_confidence IN ('confirmed', 'heuristic', 'not_applicable')",
        name="source_confidence",
    ),
    Index("idx_user_event_user_ts", "user_id", "event_ts"),
    Index("idx_user_event_type_ts", "event_type", "event_ts"),
    Index("idx_user_event_answer", "answer_id"),
    Index("idx_user_event_request_answer", "request_id", "answer_id"),
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
