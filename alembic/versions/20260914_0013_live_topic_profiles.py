"""Persist local Live classification and source-isolated profile catch-up."""

import sqlalchemy as sa

from alembic import op

revision = "20260914_0013"
down_revision = "20260914_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "live_news",
        sa.Column("topic_status", sa.String(16), nullable=False, server_default="pending"),
    )
    op.add_column("live_news", sa.Column("topic_classifier_version", sa.String(64)))
    op.add_column("live_news", sa.Column("topic_classified_at", sa.DateTime(timezone=True)))
    op.add_column("live_news", sa.Column("topic_input_hash", sa.String(64)))
    op.create_check_constraint(
        "topic_status", "live_news", "topic_status IN ('pending','available','failed')"
    )
    op.create_unique_constraint("uq_topic_id_space", "topic", ["topic_id", "source_space"])
    op.create_table(
        "live_news_topic",
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
    op.create_table(
        "live_topic_enrichment_job",
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
    )
    op.create_index(
        "idx_live_topic_job_due", "live_topic_enrichment_job", ["status", "next_attempt_at"]
    )
    op.create_table(
        "live_profile_rebuild_job",
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
    op.execute("""
        CREATE FUNCTION enqueue_live_topics() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          INSERT INTO live_topic_enrichment_job(article_id) VALUES(NEW.article_id)
          ON CONFLICT(article_id) DO UPDATE SET status='pending',
            generation=live_topic_enrichment_job.generation+1, attempt_count=0,
            worker_id=NULL, claimed_at=NULL, next_attempt_at=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP;
          RETURN NEW;
        END $$;
        CREATE TRIGGER live_topics_insert AFTER INSERT ON live_news
          FOR EACH ROW EXECUTE FUNCTION enqueue_live_topics();
        CREATE TRIGGER live_topics_change AFTER UPDATE OF title,summary ON live_news
          FOR EACH ROW WHEN(OLD.title IS DISTINCT FROM NEW.title OR OLD.summary IS DISTINCT FROM NEW.summary)
          EXECUTE FUNCTION enqueue_live_topics();
        CREATE FUNCTION enqueue_live_profile() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.source_space='live' AND NEW.event_type IN
             ('recommendation_click','search_result_click','upvote','downvote','dwell') THEN
            INSERT INTO live_profile_rebuild_job(user_id) VALUES(NEW.user_id)
            ON CONFLICT(user_id) DO UPDATE SET generation=live_profile_rebuild_job.generation+1,
              updated_at=CURRENT_TIMESTAMP;
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER live_profile_event AFTER INSERT ON user_event
          FOR EACH ROW EXECUTE FUNCTION enqueue_live_profile();
        INSERT INTO live_topic_enrichment_job(article_id) SELECT article_id FROM live_news;
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER live_profile_event ON user_event; DROP FUNCTION enqueue_live_profile(); DROP TRIGGER live_topics_insert ON live_news; DROP TRIGGER live_topics_change ON live_news; DROP FUNCTION enqueue_live_topics();"
    )
    op.drop_table("live_profile_rebuild_job")
    op.drop_table("live_topic_enrichment_job")
    op.drop_table("live_news_topic")
    op.drop_constraint("uq_topic_id_space", "topic", type_="unique")
    op.drop_constraint(op.f("chk_live_news_topic_status"), "live_news", type_="check")
    for name in (
        "topic_input_hash",
        "topic_classified_at",
        "topic_classifier_version",
        "topic_status",
    ):
        op.drop_column("live_news", name)
