"""add cursor pagination state to feed requests

Revision ID: 20260816_0004
Revises: 20260816_0003
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260816_0004"
down_revision: str | None = "20260816_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("feed_request", sa.Column("session_id", sa.String(length=128)))
    op.add_column(
        "feed_request",
        sa.Column("page_number", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("feed_request", sa.Column("cursor_token", sa.String(length=128)))
    op.add_column(
        "feed_request",
        sa.Column(
            "returned_news_ids_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.execute(sa.text("UPDATE feed_request SET session_id = request_id"))
    op.alter_column(
        "feed_request",
        "session_id",
        existing_type=sa.String(length=128),
        nullable=False,
    )
    op.create_index(
        "uq_feed_request_cursor_token",
        "feed_request",
        ["cursor_token"],
        unique=True,
    )
    op.create_index(
        "idx_feed_request_session_page",
        "feed_request",
        ["session_id", "page_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_feed_request_session_page", table_name="feed_request")
    op.drop_index("uq_feed_request_cursor_token", table_name="feed_request")
    op.drop_column("feed_request", "returned_news_ids_json")
    op.drop_column("feed_request", "cursor_token")
    op.drop_column("feed_request", "page_number")
    op.drop_column("feed_request", "session_id")
