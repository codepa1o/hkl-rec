from __future__ import annotations

from pathlib import Path

from sqlalchemy import Boolean, CheckConstraint, Identity, inspect
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.db.schema import metadata

EXPECTED_TABLES = {
    "topic",
    "author",
    "app_user",
    "auth_user_id_sequence",
    "user_account",
    "event_idempotency",
    "feed_request",
    "question",
    "answer",
    "question_topic",
    "answer_topic",
    "query_topic_map",
    "hot_answer_snapshot",
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


def test_metadata_contains_every_existing_business_table() -> None:
    assert set(metadata.tables) == EXPECTED_TABLES


def test_metadata_uses_native_postgres_types_and_named_constraints() -> None:
    assert isinstance(metadata.tables["app_user"].c.is_demo_user.type, Boolean)
    assert isinstance(metadata.tables["user_profile"].c.topic_weights_json.type, JSONB)
    assert isinstance(metadata.tables["user_event"].c.event_id.identity, Identity)
    assert metadata.tables["answer"].c.answer_id.autoincrement is False
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
    assert len(versions) == 1


def test_metadata_can_be_inspected_without_binding_an_engine() -> None:
    assert inspect(metadata.tables["answer"]).primary_key.name == "pk_answer"
