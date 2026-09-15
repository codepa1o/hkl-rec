from __future__ import annotations

import io
import re
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError

from alembic import command
from backend.app.db.schema import metadata

ROOT = Path(__file__).resolve().parents[1]
BASE_REVISION = "20260816_0007"
DUAL_SPACE_REVISION = "20260817_0009"
CONTENT_REVISION = "20260818_0010"
STRUCTURED_REVISION = "20260821_0011"
HEAD_REVISION = "20260914_0013"
SOURCE_SPACE_TABLES = {
    "topic",
    "query_topic_map",
    "system_profile_seed",
    "user_profile",
    "user_topic_profile",
    "feed_request",
    "event_idempotency",
    "user_event",
}
LIVE_NEWS_COLUMNS = {
    "topic_status",
    "topic_classifier_version",
    "topic_classified_at",
    "topic_input_hash",
    "article_id",
    "canonical_url",
    "source_external_id",
    "title",
    "summary",
    "image_url",
    "publisher",
    "source_domain",
    "language",
    "published_at",
    "published_at_quality",
    "discovered_at",
    "fetched_at",
    "content_hash",
    "status",
    "raw_metadata_json",
    "body_text",
    "body_source",
    "body_status",
    "body_fetched_at",
    "body_content_hash",
    "body_extraction_version",
    "content_rights",
    "body_access_scope",
    "body_document",
    "body_document_version",
    "body_document_hash",
    "body_structure_status",
    "body_structure_updated_at",
    "link_failure_count",
    "last_link_check_at",
    "created_at",
    "updated_at",
}
LIVE_NEWS_INDEXES = {
    "idx_live_news_active_discovered",
    "idx_live_news_language_discovered",
    "idx_live_news_domain_discovered",
    "idx_live_news_content_hash",
}
ORIGINAL_EVENT_TYPES = {
    "search_query",
    "recommendation_click",
    "search_result_click",
    "feed_impression",
    "detail_view",
    "dwell",
    "upvote",
    "downvote",
    "share",
}
ALL_EVENT_TYPES = ORIGINAL_EVENT_TYPES | {"outbound_click"}


def _alembic_config() -> Config:
    return Config(ROOT / "alembic.ini")


def _primary_key_columns(connection: Any, table_name: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON kcu.constraint_name = tc.constraint_name
             AND kcu.constraint_schema = tc.constraint_schema
            WHERE tc.table_schema = current_schema()
              AND tc.table_name = %s
              AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
            """,
            (table_name,),
        )
        return [str(row["column_name"]) for row in cursor.fetchall()]


def _constraint_definitions(connection: Any, table_name: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT constraint_record.conname,
                   pg_get_constraintdef(constraint_record.oid) AS definition
            FROM pg_constraint AS constraint_record
            WHERE constraint_record.conrelid = %s::regclass
            """,
            (table_name,),
        )
        return {
            str(row["conname"]): re.sub(r"\s+", " ", str(row["definition"])).strip()
            for row in cursor.fetchall()
        }


def _check_allowed_values(definition: str) -> set[str]:
    return set(re.findall(r"'([^']+)'", definition))


