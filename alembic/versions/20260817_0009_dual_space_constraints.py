"""enforce final dual-space event and source constraints

Revision ID: 20260817_0009
Revises: 20260817_0008
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260817_0009"
down_revision: str | None = "20260817_0008"
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
_NO_DEFAULT_TABLES = ("feed_request", "event_idempotency", "user_event")


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM (
                        SELECT source_space FROM topic
                        UNION ALL SELECT source_space FROM query_topic_map
                        UNION ALL SELECT source_space FROM system_profile_seed
                        UNION ALL SELECT source_space FROM user_profile
                        UNION ALL SELECT source_space FROM user_topic_profile
                        UNION ALL SELECT source_space FROM feed_request
                        UNION ALL SELECT source_space FROM event_idempotency
                        UNION ALL SELECT source_space FROM user_event
                    ) AS scoped_rows
                    WHERE source_space IS NULL
                ) THEN
                    RAISE EXCEPTION 'source-scoped tables contain rows without source_space';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM user_event
                    WHERE source_space = 'mind'
                      AND news_id IS NOT NULL
                      AND news_id IS DISTINCT FROM article_id
                ) THEN
                    RAISE EXCEPTION 'MIND user_event news_id/article_id compatibility mismatch';
                END IF;
            END
            $$
            """
        )
    )

    op.drop_index("idx_user_event_request_news", table_name="user_event")
    op.drop_index("idx_user_event_news", table_name="user_event")
    op.drop_constraint("fk_user_event_news", "user_event", type_="foreignkey")
    op.drop_column("user_event", "news_id")

    op.create_check_constraint(
        "article_required",
        "user_event",
        "event_type = 'search_query' OR article_id IS NOT NULL",
    )
    op.create_check_constraint(
        "article_space",
        "user_event",
        "article_id IS NULL OR "
        "(source_space = 'mind' AND article_id ~ '^N[0-9]+$') OR "
        "(source_space = 'live' AND article_id ~ '^L[0-9a-f]{32}$')",
    )
    for table_name in _SOURCE_SPACE_TABLES:
        op.create_check_constraint(
            "source_space",
            table_name,
            "source_space IN ('mind', 'live')",
        )
    for table_name in _NO_DEFAULT_TABLES:
        op.alter_column(
            table_name,
            "source_space",
            existing_type=sa.String(length=16),
            server_default=None,
            existing_nullable=False,
        )


def downgrade() -> None:
    for table_name in _NO_DEFAULT_TABLES:
        op.alter_column(
            table_name,
            "source_space",
            existing_type=sa.String(length=16),
            server_default=sa.text("'mind'"),
            existing_nullable=False,
        )
    for table_name in reversed(_SOURCE_SPACE_TABLES):
        op.drop_constraint(
            op.f(f"chk_{table_name}_source_space"),
            table_name,
            type_="check",
        )
    op.drop_constraint(op.f("chk_user_event_article_space"), "user_event", type_="check")
    op.drop_constraint(op.f("chk_user_event_article_required"), "user_event", type_="check")

    op.add_column(
        "user_event",
        sa.Column("news_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE user_event SET news_id = article_id "
            "WHERE source_space = 'mind' AND article_id IS NOT NULL"
        )
    )
    op.create_foreign_key(
        "fk_user_event_news",
        "user_event",
        "mind_news",
        ["news_id"],
        ["news_id"],
    )
    op.create_index("idx_user_event_news", "user_event", ["news_id"], unique=False)
    op.create_index(
        "idx_user_event_request_news",
        "user_event",
        ["request_id", "news_id"],
        unique=False,
    )
