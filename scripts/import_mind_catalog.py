from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.data_contracts.mind import (  # noqa: E402
    MindContractError,
    news_internal_id,
    parse_news_id,
)
from backend.app.repositories.connection import (  # noqa: E402
    connect,
    parse_database_url,
)

REQUIRED_OUTPUTS = (
    "articles.parquet",
    "requests_train.parquet",
    "impressions_train.parquet",
    "id_maps.json",
)


class MindCatalogImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class CatalogNews:
    news_id: str
    category: str
    subcategory: str
    title: str
    abstract: str
    url: str
    title_entities: list[dict[str, Any]]
    abstract_entities: list[dict[str, Any]]


@dataclass(frozen=True)
class CatalogNewsStats:
    news_id: str
    first_seen_ts: int | None
    click_count: int
    impression_count: int
    hot_score: float


@dataclass(frozen=True)
class PreparedCatalog:
    normalized_fingerprint: str
    dataset: str
    news: tuple[CatalogNews, ...]
    stats: tuple[CatalogNewsStats, ...]
    train_request_count: int
    train_impression_count: int
    train_click_count: int
    articles_sha256: str
    train_impressions_sha256: str

    @property
    def news_count(self) -> int:
        return len(self.news)


@dataclass(frozen=True)
class ImportResult:
    normalized_fingerprint: str
    news_rows: int
    stats_rows: int
    train_request_count: int
    train_impression_count: int
    train_click_count: int


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MindCatalogImportError(f"Cannot read valid JSON from {path}") from exc
    if not isinstance(value, dict):
        raise MindCatalogImportError(f"Expected a JSON object in {path}")
    return value


