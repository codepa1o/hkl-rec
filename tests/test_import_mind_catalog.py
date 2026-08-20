from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend.app.repositories.connection import connect, parse_database_url
from scripts.import_mind_catalog import (
    MindCatalogImportError,
    _assert_replacement_has_no_removed_news_references,
    import_catalog,
    parse_entity_array,
    prepare_catalog,
)
from scripts.normalize_mind import normalize_dataset


def _write_split(
    root: Path,
    split: str,
    *,
    news_rows: list[str],
    behavior_rows: list[str],
) -> None:
    split_root = root / split
    split_root.mkdir(parents=True)
    (split_root / "news.tsv").write_text("\n".join(news_rows) + "\n", encoding="utf-8")
    (split_root / "behaviors.tsv").write_text("\n".join(behavior_rows) + "\n", encoding="utf-8")


@pytest.fixture
def normalized_catalog(tmp_path: Path) -> Path:
    raw_root = tmp_path / "raw"
    train_news = [
        "N1\tNews\tLocal\tOne\tFirst abstract\thttps://example.com/1\t[]\t[]",
        ('N2\tSports\tGolf\tTwo\t\thttps://example.com/2\t[{"Label":"Tiger Woods"}]\t[]'),
    ]
    dev_news = [
        *train_news,
        "N3\tFinance\tMarkets\tThree\tDev only\thttps://example.com/3\t[]\t[]",
    ]
    _write_split(
        raw_root,
        "train",
        news_rows=train_news,
        behavior_rows=[
            "1\tU1\t11/13/2019 8:36:57 AM\t\tN1-0 N2-1",
            "2\tU2\t11/13/2019 9:36:57 AM\tN1\tN2-1 N1-1",
        ],
    )
    _write_split(
        raw_root,
        "dev",
        news_rows=dev_news,
        behavior_rows=["1\tU1\t11/14/2019 8:36:57 AM\tN2\tN3-1 N1-1"],
    )
    output_root = tmp_path / "normalized"
    normalize_dataset(raw_root, output_root)
    return output_root


def test_prepare_catalog_preserves_news_and_uses_only_train_outcomes(
    normalized_catalog: Path,
) -> None:
    prepared = prepare_catalog(normalized_catalog)

    assert prepared.news_count == 3
    assert prepared.train_request_count == 2
    assert prepared.train_impression_count == 4
    assert prepared.train_click_count == 3
    topics = {row.key: row for row in prepared.topics}
    assert topics["category:News"].news_count == 1
    assert topics["subcategory:Sports/Golf"].display_name == "Golf"
    assert topics["subcategory:Sports/Golf"].news_count == 1
    assert len(prepared.news_topics) == 6
    mappings = {(row.news_id, row.source_rank): row.topic_id for row in prepared.news_topics}
    assert mappings[("N2", 0)] == topics["category:Sports"].topic_id
    assert mappings[("N2", 1)] == topics["subcategory:Sports/Golf"].topic_id

    news = {row.news_id: row for row in prepared.news}
    assert news["N1"].title == "One"
    assert news["N1"].abstract == "First abstract"
    assert news["N2"].title_entities == [{"Label": "Tiger Woods"}]

    stats = {row.news_id: row for row in prepared.stats}
    assert (stats["N1"].impression_count, stats["N1"].click_count) == (2, 1)
    assert (stats["N2"].impression_count, stats["N2"].click_count) == (2, 2)
    assert (stats["N3"].impression_count, stats["N3"].click_count) == (0, 0)
    assert stats["N3"].first_seen_ts is None


def test_prepare_catalog_rejects_a_manifest_hash_mismatch(normalized_catalog: Path) -> None:
    with (normalized_catalog / "id_maps.json").open("a", encoding="utf-8") as handle:
        handle.write(" ")

    with pytest.raises(MindCatalogImportError, match="checksum"):
        prepare_catalog(normalized_catalog)


