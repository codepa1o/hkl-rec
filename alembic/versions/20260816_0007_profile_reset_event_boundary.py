"""add causal event boundary for profile reset

Revision ID: 20260816_0007
Revises: 20260816_0006
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260816_0007"
down_revision: str | None = "20260816_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("profile_reset_before_event_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profile", "profile_reset_before_event_id")
