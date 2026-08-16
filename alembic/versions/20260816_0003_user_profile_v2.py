"""add normalized user profile v2 projection

Revision ID: 20260816_0003
Revises: 20260815_0002
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260816_0003"
down_revision: str | None = "20260815_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column(
            "profile_v2_evidence_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "user_profile",
        sa.Column("profile_v2_last_event_ts", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "user_profile",
        sa.Column("profile_reset_before_ts", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "user_profile",
        sa.Column("profile_v2_updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "user_topic_profile",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "short_positive_score",
            sa.DOUBLE_PRECISION(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "short_negative_score",
            sa.DOUBLE_PRECISION(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "long_positive_score",
            sa.DOUBLE_PRECISION(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "long_negative_score",
            sa.DOUBLE_PRECISION(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "positive_evidence_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "negative_evidence_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "evidence_counts_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_signal_type", sa.String(length=32), nullable=True),
        sa.Column("last_event_ts", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "short_positive_score >= 0 AND short_negative_score >= 0",
            name="short_scores",
        ),
        sa.CheckConstraint(
            "long_positive_score >= 0 AND long_negative_score >= 0",
            name="long_scores",
        ),
        sa.CheckConstraint(
            "positive_evidence_count >= 0 AND negative_evidence_count >= 0",
            name="evidence_counts",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.user_id"],
            name="fk_user_topic_profile_user",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["topic.topic_id"],
            name="fk_user_topic_profile_topic",
        ),
        sa.PrimaryKeyConstraint(
            "user_id",
            "topic_id",
            name="pk_user_topic_profile",
        ),
        comment="Short- and long-term explainable topic projection for profile V2.",
    )
    op.create_index(
        "idx_user_topic_profile_user",
        "user_topic_profile",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_user_topic_profile_user", table_name="user_topic_profile")
    op.drop_table("user_topic_profile")
    op.drop_column("user_profile", "profile_v2_updated_at")
    op.drop_column("user_profile", "profile_reset_before_ts")
    op.drop_column("user_profile", "profile_v2_last_event_ts")
    op.drop_column("user_profile", "profile_v2_evidence_count")
