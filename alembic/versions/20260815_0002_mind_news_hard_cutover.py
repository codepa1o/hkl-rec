"""replace the legacy content model with canonical MIND news

Revision ID: 20260815_0002
Revises: 20260814_0001
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260815_0002"
down_revision: str | None = "20260814_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_FINGERPRINT = "0" * 64


def _migrate_news_id_column(
    table_name: str,
    *,
    nullable: bool,
    old_foreign_key: str,
    new_foreign_key: str,
) -> None:
    op.add_column(table_name, sa.Column("news_id", sa.String(length=32), nullable=True))
    op.execute(
        sa.text(
            f"UPDATE {table_name} SET news_id = 'N' || answer_id::text "
            "WHERE answer_id IS NOT NULL"
        )
    )
    if not nullable:
        op.alter_column(table_name, "news_id", existing_type=sa.String(length=32), nullable=False)
    op.create_foreign_key(
        new_foreign_key,
        table_name,
        "mind_news",
        ["news_id"],
        ["news_id"],
    )
    op.drop_constraint(old_foreign_key, table_name, type_="foreignkey")


def _canonical_news_array(column_name: str) -> sa.TextClause:
    return sa.text(
        f"""
        CASE
          WHEN {column_name} IS NULL THEN NULL
          ELSE COALESCE(
            (
              SELECT jsonb_agg(
                to_jsonb(
                  CASE
                    WHEN item #>> '{{}}' ~ '^N[0-9]+$' THEN item #>> '{{}}'
                    ELSE 'N' || (item #>> '{{}}')
                  END
                )
                ORDER BY ordinal_position
              )
              FROM jsonb_array_elements({column_name})
                   WITH ORDINALITY AS entries(item, ordinal_position)
            ),
            '[]'::jsonb
          )
        END
        """
    )


def upgrade() -> None:
    op.create_table(
        "mind_news",
        sa.Column("news_id", sa.String(length=32), autoincrement=False, nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("subcategory", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title_entities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("abstract_entities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("news_id ~ '^N[0-9]+$'", name="chk_mind_news_news_id"),
        sa.CheckConstraint(
            "jsonb_typeof(title_entities) = 'array'",
            name="chk_mind_news_title_entities_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(abstract_entities) = 'array'",
            name="chk_mind_news_abstract_entities_array",
        ),
        sa.PrimaryKeyConstraint("news_id", name="pk_mind_news"),
        comment="Canonical MIND news.tsv rows with exactly the eight source fields.",
    )
    op.create_index("idx_mind_news_category", "mind_news", ["category"], unique=False)
    op.create_index("idx_mind_news_subcategory", "mind_news", ["subcategory"], unique=False)

    op.create_table(
        "mind_catalog_import",
        sa.Column("normalized_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("dataset", sa.String(length=32), nullable=False),
        sa.Column("news_count", sa.Integer(), nullable=False),
        sa.Column("train_request_count", sa.Integer(), nullable=False),
        sa.Column("train_impression_count", sa.BigInteger(), nullable=False),
        sa.Column("train_click_count", sa.BigInteger(), nullable=False),
        sa.Column("articles_sha256", sa.String(length=64), nullable=False),
        sa.Column("train_impressions_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("news_count >= 0", name="chk_mind_catalog_import_news_count"),
        sa.CheckConstraint(
            "train_request_count >= 0",
            name="chk_mind_catalog_import_train_request_count",
        ),
        sa.CheckConstraint(
            "train_impression_count >= 0",
            name="chk_mind_catalog_import_train_impression_count",
        ),
        sa.CheckConstraint(
            "train_click_count >= 0",
            name="chk_mind_catalog_import_train_click_count",
        ),
        sa.PrimaryKeyConstraint("normalized_fingerprint", name="pk_mind_catalog_import"),
        comment="Fingerprint and row-count provenance for an imported normalized MIND catalog.",
    )

    op.create_table(
        "mind_news_stats",
        sa.Column("news_id", sa.String(length=32), nullable=False),
        sa.Column("first_seen_ts", sa.BigInteger(), nullable=True),
        sa.Column("click_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "impression_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "hot_score", sa.DOUBLE_PRECISION(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("normalized_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint("click_count >= 0", name="chk_mind_news_stats_click_count"),
        sa.CheckConstraint(
            "impression_count >= click_count",
            name="chk_mind_news_stats_impression_count",
        ),
        sa.CheckConstraint("hot_score >= 0", name="chk_mind_news_stats_hot_score"),
        sa.ForeignKeyConstraint(
            ["news_id"], ["mind_news.news_id"], name="fk_mind_news_stats_news"
        ),
        sa.ForeignKeyConstraint(
            ["normalized_fingerprint"],
            ["mind_catalog_import.normalized_fingerprint"],
            name="fk_mind_news_stats_import",
        ),
        sa.PrimaryKeyConstraint("news_id", name="pk_mind_news_stats"),
        comment="Train-only serving statistics kept separate from canonical MIND facts.",
    )
    op.create_index(
        "idx_mind_news_stats_hot",
        "mind_news_stats",
        ["hot_score", "news_id"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO mind_news (
                news_id, category, subcategory, title, abstract, url,
                title_entities, abstract_entities
            )
            SELECT
                'N' || a.answer_id::text,
                'unknown',
                'legacy-cutover',
                COALESCE(q.display_title, 'N' || a.answer_id::text),
                COALESCE(a.display_summary, ''),
                '',
                '[]'::jsonb,
                '[]'::jsonb
            FROM answer AS a
            LEFT JOIN question AS q ON q.question_id = a.question_id
            ON CONFLICT (news_id) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO mind_catalog_import (
                normalized_fingerprint, dataset, news_count, train_request_count,
                train_impression_count, train_click_count, articles_sha256,
                train_impressions_sha256
            )
            SELECT
                :fingerprint,
                'legacy-cutover',
                COUNT(*)::integer,
                0,
                COALESCE(SUM(impression_count), 0),
                COALESCE(SUM(click_count), 0),
                :fingerprint,
                :fingerprint
            FROM answer
            """
        ).bindparams(fingerprint=_LEGACY_FINGERPRINT)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO mind_news_stats (
                news_id, first_seen_ts, click_count, impression_count,
                hot_score, normalized_fingerprint
            )
            SELECT
                'N' || answer_id::text,
                create_ts,
                click_count,
                GREATEST(impression_count, click_count),
                GREATEST(hot_score, 0),
                :fingerprint
            FROM answer
            """
        ).bindparams(fingerprint=_LEGACY_FINGERPRINT)
    )

    _migrate_news_id_column(
        "sponsored_creative",
        nullable=False,
        old_foreign_key="fk_sponsored_creative_answer",
        new_foreign_key="fk_sponsored_creative_news",
    )
    op.drop_constraint(
        "uq_sponsored_creative_campaign_answer", "sponsored_creative", type_="unique"
    )
    op.drop_index("idx_sponsored_creative_answer", table_name="sponsored_creative")
    op.create_unique_constraint(
        "uq_sponsored_creative_campaign_news",
        "sponsored_creative",
        ["campaign_id", "news_id"],
    )
    op.create_index(
        "idx_sponsored_creative_news", "sponsored_creative", ["news_id"], unique=False
    )
    op.drop_column("sponsored_creative", "answer_id")

    _migrate_news_id_column(
        "sponsored_delivery",
        nullable=False,
        old_foreign_key="fk_sponsored_delivery_answer",
        new_foreign_key="fk_sponsored_delivery_news",
    )
    op.drop_column("sponsored_delivery", "answer_id")

    _migrate_news_id_column(
        "user_event",
        nullable=True,
        old_foreign_key="fk_user_event_answer",
        new_foreign_key="fk_user_event_news",
    )
    op.drop_index("idx_user_event_answer", table_name="user_event")
    op.drop_index("idx_user_event_request_answer", table_name="user_event")
    op.create_index("idx_user_event_news", "user_event", ["news_id"], unique=False)
    op.create_index(
        "idx_user_event_request_news", "user_event", ["request_id", "news_id"], unique=False
    )
    op.drop_column("user_event", "answer_id")

    op.add_column(
        "system_profile_seed",
        sa.Column("recent_clicked_news_json", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.execute(
        sa.text(
            "UPDATE system_profile_seed SET recent_clicked_news_json = "
            + _canonical_news_array("recent_clicked_answers_json").text
        )
    )
    op.drop_column("system_profile_seed", "recent_clicked_answers_json")

    op.add_column(
        "user_profile",
        sa.Column("recent_clicked_news_json", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.execute(
        sa.text(
            "UPDATE user_profile SET recent_clicked_news_json = "
            + _canonical_news_array("recent_clicked_answers_json").text
        )
    )
    op.alter_column(
        "user_profile",
        "recent_clicked_news_json",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
    )
    op.drop_column("user_profile", "recent_clicked_answers_json")

    op.add_column(
        "topic",
        sa.Column("news_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.execute(
        sa.text("UPDATE topic SET news_count = GREATEST(answer_count, question_count)")
    )
    op.drop_column("topic", "answer_count")
    op.drop_column("topic", "question_count")
    op.drop_column("app_user", "answer_count")
    op.drop_column("app_user", "question_count")

    op.drop_table("hot_answer_snapshot")
    op.drop_table("answer_topic")
    op.drop_table("question_topic")
    op.drop_table("answer")
    op.drop_table("question")
    op.drop_table("author")


def downgrade() -> None:
    raise RuntimeError(
        "The MIND news hard cutover intentionally deletes the legacy content model; "
        "restore a pre-cutover PostgreSQL backup instead of downgrading."
    )
