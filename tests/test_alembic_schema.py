from __future__ import annotations

from pathlib import Path

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
    "mind_news",
    "mind_news_stats",
    "mind_catalog_import",
    "query_topic_map",
    "system_profile_seed",
    "user_profile",
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


def test_all_content_references_use_news_id() -> None:
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

    assert "news_id" in metadata.tables["user_event"].c
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
    assert len(versions) == 2


def test_metadata_can_be_inspected_without_binding_an_engine() -> None:
    assert inspect(metadata.tables["mind_news"]).primary_key.name == "pk_mind_news"
