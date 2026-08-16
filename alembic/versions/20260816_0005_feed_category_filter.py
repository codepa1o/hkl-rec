"""将新闻分类加入信息流请求形状。

Revision ID: 20260816_0005
Revises: 20260816_0004
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260816_0005"
down_revision: str | None = "20260816_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "feed_request",
        sa.Column("category", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "idx_feed_request_category",
        "feed_request",
        ["category"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_feed_request_category", table_name="feed_request")
    op.drop_column("feed_request", "category")
