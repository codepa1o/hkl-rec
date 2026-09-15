from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Boolean, CheckConstraint, Identity, inspect
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.db.schema import metadata

EXPECTED_TABLES = {
    "topic",
    "app_user",
    "auth_user_id_sequence",
    "user_account",
    "event_idempotency",
    "feed_request",
    "live_news",
    "live_news_topic",
    "live_topic_enrichment_job",
    "live_profile_rebuild_job",
    "live_news_content_job",
    "live_news_content_asset",
    "live_news_import",
    "live_news_source_checkpoint",
    "mind_news",
    "mind_news_topic",
    "mind_news_stats",
    "mind_catalog_import",
    "query_topic_map",
    "system_profile_seed",
    "user_profile",
    "user_topic_profile",
    "sponsored_campaign",
    "sponsored_campaign_topic",
    "sponsored_creative",
    "sponsored_campaign_daily_state",
    "sponsored_user_daily_frequency",
    "sponsored_delivery",
    "user_event",
    "event_outbox",
    "worker_heartbeat",
}

MIND_NEWS_COLUMNS = {
    "news_id",
    "category",
    "subcategory",
    "title",
    "abstract",
    "url",
    "title_entities",
    "abstract_entities",
}

LEGACY_CONTENT_TABLES = {
    "question",
    "answer",
    "author",
    "question_topic",
    "answer_topic",
    "hot_answer_snapshot",
}


def test_metadata_contains_every_existing_business_table() -> None:
    assert set(metadata.tables) == EXPECTED_TABLES
    assert not LEGACY_CONTENT_TABLES.intersection(metadata.tables)


def test_mind_news_is_the_exact_eight_field_source_of_truth() -> None:
    news = metadata.tables["mind_news"]

    assert set(news.c.keys()) == MIND_NEWS_COLUMNS
    assert news.primary_key.name == "pk_mind_news"
    assert [column.name for column in news.primary_key.columns] == ["news_id"]
    assert isinstance(news.c.title_entities.type, JSONB)
    assert isinstance(news.c.abstract_entities.type, JSONB)

    topic = metadata.tables["topic"]
    assert topic.c.topic_key.nullable is False
    mapping = metadata.tables["mind_news_topic"]
    assert set(mapping.c.keys()) == {"news_id", "topic_id", "source_rank"}


def test_mind_content_references_use_news_id_and_events_use_article_id() -> None:
    for table_name in ("mind_news_stats", "sponsored_creative", "sponsored_delivery"):
        table = metadata.tables[table_name]
        assert "news_id" in table.c
        assert "answer_id" not in table.c
        targets = {
            element.target_fullname
            for foreign_key in table.foreign_key_constraints
            for element in foreign_key.elements
        }
        assert "mind_news.news_id" in targets

    assert "article_id" in metadata.tables["user_event"].c
    assert "news_id" not in metadata.tables["user_event"].c
    assert "answer_id" not in metadata.tables["user_event"].c
    assert "recent_clicked_news_json" in metadata.tables["user_profile"].c
    assert "recent_clicked_answers_json" not in metadata.tables["user_profile"].c


def test_metadata_uses_native_postgres_types_and_named_constraints() -> None:
    assert isinstance(metadata.tables["app_user"].c.is_demo_user.type, Boolean)
    assert isinstance(metadata.tables["user_profile"].c.topic_weights_json.type, JSONB)
    assert isinstance(metadata.tables["user_event"].c.event_id.identity, Identity)
    assert metadata.tables["mind_news"].c.news_id.autoincrement is False
    assert {constraint.name for constraint in metadata.tables["user_account"].constraints} >= {
        "pk_user_account",
        "uq_user_account_email",
        "fk_user_account_user",
    }
    checks = {
        constraint.name
        for constraint in metadata.tables["sponsored_creative"].constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert checks >= {
        "chk_sponsored_creative_bid",
        "chk_sponsored_creative_ctr",
        "chk_sponsored_creative_quality",
    }


def test_alembic_is_configured_to_use_project_metadata() -> None:
    root = Path(__file__).resolve().parents[1]

    assert (root / "alembic.ini").is_file()
    env_source = (root / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "target_metadata = metadata" in env_source
    assert "NEWSREC_DATABASE_URL" in env_source
    versions = list((root / "alembic" / "versions").glob("*.py"))
    assert len(versions) == 13
    script = ScriptDirectory.from_config(Config(root / "alembic.ini"))
    assert script.get_heads() == ["20260914_0013"]


def test_metadata_can_be_inspected_without_binding_an_engine() -> None:
    assert inspect(metadata.tables["mind_news"]).primary_key.name == "pk_mind_news"


def test_feed_request_metadata_includes_category_request_shape() -> None:
    table = metadata.tables["feed_request"]

    assert table.c.category.type.length == 64
    assert table.c.category.nullable is True
    assert "idx_feed_request_category" in {index.name for index in table.indexes}


def test_profile_v2_metadata_has_normalized_topic_projection() -> None:
    projection = metadata.tables["user_topic_profile"]

    assert [column.name for column in projection.primary_key.columns] == [
        "user_id",
        "source_space",
        "topic_id",
    ]
    assert {
        "short_positive_score",
        "short_negative_score",
        "long_positive_score",
        "long_negative_score",
        "positive_evidence_count",
        "negative_evidence_count",
        "evidence_counts_json",
        "last_signal_type",
        "last_event_ts",
        "updated_at",
    } <= set(projection.c.keys())
    assert isinstance(projection.c.evidence_counts_json.type, JSONB)
    assert {
        element.target_fullname
        for constraint in projection.foreign_key_constraints
        for element in constraint.elements
    } == {"app_user.user_id", "topic.topic_id"}
    assert "idx_user_topic_profile_user" in {index.name for index in projection.indexes}


def test_profile_v2_user_state_columns_exist() -> None:
    columns = metadata.tables["user_profile"].c

    assert {
        "profile_v2_evidence_count",
        "profile_v2_last_event_ts",
        "profile_reset_before_ts",
        "profile_reset_before_event_id",
        "profile_v2_updated_at",
    } <= set(columns.keys())
    assert columns.profile_v2_evidence_count.nullable is False
    assert str(columns.profile_v2_evidence_count.server_default.arg) == "0"
