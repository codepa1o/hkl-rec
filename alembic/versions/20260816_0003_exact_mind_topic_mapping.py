"""add stable MIND topic keys and exact news-topic mappings

Revision ID: 20260816_0003
Revises: 20260815_0002
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260816_0003"
down_revision: str | None = "20260815_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("topic", sa.Column("topic_key", sa.String(length=512), nullable=True))
    op.execute(sa.text("UPDATE topic SET topic_key = 'legacy:' || topic_id::text"))
    op.alter_column(
        "topic",
        "topic_key",
        existing_type=sa.String(length=512),
        nullable=False,
    )
    op.create_unique_constraint("uq_topic_topic_key", "topic", ["topic_key"])

    op.create_table(
        "mind_news_topic",
        sa.Column("news_id", sa.String(length=32), nullable=False),
        sa.Column("topic_id", sa.BigInteger(), nullable=False),
        sa.Column("source_rank", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("source_rank IN (0, 1)", name="chk_mind_news_topic_source_rank"),
        sa.ForeignKeyConstraint(
            ["news_id"],
            ["mind_news.news_id"],
            name="fk_mind_news_topic_news",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["topic.topic_id"],
            name="fk_mind_news_topic_topic",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("news_id", "topic_id", name="pk_mind_news_topic"),
        sa.UniqueConstraint("news_id", "source_rank", name="uq_mind_news_topic_news_rank"),
        comment="Exact category and parent-qualified subcategory links for canonical MIND news.",
    )
    op.create_index(
        "idx_mind_news_topic_topic",
        "mind_news_topic",
        ["topic_id", "news_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_mind_news_topic_topic", table_name="mind_news_topic")
    op.drop_table("mind_news_topic")
    op.drop_constraint("uq_topic_topic_key", "topic", type_="unique")
    op.drop_column("topic", "topic_key")
