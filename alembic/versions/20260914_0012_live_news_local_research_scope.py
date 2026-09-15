"""add local research access scope to live news bodies

Revision ID: 20260914_0012
Revises: 20260821_0011
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260914_0012"
down_revision: str | None = "20260821_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "live_news",
        sa.Column(
            "body_access_scope",
            sa.String(length=24),
            server_default=sa.text("'public'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "body_access_scope",
        "live_news",
        "body_access_scope IN ('public', 'local_research')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("chk_live_news_body_access_scope"),
        "live_news",
        type_="check",
    )
    op.drop_column("live_news", "body_access_scope")
