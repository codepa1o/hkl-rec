"""add source-scoped recommendation state and live news catalog

Revision ID: 20260817_0008
Revises: 20260816_0007
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260817_0008"
down_revision: str | None = "20260816_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_SPACE_TABLES = (
    "topic",
    "query_topic_map",
    "system_profile_seed",
    "user_profile",
    "user_topic_profile",
    "feed_request",
    "event_idempotency",
    "user_event",
)

_PREVIOUS_EVENT_TYPES = (
    "'search_query', 'recommendation_click', 'search_result_click', "
    "'feed_impression', 'detail_view', 'dwell', 'upvote', 'downvote', 'share'"
)


def _event_type_check(*, include_outbound_click: bool) -> str:
    event_types = _PREVIOUS_EVENT_TYPES
    if include_outbound_click:
        event_types += ", 'outbound_click'"
    return f"event_type IN ({event_types})"


def upgrade() -> None:
    for table_name in _SOURCE_SPACE_TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "source_space",
                sa.String(length=16),
                server_default=sa.text("'mind'"),
                nullable=False,
            ),
        )

    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM system_profile_seed
                    WHERE seed_key = 'live_cold_start_default'
                ) THEN
                    RAISE EXCEPTION
                        'live_cold_start_default is reserved for the Live news space; '
                        'rename the pre-existing seed and update referencing profiles before retrying';
                END IF;
            END
            $$
            """
        )
    )

    op.add_column(
        "user_event",
        sa.Column("article_id", sa.String(length=64), nullable=True),
    )
    op.execute(sa.text("UPDATE user_event SET article_id = news_id WHERE news_id IS NOT NULL"))

    op.drop_constraint("pk_user_profile", "user_profile", type_="primary")
    op.create_primary_key(
        "pk_user_profile",
        "user_profile",
        ["user_id", "source_space"],
    )
    op.drop_constraint("pk_user_topic_profile", "user_topic_profile", type_="primary")
    op.create_primary_key(
        "pk_user_topic_profile",
        "user_topic_profile",
        ["user_id", "source_space", "topic_id"],
    )
    op.drop_constraint("pk_query_topic_map", "query_topic_map", type_="primary")
    op.create_primary_key(
        "pk_query_topic_map",
        "query_topic_map",
        ["source_space", "query_key", "topic_id"],
    )

    op.drop_constraint("uq_topic_topic_key", "topic", type_="unique")
    op.create_unique_constraint(
        "uq_topic_space_key",
        "topic",
        ["source_space", "topic_key"],
    )

    op.drop_constraint(op.f("chk_user_event_event_type"), "user_event", type_="check")
    op.create_check_constraint(
        op.f("chk_user_event_event_type"),
        "user_event",
        _event_type_check(include_outbound_click=True),
    )

    op.create_table(
        "live_news",
        sa.Column("article_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("source_external_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column("source_domain", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at_quality", sa.String(length=32), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("raw_metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "link_failure_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_link_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("language IN ('zh', 'en')", name=op.f("chk_live_news_language")),
        sa.CheckConstraint(
            "published_at_quality IN ('gdelt_unverified', 'publisher', 'unknown')",
            name=op.f("chk_live_news_published_at_quality"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name=op.f("chk_live_news_status"),
        ),
        sa.PrimaryKeyConstraint("article_id", name="pk_live_news"),
        sa.UniqueConstraint("canonical_url", name="uq_live_news_canonical_url"),
        comment="Canonical catalog of continuously discovered live news articles.",
    )
    op.create_index(
        "idx_live_news_active_discovered",
        "live_news",
        ["status", sa.text("discovered_at DESC"), "article_id"],
        unique=False,
    )
    op.create_index(
        "idx_live_news_language_discovered",
        "live_news",
        ["language", sa.text("discovered_at DESC"), "article_id"],
        unique=False,
    )
    op.create_index(
        "idx_live_news_domain_discovered",
        "live_news",
        ["source_domain", sa.text("discovered_at DESC"), "article_id"],
        unique=False,
    )
    op.create_index(
        "idx_live_news_content_hash",
        "live_news",
        ["content_hash"],
        unique=False,
    )

    op.create_table(
        "live_news_source_checkpoint",
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("last_batch_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_etag", sa.String(length=255), nullable=True),
        sa.Column("last_modified", sa.String(length=255), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("source_name", name="pk_live_news_source_checkpoint"),
        comment="Per-source cursors and health state for live news discovery.",
    )

    op.create_table(
        "live_news_import",
        sa.Column("batch_id", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "accepted_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "rejected_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "rejection_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('fetching', 'completed', 'failed')",
            name=op.f("chk_live_news_import_status"),
        ),
        sa.PrimaryKeyConstraint("batch_id", name="pk_live_news_import"),
        comment="Audit record for each raw live-news import batch.",
    )

    op.create_index(
        "idx_user_event_space_user_ts",
        "user_event",
        ["source_space", "user_id", "event_ts"],
        unique=False,
    )
    op.create_index(
        "idx_feed_request_space_session",
        "feed_request",
        ["source_space", "session_id", "page_number"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO system_profile_seed (
                seed_key, topic_weights_json, recent_clicked_news_json,
                recent_queries_json, behavior_score, notes, source_space
            ) VALUES (
                'live_cold_start_default', '[]'::jsonb, '[]'::jsonb,
                '[]'::jsonb, 0, 'Empty cold-start profile for the live news space.', 'live'
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM user_event WHERE source_space <> 'mind' OR event_type = 'outbound_click'"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM event_idempotency "
            "WHERE source_space <> 'mind' OR event_type = 'outbound_click'"
        )
    )
    op.execute(sa.text("DELETE FROM feed_request WHERE source_space <> 'mind'"))
    op.execute(sa.text("DELETE FROM user_topic_profile WHERE source_space <> 'mind'"))
    op.execute(sa.text("DELETE FROM query_topic_map WHERE source_space <> 'mind'"))
    op.execute(
        sa.text(
            "DELETE FROM user_profile "
            "WHERE source_space <> 'mind' "
            "OR cold_start_seed_key IN ("
            "SELECT seed_key FROM system_profile_seed WHERE source_space <> 'mind'"
            ")"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM mind_news_topic WHERE topic_id IN ("
            "SELECT topic_id FROM topic WHERE source_space <> 'mind'"
            ")"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM sponsored_campaign_topic WHERE topic_id IN ("
            "SELECT topic_id FROM topic WHERE source_space <> 'mind'"
            ")"
        )
    )
    op.execute(sa.text("DELETE FROM topic WHERE source_space <> 'mind'"))
    op.execute(sa.text("DELETE FROM system_profile_seed WHERE source_space <> 'mind'"))

    op.drop_index("idx_feed_request_space_session", table_name="feed_request")
    op.drop_index("idx_user_event_space_user_ts", table_name="user_event")

    op.drop_index("idx_live_news_content_hash", table_name="live_news")
    op.drop_index("idx_live_news_domain_discovered", table_name="live_news")
    op.drop_index("idx_live_news_language_discovered", table_name="live_news")
    op.drop_index("idx_live_news_active_discovered", table_name="live_news")
    op.drop_table("live_news_import")
    op.drop_table("live_news_source_checkpoint")
    op.drop_table("live_news")

    op.drop_constraint(op.f("chk_user_event_event_type"), "user_event", type_="check")
    op.create_check_constraint(
        op.f("chk_user_event_event_type"),
        "user_event",
        _event_type_check(include_outbound_click=False),
    )

    op.drop_constraint("uq_topic_space_key", "topic", type_="unique")
    op.create_unique_constraint("uq_topic_topic_key", "topic", ["topic_key"])

    op.drop_constraint("pk_query_topic_map", "query_topic_map", type_="primary")
    op.create_primary_key(
        "pk_query_topic_map",
        "query_topic_map",
        ["query_key", "topic_id"],
    )
    op.drop_constraint("pk_user_topic_profile", "user_topic_profile", type_="primary")
    op.create_primary_key(
        "pk_user_topic_profile",
        "user_topic_profile",
        ["user_id", "topic_id"],
    )
    op.drop_constraint("pk_user_profile", "user_profile", type_="primary")
    op.create_primary_key("pk_user_profile", "user_profile", ["user_id"])

    op.drop_column("user_event", "article_id")
    for table_name in reversed(_SOURCE_SPACE_TABLES):
        op.drop_column(table_name, "source_space")