def _index_definitions(connection: Any, table_name: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT index_class.relname AS index_name,
                   pg_get_indexdef(index_record.indexrelid) AS definition
            FROM pg_index AS index_record
            JOIN pg_class AS index_class ON index_class.oid = index_record.indexrelid
            WHERE index_record.indrelid = %s::regclass
            """,
            (table_name,),
        )
        return {
            str(row["index_name"]): re.sub(r"\s+", " ", str(row["definition"])).strip()
            for row in cursor.fetchall()
        }


def _index_key_expression(definition: str) -> str:
    marker = " USING btree ("
    assert marker in definition
    return definition.split(marker, maxsplit=1)[1].removesuffix(")")


def _prepare_revision_0007(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('alembic_version') AS version_table")
        has_version_table = cursor.fetchone()["version_table"] is not None
        current_revision = None
        if has_version_table:
            cursor.execute("SELECT version_num FROM alembic_version")
            row = cursor.fetchone()
            current_revision = None if row is None else str(row["version_num"])

    config = _alembic_config()
    if current_revision == HEAD_REVISION:
        command.downgrade(config, BASE_REVISION)
    elif current_revision != BASE_REVISION:
        command.upgrade(config, BASE_REVISION)


def test_alembic_has_one_dual_space_head() -> None:
    script = ScriptDirectory.from_config(_alembic_config())

    assert script.get_heads() == [HEAD_REVISION]
    revision = script.get_revision(HEAD_REVISION)
    assert revision is not None
    assert revision.down_revision == "20260914_0012"


def test_dual_space_migration_renders_reserved_seed_guard_in_offline_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.StringIO()
    config = Config(ROOT / "alembic.ini", output_buffer=output)
    monkeypatch.setenv(
        "NEWSREC_DATABASE_URL",
        "postgresql+psycopg://offline:offline@127.0.0.1/offline_dual_space_test",
    )

    command.upgrade(config, f"{BASE_REVISION}:{HEAD_REVISION}", sql=True)

    rendered_sql = output.getvalue()
    assert "DO $$" in rendered_sql
    assert "live_cold_start_default is reserved for the Live news space" in rendered_sql
    assert "CREATE TABLE live_news" in rendered_sql


def test_metadata_scopes_profiles_topics_queries_and_events() -> None:
    for table_name in SOURCE_SPACE_TABLES:
        column = metadata.tables[table_name].c.source_space
        assert column.type.length == 16
        assert column.nullable is False
        if table_name in {"feed_request", "event_idempotency", "user_event"}:
            assert column.server_default is None
        else:
            assert str(column.server_default.arg) == "'mind'"

    assert [column.name for column in metadata.tables["user_profile"].primary_key.columns] == [
        "user_id",
        "source_space",
    ]
    assert [
        column.name for column in metadata.tables["user_topic_profile"].primary_key.columns
    ] == ["user_id", "source_space", "topic_id"]
    assert [column.name for column in metadata.tables["query_topic_map"].primary_key.columns] == [
        "source_space",
        "query_key",
        "topic_id",
    ]

    topic_uniques = {
        constraint.name: [column.name for column in constraint.columns]
        for constraint in metadata.tables["topic"].constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert topic_uniques == {
        "uq_topic_space_key": ["source_space", "topic_key"],
        "uq_topic_id_space": ["topic_id", "source_space"],
    }

    event = metadata.tables["user_event"]
    assert event.c.article_id.type.length == 64
    assert event.c.article_id.nullable is True
    assert "news_id" not in event.c
    event_checks = " ".join(
        str(constraint.sqltext)
        for constraint in event.constraints
        if isinstance(constraint, CheckConstraint)
    )
    assert "outbound_click" in event_checks
    assert {"idx_user_event_space_user_ts"} <= {index.name for index in event.indexes}
    assert "idx_feed_request_space_session" in {
        index.name for index in metadata.tables["feed_request"].indexes
    }


def test_metadata_defines_live_catalog_tables_checks_and_indexes() -> None:
    live_news = metadata.tables["live_news"]
    assert set(live_news.c.keys()) == LIVE_NEWS_COLUMNS
    assert [column.name for column in live_news.primary_key.columns] == ["article_id"]
    assert live_news.c.canonical_url.nullable is False
    assert live_news.c.canonical_url.unique is True
    assert isinstance(live_news.c.raw_metadata_json.type, JSONB)
    assert {index.name for index in live_news.indexes} >= LIVE_NEWS_INDEXES
    assert {constraint.name for constraint in live_news.constraints} >= {
        "chk_live_news_language",
        "chk_live_news_published_at_quality",
        "chk_live_news_status",
        "chk_live_news_body_access_scope",
    }

    checkpoint = metadata.tables["live_news_source_checkpoint"]
    assert set(checkpoint.c.keys()) == {
        "source_name",
        "last_batch_time",
        "last_etag",
        "last_modified",
        "last_success_at",
        "last_error",
        "updated_at",
    }
    assert [column.name for column in checkpoint.primary_key.columns] == ["source_name"]

    import_table = metadata.tables["live_news_import"]
    assert set(import_table.c.keys()) == {
        "batch_id",
        "source_url",
        "source_sha256",
        "fetched_at",
        "raw_count",
        "accepted_count",
        "rejected_count",
        "rejection_summary_json",
        "status",
        "error_message",
    }
    assert isinstance(import_table.c.rejection_summary_json.type, JSONB)
    assert "chk_live_news_import_status" in {
        constraint.name for constraint in import_table.constraints
    }
    assert "user_vector_json" not in metadata.tables["system_profile_seed"].c


def test_postgres_connection_fixture_fails_for_configured_non_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_module = sys.modules["conftest"]
    connection = MagicMock()
    cursor_context = connection.cursor.return_value
    cursor_context.__enter__.return_value.fetchone.return_value = {
        "database_name": "configured_production_database"
    }
    monkeypatch.setattr(fixture_module, "_database_url", lambda: "postgresql://configured")
    monkeypatch.setattr(fixture_module, "parse_database_url", lambda value: value)
    monkeypatch.setattr(fixture_module, "connect", lambda _config: connection)

    fixture_generator = fixture_module.postgres_connection.__wrapped__()
    with pytest.raises(BaseException) as captured:
        next(fixture_generator)

    assert isinstance(captured.value, pytest.fail.Exception)
    connection.rollback.assert_called_once_with()
    connection.close.assert_called_once_with()


def _assert_upgraded_schema(connection: Any, *, user_id: int, news_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        assert cursor.fetchone()["version_num"] == HEAD_REVISION
        cursor.execute(
            """
            SELECT table_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ANY(%s)
              AND column_name = 'source_space'
            """,
            (list(SOURCE_SPACE_TABLES),),
        )
        scoped_columns = cursor.fetchall()
        assert {str(row["table_name"]) for row in scoped_columns} == SOURCE_SPACE_TABLES
        assert all(row["is_nullable"] == "NO" for row in scoped_columns)
        defaults = {str(row["table_name"]): row["column_default"] for row in scoped_columns}
        assert all(
            defaults[table_name] is None
            for table_name in {"feed_request", "event_idempotency", "user_event"}
        )
        assert all(
            "mind" in str(defaults[table_name])
            for table_name in SOURCE_SPACE_TABLES
            - {"feed_request", "event_idempotency", "user_event"}
        )

        cursor.execute("SELECT source_space FROM user_profile WHERE user_id = %s", (user_id,))
        assert cursor.fetchone()["source_space"] == "mind"
        cursor.execute("SELECT article_id FROM user_event WHERE user_id = %s", (user_id,))
        assert cursor.fetchone() == {"article_id": news_id}

        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'live_news'
            """
        )
        assert {str(row["column_name"]) for row in cursor.fetchall()} == LIVE_NEWS_COLUMNS

        cursor.execute(
            """
            SELECT table_name, column_name, column_default
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND (table_name, column_name) IN (
                  ('live_news', 'link_failure_count'),
                  ('live_news', 'created_at'),
                  ('live_news', 'updated_at'),
                  ('live_news_import', 'raw_count'),
                  ('live_news_import', 'accepted_count'),
                  ('live_news_import', 'rejected_count'),
                  ('live_news_import', 'rejection_summary_json'),
                  ('live_news_source_checkpoint', 'updated_at')
              )
            """
        )
        defaults = {
            (str(row["table_name"]), str(row["column_name"])): str(row["column_default"])
            for row in cursor.fetchall()
        }
        assert defaults == {
            ("live_news", "link_failure_count"): "0",
            ("live_news", "created_at"): "CURRENT_TIMESTAMP",
            ("live_news", "updated_at"): "CURRENT_TIMESTAMP",
            ("live_news_import", "raw_count"): "0",
            ("live_news_import", "accepted_count"): "0",
            ("live_news_import", "rejected_count"): "0",
            ("live_news_import", "rejection_summary_json"): "'{}'::jsonb",
            ("live_news_source_checkpoint", "updated_at"): "CURRENT_TIMESTAMP",
        }

        cursor.execute(
            """
            SELECT source_space, topic_weights_json, recent_clicked_news_json,
                   recent_queries_json, behavior_score, notes
            FROM system_profile_seed WHERE seed_key = 'live_cold_start_default'
            """
        )
        assert cursor.fetchone() == {
            "source_space": "live",
            "topic_weights_json": [],
            "recent_clicked_news_json": [],
            "recent_queries_json": [],
            "behavior_score": 0.0,
            "notes": "Empty cold-start profile for the live news space.",
        }

    expected_constraints = {
        ("user_profile", "pk_user_profile"): "PRIMARY KEY (user_id, source_space)",
        (
            "user_topic_profile",
            "pk_user_topic_profile",
        ): "PRIMARY KEY (user_id, source_space, topic_id)",
        (
            "query_topic_map",
            "pk_query_topic_map",
        ): "PRIMARY KEY (source_space, query_key, topic_id)",
        ("topic", "uq_topic_space_key"): "UNIQUE (source_space, topic_key)",
        ("live_news", "pk_live_news"): "PRIMARY KEY (article_id)",
        ("live_news", "uq_live_news_canonical_url"): "UNIQUE (canonical_url)",
        (
            "live_news_source_checkpoint",
            "pk_live_news_source_checkpoint",
        ): "PRIMARY KEY (source_name)",
        ("live_news_import", "pk_live_news_import"): "PRIMARY KEY (batch_id)",
    }
    constraint_cache: dict[str, dict[str, str]] = {}
    for (table_name, constraint_name), expected_definition in expected_constraints.items():
        definitions = constraint_cache.setdefault(
            table_name, _constraint_definitions(connection, table_name)
        )
        assert definitions[constraint_name] == expected_definition

    check_expectations = {
        ("live_news", "chk_live_news_language", "language"): {"zh", "en"},
        ("live_news", "chk_live_news_status", "status"): {"active", "inactive"},
        (
            "live_news",
            "chk_live_news_body_access_scope",
            "body_access_scope",
        ): {"public", "local_research"},
        (
            "live_news",
            "chk_live_news_published_at_quality",
            "published_at_quality",
        ): {"gdelt_unverified", "publisher", "unknown"},
        (
            "live_news_import",
            "chk_live_news_import_status",
            "status",
        ): {"fetching", "completed", "failed"},
        ("user_event", "chk_user_event_event_type", "event_type"): ALL_EVENT_TYPES,
    }
    for (table_name, constraint_name, column_name), allowed_values in check_expectations.items():
        definitions = constraint_cache.setdefault(
            table_name, _constraint_definitions(connection, table_name)
        )
        definition = definitions[constraint_name]
        assert definition.startswith("CHECK (")
        assert column_name in definition
        assert _check_allowed_values(definition) == allowed_values

    expected_indexes = {
        ("live_news", "idx_live_news_active_discovered"): (
            "status, discovered_at DESC, article_id"
        ),
        ("live_news", "idx_live_news_language_discovered"): (
            "language, discovered_at DESC, article_id"
        ),
        ("live_news", "idx_live_news_domain_discovered"): (
            "source_domain, discovered_at DESC, article_id"
        ),
        ("live_news", "idx_live_news_content_hash"): "content_hash",
        ("user_event", "idx_user_event_space_user_ts"): "source_space, user_id, event_ts",
        (
            "feed_request",
            "idx_feed_request_space_session",
        ): "source_space, session_id, page_number",
    }
    index_cache: dict[str, dict[str, str]] = {}
    for (table_name, index_name), expected_keys in expected_indexes.items():
        definitions = index_cache.setdefault(table_name, _index_definitions(connection, table_name))
        assert _index_key_expression(definitions[index_name]) == expected_keys