def _verify_manifest(normalized_root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    manifest_path = normalized_root / "normalization_manifest.json"
    if not manifest_path.is_file():
        raise MindCatalogImportError(f"Missing normalization manifest: {manifest_path}")
    manifest = _load_json(manifest_path)
    expected_hashes = manifest.get("output_hashes")
    if not isinstance(expected_hashes, dict):
        raise MindCatalogImportError("Normalization manifest lacks output_hashes")

    actual_hashes: dict[str, str] = {}
    for filename in REQUIRED_OUTPUTS:
        path = normalized_root / filename
        if not path.is_file():
            raise MindCatalogImportError(f"Missing normalized output: {path}")
        expected_hash = expected_hashes.get(filename)
        actual_hash = _sha256_file(path)
        if expected_hash != actual_hash:
            raise MindCatalogImportError(
                f"Normalized output checksum mismatch for {filename}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
        actual_hashes[filename] = actual_hash

    all_manifest_hashes = {
        str(filename): str(file_hash) for filename, file_hash in expected_hashes.items()
    }
    computed_fingerprint = hashlib.sha256(
        json.dumps(all_manifest_hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if manifest.get("normalized_fingerprint") != computed_fingerprint:
        raise MindCatalogImportError("Normalization manifest fingerprint mismatch")
    return manifest, actual_hashes


def parse_entity_array(raw: object, field_name: str) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MindCatalogImportError(f"{field_name} must be a valid JSON array") from exc
    else:
        value = raw
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise MindCatalogImportError(f"{field_name} must be a JSON array of objects")
    return value


def _internal_news_mapping(normalized_root: Path) -> dict[int, str]:
    id_maps = _load_json(normalized_root / "id_maps.json")
    raw_mapping = id_maps.get("article_ids")
    if not isinstance(raw_mapping, dict):
        raise MindCatalogImportError("id_maps.json lacks article_ids")

    result: dict[int, str] = {}
    for raw_news_id, raw_internal_id in raw_mapping.items():
        try:
            news_id = parse_news_id(str(raw_news_id))
            internal_id = int(raw_internal_id)
        except (MindContractError, TypeError, ValueError) as exc:
            raise MindCatalogImportError(
                "id_maps.json contains an invalid article mapping"
            ) from exc
        if news_internal_id(news_id) != internal_id:
            raise MindCatalogImportError(
                f"id_maps.json mapping disagrees with canonical ID for {news_id}"
            )
        existing = result.get(internal_id)
        if existing is not None and existing != news_id:
            raise MindCatalogImportError(
                f"Internal article ID {internal_id} maps to both {existing} and {news_id}"
            )
        result[internal_id] = news_id
    return result


def _load_news(
    normalized_root: Path,
    internal_to_news: dict[int, str],
) -> dict[str, CatalogNews]:
    path = normalized_root / "articles.parquet"
    columns = (
        "article_id",
        "news_id",
        "category",
        "subcategory",
        "headline",
        "abstract",
        "source_url",
        "title_entities",
        "abstract_entities",
    )
    news: dict[str, CatalogNews] = {}
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=8192, columns=columns):
        for row in batch.to_pylist():
            try:
                news_id = parse_news_id(str(row["news_id"]))
                internal_id = int(row["article_id"])
            except (MindContractError, TypeError, ValueError) as exc:
                raise MindCatalogImportError(
                    "articles.parquet contains an invalid news ID"
                ) from exc
            if internal_to_news.get(internal_id) != news_id:
                raise MindCatalogImportError(
                    f"articles.parquet and id_maps.json disagree for {news_id}"
                )
            candidate = CatalogNews(
                news_id=news_id,
                category=str(row["category"]),
                subcategory=str(row["subcategory"]),
                title=str(row["headline"]),
                abstract=str(row["abstract"]),
                url=str(row["source_url"]),
                title_entities=parse_entity_array(row["title_entities"], "title_entities"),
                abstract_entities=parse_entity_array(row["abstract_entities"], "abstract_entities"),
            )
            existing = news.get(news_id)
            if existing is not None and existing != candidate:
                raise MindCatalogImportError(f"Conflicting normalized rows for {news_id}")
            news[news_id] = candidate
    if set(news) != set(internal_to_news.values()):
        raise MindCatalogImportError("articles.parquet does not cover every mapped MIND news ID")
    return news


def _load_train_stats(
    normalized_root: Path,
    internal_to_news: dict[int, str],
    news_ids: set[str],
) -> tuple[dict[str, CatalogNewsStats], int, int]:
    aggregate: dict[str, list[int | None]] = {news_id: [None, 0, 0] for news_id in news_ids}
    impression_count = 0
    click_count = 0
    parquet = pq.ParquetFile(normalized_root / "impressions_train.parquet")
    for batch in parquet.iter_batches(
        batch_size=100_000,
        columns=("article_id", "event_ts", "clicked"),
    ):
        for row in batch.to_pylist():
            try:
                news_id = internal_to_news[int(row["article_id"])]
                event_ts = int(row["event_ts"])
            except (KeyError, TypeError, ValueError) as exc:
                raise MindCatalogImportError(
                    "Train impressions contain an article without canonical metadata"
                ) from exc
            first_seen, impressions, clicks = aggregate[news_id]
            aggregate[news_id] = [
                event_ts if first_seen is None else min(int(first_seen), event_ts),
                int(impressions) + 1,
                int(clicks) + int(bool(row["clicked"])),
            ]
            impression_count += 1
            click_count += int(bool(row["clicked"]))

    stats: dict[str, CatalogNewsStats] = {}
    for news_id, (first_seen, impressions, clicks) in aggregate.items():
        typed_impressions = int(impressions)
        typed_clicks = int(clicks)
        ctr = typed_clicks / typed_impressions if typed_impressions else 0.0
        stats[news_id] = CatalogNewsStats(
            news_id=news_id,
            first_seen_ts=int(first_seen) if first_seen is not None else None,
            click_count=typed_clicks,
            impression_count=typed_impressions,
            hot_score=math.log1p(typed_clicks) + ctr,
        )
    return stats, impression_count, click_count


def prepare_catalog(normalized_root: Path) -> PreparedCatalog:
    normalized_root = normalized_root.resolve()
    manifest, hashes = _verify_manifest(normalized_root)
    internal_to_news = _internal_news_mapping(normalized_root)
    news = _load_news(normalized_root, internal_to_news)
    stats, train_impression_count, train_click_count = _load_train_stats(
        normalized_root,
        internal_to_news,
        set(news),
    )
    train_request_count = pq.ParquetFile(
        normalized_root / "requests_train.parquet"
    ).metadata.num_rows
    sorted_news_ids = sorted(news, key=news_internal_id)
    return PreparedCatalog(
        normalized_fingerprint=str(manifest["normalized_fingerprint"]),
        dataset=str(manifest.get("dataset", "MIND-small")),
        news=tuple(news[news_id] for news_id in sorted_news_ids),
        stats=tuple(stats[news_id] for news_id in sorted_news_ids),
        train_request_count=int(train_request_count),
        train_impression_count=train_impression_count,
        train_click_count=train_click_count,
        articles_sha256=hashes["articles.parquet"],
        train_impressions_sha256=hashes["impressions_train.parquet"],
    )


def _database_name(connection: Any) -> str:
    connection_info = getattr(connection, "info", None)
    configured_name = getattr(connection_info, "dbname", None)
    if configured_name:
        return str(configured_name)
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database() AS database_name")
        row = cursor.fetchone()
    if isinstance(row, dict):
        return str(row["database_name"])
    return str(row[0])


def _create_staging_tables(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TEMP TABLE mind_news_import_stage (
            news_id VARCHAR(32) PRIMARY KEY,
            category TEXT NOT NULL,
            subcategory TEXT NOT NULL,
            title TEXT NOT NULL,
            abstract TEXT NOT NULL,
            url TEXT NOT NULL,
            title_entities JSONB NOT NULL,
            abstract_entities JSONB NOT NULL
        ) ON COMMIT DROP
        """
    )
    cursor.execute(
        """
        CREATE TEMP TABLE mind_news_stats_import_stage (
            news_id VARCHAR(32) PRIMARY KEY,
            first_seen_ts BIGINT,
            click_count BIGINT NOT NULL,
            impression_count BIGINT NOT NULL,
            hot_score DOUBLE PRECISION NOT NULL
        ) ON COMMIT DROP
        """
    )


def _copy_staging(cursor: Any, prepared: PreparedCatalog) -> None:
    with cursor.copy(
        """
        COPY mind_news_import_stage (
            news_id, category, subcategory, title, abstract, url,
            title_entities, abstract_entities
        ) FROM STDIN
        """
    ) as copy:
        for row in prepared.news:
            copy.write_row(
                (
                    row.news_id,
                    row.category,
                    row.subcategory,
                    row.title,
                    row.abstract,
                    row.url,
                    json.dumps(row.title_entities, separators=(",", ":"), ensure_ascii=False),
                    json.dumps(row.abstract_entities, separators=(",", ":"), ensure_ascii=False),
                )
            )
    with cursor.copy(
        """
        COPY mind_news_stats_import_stage (
            news_id, first_seen_ts, click_count, impression_count, hot_score
        ) FROM STDIN
        """
    ) as copy:
        for row in prepared.stats:
            copy.write_row(
                (
                    row.news_id,
                    row.first_seen_ts,
                    row.click_count,
                    row.impression_count,
                    row.hot_score,
                )
            )


def _upsert_catalog(cursor: Any, prepared: PreparedCatalog) -> None:
    cursor.execute(
        """
        INSERT INTO mind_catalog_import (
            normalized_fingerprint, dataset, news_count, train_request_count,
            train_impression_count, train_click_count, articles_sha256,
            train_impressions_sha256
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (normalized_fingerprint) DO UPDATE SET
            dataset = EXCLUDED.dataset,
            news_count = EXCLUDED.news_count,
            train_request_count = EXCLUDED.train_request_count,
            train_impression_count = EXCLUDED.train_impression_count,
            train_click_count = EXCLUDED.train_click_count,
            articles_sha256 = EXCLUDED.articles_sha256,
            train_impressions_sha256 = EXCLUDED.train_impressions_sha256,
            imported_at = CURRENT_TIMESTAMP
        """,
        (
            prepared.normalized_fingerprint,
            prepared.dataset,
            prepared.news_count,
            prepared.train_request_count,
            prepared.train_impression_count,
            prepared.train_click_count,
            prepared.articles_sha256,
            prepared.train_impressions_sha256,
        ),
    )
    cursor.execute(
        """
        INSERT INTO mind_news (
            news_id, category, subcategory, title, abstract, url,
            title_entities, abstract_entities
        )
        SELECT
            news_id, category, subcategory, title, abstract, url,
            title_entities, abstract_entities
        FROM mind_news_import_stage
        ON CONFLICT (news_id) DO UPDATE SET
            category = EXCLUDED.category,
            subcategory = EXCLUDED.subcategory,
            title = EXCLUDED.title,
            abstract = EXCLUDED.abstract,
            url = EXCLUDED.url,
            title_entities = EXCLUDED.title_entities,
            abstract_entities = EXCLUDED.abstract_entities
        """
    )
    cursor.execute(
        """
        INSERT INTO mind_news_stats (
            news_id, first_seen_ts, click_count, impression_count,
            hot_score, normalized_fingerprint
        )
        SELECT
            news_id, first_seen_ts, click_count, impression_count,
            hot_score, %s
        FROM mind_news_stats_import_stage
        ON CONFLICT (news_id) DO UPDATE SET
            first_seen_ts = EXCLUDED.first_seen_ts,
            click_count = EXCLUDED.click_count,
            impression_count = EXCLUDED.impression_count,
            hot_score = EXCLUDED.hot_score,
            normalized_fingerprint = EXCLUDED.normalized_fingerprint
        """,
        (prepared.normalized_fingerprint,),
    )
    cursor.execute(
        """
        DELETE FROM mind_news_stats AS stats
        WHERE NOT EXISTS (
            SELECT 1 FROM mind_news_stats_import_stage AS stage
            WHERE stage.news_id = stats.news_id
        )
        """
    )
    cursor.execute(
        """
        DELETE FROM mind_news AS news
        WHERE NOT EXISTS (
            SELECT 1 FROM mind_news_import_stage AS stage
            WHERE stage.news_id = news.news_id
        )
        """
    )
    cursor.execute(
        "DELETE FROM mind_catalog_import WHERE normalized_fingerprint <> %s",
        (prepared.normalized_fingerprint,),
    )


def _count(cursor: Any, table_name: str) -> int:
    cursor.execute(f"SELECT COUNT(*) AS count FROM {table_name}")
    row = cursor.fetchone()
    return int(row["count"] if isinstance(row, dict) else row[0])


def import_catalog(
    normalized_root: Path,
    connection: Any,
    *,
    replace_catalog: bool = False,
) -> ImportResult:
    prepared = prepare_catalog(normalized_root)
    database_name = _database_name(connection)
    if database_name != "newsrec_demo" and not database_name.endswith("_test"):
        raise MindCatalogImportError(
            "Refusing catalog import outside newsrec_demo or a database ending in _test"
        )

    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('mind_catalog_import'))")
            cursor.execute("SELECT normalized_fingerprint FROM mind_catalog_import FOR UPDATE")
            existing = {
                str(row["normalized_fingerprint"] if isinstance(row, dict) else row[0])
                for row in cursor.fetchall()
            }
            different = existing - {prepared.normalized_fingerprint}
            if different and not replace_catalog:
                raise MindCatalogImportError(
                    "Database contains a different MIND catalog fingerprint; "
                    "rerun with --replace-catalog"
                )
            _create_staging_tables(cursor)
            _copy_staging(cursor, prepared)
            if _count(cursor, "mind_news_import_stage") != prepared.news_count:
                raise MindCatalogImportError("Staged MIND news row count does not match manifest")
            if _count(cursor, "mind_news_stats_import_stage") != prepared.news_count:
                raise MindCatalogImportError("Staged MIND stats row count does not match catalog")
            _upsert_catalog(cursor, prepared)
            if _count(cursor, "mind_news") != prepared.news_count:
                raise MindCatalogImportError("Imported MIND news row count does not match catalog")
            if _count(cursor, "mind_news_stats") != prepared.news_count:
                raise MindCatalogImportError("Imported MIND stats row count does not match catalog")

    return ImportResult(
        normalized_fingerprint=prepared.normalized_fingerprint,
        news_rows=prepared.news_count,
        stats_rows=len(prepared.stats),
        train_request_count=prepared.train_request_count,
        train_impression_count=prepared.train_impression_count,
        train_click_count=prepared.train_click_count,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import a complete normalized MIND catalog directly into PostgreSQL."
    )
    parser.add_argument(
        "--normalized-root",
        type=Path,
        default=Path("build/mind_normalized"),
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("NEWSREC_DATABASE_URL", ""),
        help="PostgreSQL URL; defaults to NEWSREC_DATABASE_URL.",
    )
    parser.add_argument("--replace-catalog", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.database_url:
        print("error: --database-url or NEWSREC_DATABASE_URL is required", file=sys.stderr)
        return 2
    connection = connect(parse_database_url(args.database_url), connect_timeout=10)
    try:
        result = import_catalog(
            args.normalized_root,
            connection,
            replace_catalog=args.replace_catalog,
        )
    except MindCatalogImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        connection.close()
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
