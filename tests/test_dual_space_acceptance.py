from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint

from backend.app.db.schema import metadata
from scripts.reset_demo_user import reset_demo_user


def test_final_event_metadata_uses_only_canonical_article_identity() -> None:
    event = metadata.tables["user_event"]

    assert "article_id" in event.c
    assert "news_id" not in event.c
    checks = {
        constraint.name
        for constraint in event.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "chk_user_event_article_required" in checks
    assert "chk_user_event_source_space" in checks
    assert event.c.source_space.server_default is None


@pytest.mark.postgres
def test_new_events_require_explicit_space_and_use_article_id(postgres_connection) -> None:
    with postgres_connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'user_event'
              AND column_name IN ('source_space', 'article_id', 'news_id')
            ORDER BY column_name
            """
        )
        columns = {row["column_name"]: row for row in cursor.fetchall()}

    assert set(columns) == {"article_id", "source_space"}
    assert columns["source_space"]["is_nullable"] == "NO"
    assert columns["source_space"]["column_default"] is None
    with postgres_connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conname = ANY(%s)
            ORDER BY conname
            """,
            (
                [
                    "chk_event_idempotency_source_space",
                    "chk_feed_request_source_space",
                    "chk_query_topic_map_source_space",
                    "chk_system_profile_seed_source_space",
                    "chk_topic_source_space",
                    "chk_user_event_article_required",
                    "chk_user_event_article_space",
                    "chk_user_event_source_space",
                    "chk_user_profile_source_space",
                    "chk_user_topic_profile_source_space",
                ],
            ),
        )
        assert len(cursor.fetchall()) == 10


@pytest.mark.postgres
def test_reset_live_profile_leaves_mind_profile_unchanged(postgres_connection) -> None:
    user_id = 9_100_002
    try:
        reset_demo_user(postgres_connection, user_id, "mind")
        reset_demo_user(postgres_connection, user_id, "live")
        with postgres_connection.transaction(), postgres_connection.cursor() as cursor:
            cursor.execute(
                "UPDATE user_profile SET behavior_score = 42 "
                "WHERE user_id = %s AND source_space = 'mind'",
                (user_id,),
            )
            cursor.execute(
                "UPDATE user_profile SET behavior_score = 7 "
                "WHERE user_id = %s AND source_space = 'live'",
                (user_id,),
            )

        reset_demo_user(postgres_connection, user_id, "live")

        with postgres_connection.cursor() as cursor:
            cursor.execute(
                "SELECT source_space, behavior_score FROM user_profile "
                "WHERE user_id = %s ORDER BY source_space",
                (user_id,),
            )
            assert cursor.fetchall() == [
                {"source_space": "live", "behavior_score": 0.0},
                {"source_space": "mind", "behavior_score": 42.0},
            ]
    finally:
        with postgres_connection.transaction(), postgres_connection.cursor() as cursor:
            cursor.execute("DELETE FROM user_event WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM feed_request WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM event_idempotency WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM user_topic_profile WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM user_profile WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM app_user WHERE user_id = %s", (user_id,))