def _assert_live_constraints_behavior(connection: Any, *, user_id: int) -> None:
    from psycopg.errors import CheckViolation, UniqueViolation

    insert_live_news = """
        INSERT INTO live_news (
            article_id, canonical_url, title, summary, publisher, source_domain,
            language, published_at_quality, discovered_at, fetched_at,
            content_hash, status, raw_metadata_json
        ) VALUES (
            %s, %s, 'Title', 'Summary', 'Publisher', 'example.test',
            %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            %s, '{}'::jsonb
        )
    """
    with connection.cursor() as cursor:
        cursor.execute("BEGIN")
        try:
            cursor.execute(
                insert_live_news,
                (
                    "L0123456789abcdef0123456789abcdef",
                    "https://example.test/valid",
                    "zh",
                    "publisher",
                    "active",
                ),
            )
            cursor.execute(
                """
                INSERT INTO live_news_import (batch_id, source_url, fetched_at, status)
                VALUES ('valid-live-import', 'https://example.test/feed', CURRENT_TIMESTAMP, 'fetching')
                """
            )
            cursor.execute(
                """
                INSERT INTO user_event (
                    user_id, event_type, article_id, event_ts, source_space
                ) VALUES (
                    %s, 'outbound_click',
                    'L0123456789abcdef0123456789abcdef', 2, 'live'
                )
                """,
                (user_id,),
            )

            invalid_articles = (
                ("invalid-language", "https://example.test/language", "fr", "publisher", "active"),
                ("invalid-quality", "https://example.test/quality", "en", "rss", "active"),
                ("invalid-status", "https://example.test/status", "en", "unknown", "draft"),
            )
            for savepoint_index, parameters in enumerate(invalid_articles):
                savepoint = f"invalid_live_news_{savepoint_index}"
                cursor.execute(f"SAVEPOINT {savepoint}")
                with pytest.raises(CheckViolation):
                    cursor.execute(insert_live_news, parameters)
                cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")

            cursor.execute("SAVEPOINT invalid_import_status")
            with pytest.raises(CheckViolation):
                cursor.execute(
                    """
                    INSERT INTO live_news_import (batch_id, source_url, fetched_at, status)
                    VALUES (
                        'invalid-live-import', 'https://example.test/feed',
                        CURRENT_TIMESTAMP, 'pending'
                    )
                    """
                )
            cursor.execute("ROLLBACK TO SAVEPOINT invalid_import_status")

            cursor.execute("SAVEPOINT duplicate_canonical_url")
            with pytest.raises(UniqueViolation):
                cursor.execute(
                    insert_live_news,
                    (
                        "L1123456789abcdef0123456789abcdef",
                        "https://example.test/valid",
                        "en",
                        "unknown",
                        "inactive",
                    ),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT duplicate_canonical_url")
        finally:
            cursor.execute("ROLLBACK")


def _assert_downgraded_schema(
    connection: Any,
    *,
    user_id: int,
    topic_id: int,
    news_id: str,
    seed_key: str,
    outbound_external_event_id: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        assert cursor.fetchone()["version_num"] == BASE_REVISION
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ANY(%s)
              AND column_name = 'source_space'
            """,
            (list(SOURCE_SPACE_TABLES),),
        )
        assert cursor.fetchall() == []
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'user_event'
              AND column_name = 'article_id'
            """
        )
        assert cursor.fetchone() is None
        cursor.execute(
            "SELECT to_regclass(table_name) AS table_object "
            "FROM unnest(%s::text[]) AS requested_tables(table_name)",
            (["live_news", "live_news_source_checkpoint", "live_news_import"],),
        )
        assert all(row["table_object"] is None for row in cursor.fetchall())
        cursor.execute(
            "SELECT to_regclass(index_name) AS index_object "
            "FROM unnest(%s::text[]) AS requested_indexes(index_name)",
            (["idx_user_event_space_user_ts", "idx_feed_request_space_session"],),
        )
        assert all(row["index_object"] is None for row in cursor.fetchall())
        cursor.execute(
            "SELECT COUNT(*) AS seed_count FROM system_profile_seed "
            "WHERE seed_key = 'live_cold_start_default'"
        )
        assert cursor.fetchone()["seed_count"] == 0
        cursor.execute(
            "SELECT COUNT(*) AS event_count FROM user_event "
            "WHERE external_event_id = %s OR event_type = 'outbound_click'",
            (outbound_external_event_id,),
        )
        assert cursor.fetchone()["event_count"] == 0
        cursor.execute(
            "SELECT COUNT(*) AS idempotency_count FROM event_idempotency "
            "WHERE external_event_id = %s OR event_type = 'outbound_click'",
            (outbound_external_event_id,),
        )
        assert cursor.fetchone()["idempotency_count"] == 0

        cursor.execute(
            """
            SELECT
                EXISTS(SELECT 1 FROM app_user WHERE user_id = %s) AS user_survives,
                EXISTS(SELECT 1 FROM user_profile WHERE user_id = %s) AS profile_survives,
                EXISTS(SELECT 1 FROM topic WHERE topic_id = %s) AS topic_survives,
                EXISTS(SELECT 1 FROM mind_news WHERE news_id = %s) AS news_survives,
                EXISTS(
                    SELECT 1 FROM user_event
                    WHERE user_id = %s AND news_id = %s AND event_type = 'detail_view'
                ) AS event_survives,
                EXISTS(
                    SELECT 1 FROM system_profile_seed WHERE seed_key = %s
                ) AS seed_survives
            """,
            (user_id, user_id, topic_id, news_id, user_id, news_id, seed_key),
        )
        assert all(cursor.fetchone().values())

    assert _primary_key_columns(connection, "user_profile") == ["user_id"]
    assert _primary_key_columns(connection, "user_topic_profile") == ["user_id", "topic_id"]
    assert _primary_key_columns(connection, "query_topic_map") == ["query_key", "topic_id"]
    assert _constraint_definitions(connection, "topic")["uq_topic_topic_key"] == (
        "UNIQUE (topic_key)"
    )
    event_check = _constraint_definitions(connection, "user_event")["chk_user_event_event_type"]
    assert _check_allowed_values(event_check) == ORIGINAL_EVENT_TYPES


@pytest.mark.postgres
def test_upgrade_backfills_existing_rows_and_downgrade_reupgrade_round_trip(
    postgres_connection: Any,
) -> None:
    postgres_connection.autocommit = True
    _prepare_revision_0007(postgres_connection)
    user_id = 9_223_372_036_854_770_001
    topic_id = 9_223_372_036_854_770_002
    news_id = "N9223372036854770001"
    seed_key = "dual_space_schema_test_seed"
    outbound_external_event_id = "dual-space-mind-outbound-click"
    config = _alembic_config()

    try:
        with postgres_connection.cursor() as cursor:
            cursor.execute("DELETE FROM user_event WHERE user_id = %s", (user_id,))
            cursor.execute(
                "DELETE FROM event_idempotency WHERE external_event_id = %s",
                (outbound_external_event_id,),
            )
            cursor.execute("DELETE FROM user_profile WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM app_user WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM mind_news WHERE news_id = %s", (news_id,))
            cursor.execute("DELETE FROM topic WHERE topic_id = %s", (topic_id,))
            cursor.execute("DELETE FROM system_profile_seed WHERE seed_key = %s", (seed_key,))
            cursor.execute(
                """
                INSERT INTO system_profile_seed (
                    seed_key, topic_weights_json, recent_clicked_news_json,
                    recent_queries_json, behavior_score, notes
                ) VALUES (%s, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 0, 'migration test')
                """,
                (seed_key,),
            )
            cursor.execute(
                "INSERT INTO app_user (user_id, display_name) VALUES (%s, 'Dual space test')",
                (user_id,),
            )
            cursor.execute(
                """
                INSERT INTO user_profile (
                    user_id, cold_start_seed_key, topic_weights_json,
                    recent_clicked_news_json, recent_queries_json
                ) VALUES (%s, %s, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb)
                """,
                (user_id, seed_key),
            )
            cursor.execute(
                "INSERT INTO topic (topic_id, topic_key, display_name) VALUES (%s, %s, %s)",
                (topic_id, "dual-space-test", "Dual space test"),
            )
            cursor.execute(
                """
                INSERT INTO mind_news (
                    news_id, category, subcategory, title, abstract, url,
                    title_entities, abstract_entities
                ) VALUES (%s, 'test', 'test', 'Test', '', '', '[]'::jsonb, '[]'::jsonb)
                """,
                (news_id,),
            )
            cursor.execute(
                """
                INSERT INTO user_event (user_id, event_type, news_id, event_ts)
                VALUES (%s, 'detail_view', %s, 1)
                """,
                (user_id, news_id),
            )

        command.upgrade(config, "head")
        _assert_upgraded_schema(postgres_connection, user_id=user_id, news_id=news_id)
        _assert_live_constraints_behavior(postgres_connection, user_id=user_id)
        with postgres_connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO event_idempotency (
                    external_event_id, payload_fingerprint, user_id,
                    event_type, source_space
                ) VALUES (%s, %s, %s, 'outbound_click', 'mind')
                """,
                (outbound_external_event_id, "b" * 64, user_id),
            )
            cursor.execute(
                """
                INSERT INTO user_event (
                    external_event_id, user_id, event_type, article_id,
                    event_ts, source_space
                ) VALUES (%s, %s, 'outbound_click', %s, 3, 'mind')
                """,
                (outbound_external_event_id, user_id, news_id),
            )

        command.downgrade(config, BASE_REVISION)
        _assert_downgraded_schema(
            postgres_connection,
            user_id=user_id,
            topic_id=topic_id,
            news_id=news_id,
            seed_key=seed_key,
            outbound_external_event_id=outbound_external_event_id,
        )

        command.upgrade(config, "head")
        _assert_upgraded_schema(postgres_connection, user_id=user_id, news_id=news_id)
        _assert_live_constraints_behavior(postgres_connection, user_id=user_id)
    finally:
        with postgres_connection.cursor() as cursor:
            cursor.execute("DELETE FROM user_event WHERE user_id = %s", (user_id,))
            cursor.execute(
                "DELETE FROM event_idempotency WHERE external_event_id = %s",
                (outbound_external_event_id,),
            )
            cursor.execute("DELETE FROM user_profile WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM app_user WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM mind_news WHERE news_id = %s", (news_id,))
            cursor.execute("DELETE FROM topic WHERE topic_id = %s", (topic_id,))
            cursor.execute("DELETE FROM system_profile_seed WHERE seed_key = %s", (seed_key,))
            cursor.execute("SELECT version_num FROM alembic_version")
            current_revision = str(cursor.fetchone()["version_num"])
        if current_revision != HEAD_REVISION:
            command.upgrade(config, "head")


@pytest.mark.postgres
def test_upgrade_rejects_reserved_live_seed_collision_without_mutating_legacy_rows(
    postgres_connection: Any,
) -> None:
    from psycopg.errors import RaiseException

    postgres_connection.autocommit = True
    _prepare_revision_0007(postgres_connection)
    user_id = 9_223_372_036_854_770_003
    seed_key = "live_cold_start_default"
    config = _alembic_config()
    expected_seed = {
        "topic_weights_json": [{"topic_id": 42, "weight": 0.75}],
        "recent_clicked_news_json": ["N42"],
        "recent_queries_json": ["legacy query"],
        "behavior_score": 17.25,
        "notes": "legacy reserved-key seed",
    }
    expected_profile = {
        "topic_weights_json": [{"topic_id": 7, "weight": 0.5}],
        "recent_clicked_news_json": ["N7"],
        "recent_queries_json": ["legacy profile query"],
        "behavior_score": 3.5,
        "user_vector_json": {"vector": [1, 2]},
        "notes": "legacy profile content",
    }

    try:
        with postgres_connection.cursor() as cursor:
            cursor.execute("DELETE FROM user_profile WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM app_user WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM system_profile_seed WHERE seed_key = %s", (seed_key,))
            cursor.execute(
                """
                INSERT INTO system_profile_seed (
                    seed_key, topic_weights_json, recent_clicked_news_json,
                    recent_queries_json, behavior_score, notes
                ) VALUES (%s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
                """,
                (
                    seed_key,
                    '[{"topic_id": 42, "weight": 0.75}]',
                    '["N42"]',
                    '["legacy query"]',
                    17.25,
                    "legacy reserved-key seed",
                ),
            )
            cursor.execute(
                "INSERT INTO app_user (user_id, display_name) VALUES (%s, 'Seed collision test')",
                (user_id,),
            )
            cursor.execute(
                """
                INSERT INTO user_profile (
                    user_id, cold_start_seed_key, topic_weights_json,
                    recent_clicked_news_json, recent_queries_json,
                    behavior_score, user_vector_json, notes
                ) VALUES (
                    %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s::jsonb, %s
                )
                """,
                (
                    user_id,
                    seed_key,
                    '[{"topic_id": 7, "weight": 0.5}]',
                    '["N7"]',
                    '["legacy profile query"]',
                    3.5,
                    '{"vector": [1, 2]}',
                    "legacy profile content",
                ),
            )

        with pytest.raises(DBAPIError) as captured:
            command.upgrade(config, "head")
        assert isinstance(captured.value.orig, RaiseException)
        assert "live_cold_start_default is reserved" in str(captured.value.orig)

        with postgres_connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone()["version_num"] == BASE_REVISION
            cursor.execute(
                """
                SELECT topic_weights_json, recent_clicked_news_json,
                       recent_queries_json, behavior_score, notes
                FROM system_profile_seed WHERE seed_key = %s
                """,
                (seed_key,),
            )
            assert cursor.fetchone() == expected_seed
            cursor.execute(
                """
                SELECT topic_weights_json, recent_clicked_news_json,
                       recent_queries_json, behavior_score, user_vector_json, notes
                FROM user_profile WHERE user_id = %s
                """,
                (user_id,),
            )
            assert cursor.fetchone() == expected_profile
            cursor.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'system_profile_seed'
                  AND column_name = 'source_space'
                """
            )
            assert cursor.fetchone() is None
    finally:
        with postgres_connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            current_revision = str(cursor.fetchone()["version_num"])
        if current_revision == HEAD_REVISION:
            command.downgrade(config, BASE_REVISION)
        with postgres_connection.cursor() as cursor:
            cursor.execute("DELETE FROM user_profile WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM app_user WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM system_profile_seed WHERE seed_key = %s", (seed_key,))
        command.upgrade(config, "head")
