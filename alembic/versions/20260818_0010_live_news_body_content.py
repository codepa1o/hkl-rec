"""add live news body content and durable acquisition jobs

Revision ID: 20260818_0010
Revises: 20260817_0009
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_0010"
down_revision: str | None = "20260817_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("live_news", sa.Column("body_text", sa.Text(), nullable=True))
    op.add_column("live_news", sa.Column("body_source", sa.String(length=32), nullable=True))
    op.add_column(
        "live_news",
        sa.Column(
            "body_status",
            sa.String(length=24),
            server_default=sa.text("'metadata_only'"),
            nullable=False,
        ),
    )
    op.add_column(
        "live_news", sa.Column("body_fetched_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "live_news", sa.Column("body_content_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "live_news", sa.Column("body_extraction_version", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "live_news",
        sa.Column(
            "content_rights",
            sa.String(length=24),
            server_default=sa.text("'link_only'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "body_source",
        "live_news",
        "body_source IS NULL OR body_source IN ('guardian_api', 'rss', 'html')",
    )
    op.create_check_constraint(
        "body_status",
        "live_news",
        "body_status IN ('metadata_only', 'pending', 'available', 'blocked', 'failed')",
    )
    op.create_check_constraint(
        "content_rights",
        "live_news",
        "content_rights IN ('full_text', 'excerpt_only', 'link_only')",
    )
    op.create_check_constraint(
        "body_integrity",
        "live_news",
        "(body_status = 'available' AND body_text IS NOT NULL "
        "AND body_source IS NOT NULL AND body_fetched_at IS NOT NULL "
        "AND body_content_hash IS NOT NULL AND body_extraction_version IS NOT NULL) "
        "OR (body_status <> 'available' AND body_text IS NULL)",
    )

    op.create_table(
        "live_news_content_job",
        sa.Column("article_id", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_detail", sa.Text(), nullable=True),
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
        sa.CheckConstraint("attempt_count >= 0", name=op.f("chk_live_news_content_job_attempt_count")),
        sa.CheckConstraint(
            "status IN ('pending', 'fetching', 'completed', 'blocked', 'failed')",
            name=op.f("chk_live_news_content_job_status"),
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["live_news.article_id"],
            name=op.f("fk_live_news_content_job_article_id_live_news"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("article_id", name=op.f("pk_live_news_content_job")),
    )
    op.create_index(
        "idx_live_news_content_job_due",
        "live_news_content_job",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_live_news_content_job_due", table_name="live_news_content_job")
    op.drop_table("live_news_content_job")
    op.drop_constraint(op.f("chk_live_news_body_integrity"), "live_news", type_="check")
    op.drop_constraint(op.f("chk_live_news_content_rights"), "live_news", type_="check")
    op.drop_constraint(op.f("chk_live_news_body_status"), "live_news", type_="check")
    op.drop_constraint(op.f("chk_live_news_body_source"), "live_news", type_="check")
    op.drop_column("live_news", "content_rights")
    op.drop_column("live_news", "body_extraction_version")
    op.drop_column("live_news", "body_content_hash")
    op.drop_column("live_news", "body_fetched_at")
    op.drop_column("live_news", "body_status")
    op.drop_column("live_news", "body_source")
    op.drop_column("live_news", "body_text")

