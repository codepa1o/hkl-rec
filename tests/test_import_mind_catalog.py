from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.app.repositories.connection import connect, parse_database_url
from scripts.import_mind_catalog import (
    MindCatalogImportError,
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


@pytest.mark.postgres
def test_import_is_idempotent_records_fingerprint_and_preserves_events(
    normalized_catalog: Path,
) -> None:
    database_url = os.environ.get("NEWSREC_DATABASE_URL", "")
    if not database_url:
        pytest.skip("NEWSREC_DATABASE_URL not set")
    connection = connect(parse_database_url(database_url))
    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SELECT current_database() AS database_name")
            assert str(cursor.fetchone()["database_name"]).endswith("_test")
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
                INSERT INTO user_event (user_id, event_type, event_ts)
                VALUES (999999, 'search_query', 1)
                """
            )

        first = import_catalog(normalized_catalog, connection, replace_catalog=True)
        second = import_catalog(normalized_catalog, connection)
        assert first == second
        assert first.news_rows == 3
        assert first.stats_rows == 3

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS count FROM mind_news")
            assert cursor.fetchone()["count"] == 3
            cursor.execute("SELECT COUNT(*) AS count FROM user_event")
            assert cursor.fetchone()["count"] == 1
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
        connection.close()