@pytest.mark.parametrize("raw", ["{}", '"entity"', "null", "1", "[1]"])
def test_parse_entity_array_rejects_non_object_arrays(raw: str) -> None:
    with pytest.raises(MindCatalogImportError, match="array"):
        parse_entity_array(raw, "title_entities")


def test_catalog_replacement_reports_referenced_removed_news() -> None:
    class Cursor:
        def execute(self, _sql: str) -> None:
            return None

        def fetchone(self) -> dict[str, int]:
            return {
                "user_events": 2,
                "sponsored_creatives": 1,
                "sponsored_deliveries": 0,
            }

    with pytest.raises(MindCatalogImportError, match="user_events=2"):
        _assert_replacement_has_no_removed_news_references(Cursor())


@pytest.mark.postgres
def test_import_is_idempotent_records_fingerprint_and_preserves_events(
    normalized_catalog: Path,
) -> None:
    database_url = os.environ.get("NEWSREC_DATABASE_URL", "")
    if not database_url:
        pytest.skip("NEWSREC_DATABASE_URL not set")
    connection = connect(parse_database_url(database_url))
    try:
        with connection.cursor() as cursor:
            cursor.execute("BEGIN")
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SELECT current_database() AS database_name")
            if not str(cursor.fetchone()["database_name"]).endswith("_test"):
                pytest.skip("destructive importer integration requires a database ending in _test")
            cursor.execute("DELETE FROM user_event")
            cursor.execute("DELETE FROM sponsored_delivery")
            cursor.execute("DELETE FROM sponsored_creative")
            cursor.execute("DELETE FROM mind_news_stats")
            cursor.execute("DELETE FROM mind_news")
            cursor.execute("DELETE FROM mind_catalog_import")
            cursor.execute(
                """
                INSERT INTO app_user (user_id, display_name)
                VALUES (999999, 'import-preservation-test')
                ON CONFLICT (user_id) DO NOTHING
                """
            )
            cursor.execute(
                """
                INSERT INTO user_event (source_space, user_id, event_type, event_ts)
                VALUES ('mind', 999999, 'search_query', 1)
                """
            )

        prepared = prepare_catalog(normalized_catalog)
        first = import_catalog(normalized_catalog, connection, replace_catalog=True)
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP TABLE mind_topic_import_stage, mind_news_import_stage, "
                "mind_news_topic_import_stage, mind_news_stats_import_stage"
            )
        second = import_catalog(normalized_catalog, connection)
        assert first == second
        assert first.news_rows == 3
        assert first.stats_rows == 3
        assert first.topic_rows == len(prepared.topics)
        assert first.news_topic_rows == 6

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS count FROM mind_news")
            assert cursor.fetchone()["count"] == 3
            cursor.execute("SELECT COUNT(*) AS count FROM user_event")
            assert cursor.fetchone()["count"] == 1
            cursor.execute("SELECT COUNT(*) AS count FROM mind_news_topic")
            assert cursor.fetchone()["count"] == 6
            cursor.execute(
                """
                SELECT MIN(topic_count) AS minimum, MAX(topic_count) AS maximum
                FROM (
                    SELECT news_id, COUNT(*) AS topic_count
                    FROM mind_news_topic
                    GROUP BY news_id
                ) AS counts
                """
            )
            counts = cursor.fetchone()
            assert (counts["minimum"], counts["maximum"]) == (2, 2)
            cursor.execute(
                "SELECT COUNT(*) AS count FROM query_topic_map WHERE source_space = 'mind'"
            )
            assert cursor.fetchone()["count"] == len(prepared.topics)
            cursor.execute(
                """
                SELECT normalized_fingerprint, news_count
                FROM mind_catalog_import
                """
            )
            import_row = cursor.fetchone()
            assert import_row["normalized_fingerprint"] == first.normalized_fingerprint
            assert import_row["news_count"] == 3
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.postgres
def test_mind_import_never_changes_live_catalog_or_profile_state(
    normalized_catalog: Path,
) -> None:
    database_url = os.environ.get("NEWSREC_DATABASE_URL", "")
    if not database_url:
        pytest.skip("NEWSREC_DATABASE_URL not set")
    connection = connect(parse_database_url(database_url))
    live_user_id = 9_100_001
    live_topic_id = 9_100_001
    live_query_key = "live:test:mind-import-isolation"
    try:
        with connection.cursor() as cursor:
            cursor.execute("BEGIN")
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SELECT current_database() AS database_name")
            if not str(cursor.fetchone()["database_name"]).endswith("_test"):
                pytest.fail("MIND import isolation test requires a database ending in _test")
            cursor.execute("DELETE FROM sponsored_delivery")
            cursor.execute("DELETE FROM sponsored_creative")
            cursor.execute(
                "INSERT INTO app_user (user_id, display_name) VALUES (%s, %s) "
                "ON CONFLICT (user_id) DO NOTHING",
                (live_user_id, "live-import-isolation"),
            )
            cursor.execute(
                """
                INSERT INTO topic (
                    topic_id, source_space, topic_key, display_name, news_count, source
                ) VALUES (%s, 'live', %s, 'Live isolation topic', 1, 'live')
                ON CONFLICT (topic_id) DO UPDATE SET
                    source_space = 'live', topic_key = EXCLUDED.topic_key,
                    display_name = EXCLUDED.display_name, news_count = 1, source = 'live'
                """,
                (live_topic_id, "live:test/mind-import-isolation"),
            )
            cursor.execute(
                """
                INSERT INTO query_topic_map (
                    source_space, query_key, topic_id, score, match_rank, source_method
                ) VALUES ('live', %s, %s, 1, 0, 'test')
                ON CONFLICT (source_space, query_key, topic_id) DO NOTHING
                """,
                (live_query_key, live_topic_id),
            )
            cursor.execute(
                """
                INSERT INTO user_profile (
                    user_id, source_space, cold_start_seed_key, topic_weights_json,
                    recent_clicked_news_json, recent_queries_json, behavior_score, notes
                ) VALUES (
                    %s, 'live', 'live_cold_start_default',
                    %s::jsonb, '[]'::jsonb, '[]'::jsonb, 0, 'isolation test'
                )
                ON CONFLICT (user_id, source_space) DO UPDATE SET
                    topic_weights_json = EXCLUDED.topic_weights_json
                """,
                (live_user_id, json.dumps([{"topic_id": live_topic_id, "weight": 1.0}])),
            )
            cursor.execute("SELECT COUNT(*) AS count FROM live_news")
            live_news_before = int(cursor.fetchone()["count"])

        import_catalog(normalized_catalog, connection, replace_catalog=True)

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS count FROM live_news")
            assert int(cursor.fetchone()["count"]) == live_news_before
            cursor.execute(
                "SELECT source_space, topic_key FROM topic WHERE topic_id = %s",
                (live_topic_id,),
            )
            assert cursor.fetchone() == {
                "source_space": "live",
                "topic_key": "live:test/mind-import-isolation",
            }
            cursor.execute(
                "SELECT COUNT(*) AS count FROM query_topic_map "
                "WHERE source_space = 'live' AND query_key = %s AND topic_id = %s",
                (live_query_key, live_topic_id),
            )
            assert int(cursor.fetchone()["count"]) == 1
            cursor.execute(
                "SELECT topic_weights_json FROM user_profile "
                "WHERE user_id = %s AND source_space = 'live'",
                (live_user_id,),
            )
            assert cursor.fetchone()["topic_weights_json"] == [
                {"topic_id": live_topic_id, "weight": 1.0}
            ]
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM user_profile WHERE user_id = %s AND source_space = 'live'",
                (live_user_id,),
            )
            cursor.execute(
                "DELETE FROM query_topic_map WHERE source_space = 'live' AND query_key = %s",
                (live_query_key,),
            )
            cursor.execute(
                "DELETE FROM topic WHERE topic_id = %s AND source_space = 'live'",
                (live_topic_id,),
            )
            cursor.execute("DELETE FROM app_user WHERE user_id = %s", (live_user_id,))
        connection.rollback()
        connection.close()
