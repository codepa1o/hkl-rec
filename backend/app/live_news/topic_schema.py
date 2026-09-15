"""SQLAlchemy mirror for the local topic pipeline."""

import sqlalchemy as sa


def define_topic_tables(metadata: sa.MetaData) -> None:
    news = metadata.tables["live_news"]
    for column in (
        sa.Column("topic_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("topic_classifier_version", sa.String(64)),
        sa.Column("topic_classified_at", sa.DateTime(timezone=True)),
        sa.Column("topic_input_hash", sa.String(64)),
    ):
        news.append_column(column)
    news.append_constraint(
        sa.CheckConstraint("topic_status IN ('pending','available','failed')", name="topic_status")
    )
    metadata.tables["topic"].append_constraint(
        sa.UniqueConstraint("topic_id", "source_space", name="uq_topic_id_space")
    )
    sa.Table(
        "live_news_topic",
        metadata,
        sa.Column(
            "article_id",
            sa.String(64),
            sa.ForeignKey("live_news.article_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("topic_id", sa.BigInteger(), primary_key=True),
        sa.Column("source_space", sa.String(16), nullable=False, server_default="live"),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("semantic_score", sa.Float(), nullable=False),
        sa.Column("lexical_score", sa.Float(), nullable=False),
        sa.Column("classifier_version", sa.String(64), nullable=False),
        sa.Column("input_content_hash", sa.String(64), nullable=False),
        sa.Column(
            "classified_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "source_space"], ["topic.topic_id", "topic.source_space"]
        ),
        sa.UniqueConstraint("article_id", "rank"),
        sa.CheckConstraint("source_space = 'live'", name="source_space"),
        sa.CheckConstraint("rank BETWEEN 0 AND 2", name="rank"),
        sa.CheckConstraint(
            "final_score BETWEEN 0 AND 1 AND semantic_score BETWEEN 0 AND 1 AND lexical_score BETWEEN 0 AND 1",
            name="scores",
        ),
    )
    sa.Table(
        "live_topic_enrichment_job",
        metadata,
        sa.Column(
            "article_id",
            sa.String(64),
            sa.ForeignKey("live_news.article_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("generation", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("worker_id", sa.String(128)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('pending','fetching','completed','failed')", name="status"),
        sa.Index("idx_live_topic_job_due", "status", "next_attempt_at"),
    )
    sa.Table(
        "live_profile_rebuild_job",
        metadata,
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("app_user.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("generation", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
