"""add structured live news documents and image assets

Revision ID: 20260821_0011
Revises: 20260818_0010
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "20260821_0011"
down_revision: str | None = "20260818_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("live_news", sa.Column("body_document", JSONB(), nullable=True))
    op.add_column(
        "live_news", sa.Column("body_document_version", sa.String(length=32), nullable=True)
    )
    op.add_column("live_news", sa.Column("body_document_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "live_news",
        sa.Column(
            "body_structure_status",
            sa.String(length=24),
            server_default=sa.text("'missing'"),
            nullable=False,
        ),
    )
    op.add_column(
        "live_news",
        sa.Column("body_structure_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "body_structure_status",
        "live_news",
        "body_structure_status IN ('missing', 'pending', 'available', 'failed', 'blocked')",
    )
    op.execute(
        "UPDATE live_news SET body_structure_status = 'blocked' WHERE content_rights = 'link_only'"
    )

    op.add_column(
        "live_news_content_job",
        sa.Column(
            "target_extraction_version",
            sa.String(length=32),
            server_default=sa.text("'structured-1'"),
            nullable=False,
        ),
    )
    op.add_column(
        "live_news_content_job",
        sa.Column(
            "requested_by",
            sa.String(length=24),
            server_default=sa.text("'ingest'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "requested_by",
        "live_news_content_job",
        "requested_by IN ('ingest', 'detail_on_demand', 'operator_backfill', 'version_upgrade')",
    )

    op.create_table(
        "live_news_content_asset",
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("article_id", sa.String(length=64), nullable=False),
        sa.Column("block_id", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("display_url", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("alt_text", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("credit", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "cache_status",
            sa.String(length=20),
            server_default=sa.text("'remote_only'"),
            nullable=False,
        ),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "width IS NULL OR width > 0", name=op.f("chk_live_news_content_asset_width")
        ),
        sa.CheckConstraint(
            "height IS NULL OR height > 0", name=op.f("chk_live_news_content_asset_height")
        ),
        sa.CheckConstraint(
            "cache_status IN ('remote_only', 'pending', 'cached', 'failed', 'omitted')",
            name=op.f("chk_live_news_content_asset_cache_status"),
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["live_news.article_id"],
            name=op.f("fk_live_news_content_asset_article_id_live_news"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("asset_id", name=op.f("pk_live_news_content_asset")),
        sa.UniqueConstraint(
            "article_id", "block_id", name=op.f("uq_live_news_content_asset_article_block")
        ),
    )
    op.create_index(
        "idx_live_news_content_asset_article",
        "live_news_content_asset",
        ["article_id", "block_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_live_news_content_asset_article", table_name="live_news_content_asset")
    op.drop_table("live_news_content_asset")
    op.drop_constraint(
        op.f("chk_live_news_content_job_requested_by"),
        "live_news_content_job",
        type_="check",
    )
    op.drop_column("live_news_content_job", "requested_by")
    op.drop_column("live_news_content_job", "target_extraction_version")
    op.drop_constraint(op.f("chk_live_news_body_structure_status"), "live_news", type_="check")
    op.drop_column("live_news", "body_structure_updated_at")
    op.drop_column("live_news", "body_structure_status")
    op.drop_column("live_news", "body_document_hash")
    op.drop_column("live_news", "body_document_version")
    op.drop_column("live_news", "body_document")
