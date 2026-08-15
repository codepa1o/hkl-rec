from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.data_contracts.mind import (  # noqa: E402
    MindContractError,
    MindNews,
    MindRequest,
    news_internal_id,
    parse_behavior_row,
    parse_news_row,
    source_domain,
)

SPLITS = ("train", "dev")
ARTICLE_SCHEMA = pa.schema(
    [
        ("article_id", pa.int64()),
        ("news_id", pa.string()),
        ("headline", pa.string()),
        ("abstract", pa.string()),
        ("source_url", pa.string()),
        ("source_domain", pa.string()),
        ("category", pa.string()),
        ("subcategory", pa.string()),
        ("category_topic_id", pa.int32()),
        ("subcategory_topic_id", pa.int32()),
        ("first_seen_any_split_ts", pa.int64()),
        ("first_seen_train_ts", pa.int64()),
        ("first_seen_dev_ts", pa.int64()),
        ("title_entities", pa.string()),
        ("abstract_entities", pa.string()),
    ]
)
REQUEST_SCHEMA = pa.schema(
    [
        ("request_id", pa.string()),
        ("impression_id", pa.string()),
        ("split", pa.string()),
        ("user_id", pa.int64()),
        ("event_ts", pa.int64()),
        ("history_article_ids", pa.list_(pa.int64())),
        ("candidate_count", pa.int32()),
        ("positive_count", pa.int32()),
    ]
)
IMPRESSION_SCHEMA = pa.schema(
    [
        ("request_id", pa.string()),
        ("impression_id", pa.string()),
        ("split", pa.string()),
        ("user_id", pa.int64()),
        ("event_ts", pa.int64()),
        ("candidate_position", pa.int32()),
        ("article_id", pa.int64()),
        ("clicked", pa.bool_()),
    ]
)


class MindNormalizationError(RuntimeError):
    pass


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _iter_tsv(path: Path) -> Iterator[list[str]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            yield line.rstrip("\n").split("\t")


def load_articles(raw_root: Path) -> dict[str, MindNews]:
    articles: dict[str, MindNews] = {}
    article_id_to_news_id: dict[int, str] = {}
    for split in SPLITS:
        path = raw_root / split / "news.tsv"
        if not path.is_file():
            raise MindNormalizationError(f"Missing MIND news file: {path}")
        for line_number, fields in enumerate(_iter_tsv(path), start=1):
            try:
                article = parse_news_row(fields)
            except MindContractError as exc:
                raise MindNormalizationError(f"{path}:{line_number}: {exc}") from exc
            existing = articles.get(article.news_id)
            if existing is not None and existing != article:
                differing_fields = [
                    field_name
                    for field_name in article.__dataclass_fields__
                    if getattr(existing, field_name) != getattr(article, field_name)
                ]
                raise MindNormalizationError(
                    f"Conflicting metadata for {article.news_id} between MIND splits: "
                    f"{differing_fields}"
                )
            article_id = news_internal_id(article.news_id)
            existing_news_id = article_id_to_news_id.get(article_id)
            if existing_news_id is not None and existing_news_id != article.news_id:
                raise MindNormalizationError(
                    f"News IDs {existing_news_id} and {article.news_id} map to the same "
                    f"numeric article ID {article_id}"
                )
            articles[article.news_id] = article
            article_id_to_news_id[article_id] = article.news_id
    return articles


def _iter_requests(raw_root: Path, split: str) -> Iterator[MindRequest]:
    path = raw_root / split / "behaviors.tsv"
    if not path.is_file():
        raise MindNormalizationError(f"Missing MIND behavior file: {path}")
    seen_request_ids: set[str] = set()
    for line_number, fields in enumerate(_iter_tsv(path), start=1):
        try:
            request = parse_behavior_row(fields, split)
        except MindContractError as exc:
            raise MindNormalizationError(f"{path}:{line_number}: {exc}") from exc
        if request.request_id in seen_request_ids:
            raise MindNormalizationError(f"{path}:{line_number}: duplicate {request.request_id}")
        seen_request_ids.add(request.request_id)
        yield request


def scan_requests(
    raw_root: Path,
    articles: dict[str, MindNews],
) -> tuple[dict[str, dict[int, int]], dict[str, dict[str, int]], dict[str, int]]:
    first_seen = {split: {} for split in SPLITS}
    summaries: dict[str, dict[str, int]] = {}
    user_ids: dict[str, int] = {}
    user_id_to_raw_id: dict[int, str] = {}
    metadata_ids = {news_internal_id(article.news_id) for article in articles.values()}

    for split in SPLITS:
        request_count = 0
        candidate_count = 0
        positive_count = 0
        users: set[int] = set()
        for request in _iter_requests(raw_root, split):
            request_count += 1
            users.add(request.user_id)
            existing_raw_user_id = user_id_to_raw_id.get(request.user_id)
            if existing_raw_user_id is not None and existing_raw_user_id != request.raw_user_id:
                raise MindNormalizationError(
                    f"User IDs {existing_raw_user_id} and {request.raw_user_id} map to "
                    f"the same numeric user ID {request.user_id}"
                )
            user_ids[request.raw_user_id] = request.user_id
            user_id_to_raw_id[request.user_id] = request.raw_user_id
            for history_id in request.history_article_ids:
                if history_id not in metadata_ids:
                    raise MindNormalizationError(
                        f"{request.request_id} history article {history_id} lacks metadata"
                    )
            for candidate in request.candidates:
                if candidate.article_id not in metadata_ids:
                    raise MindNormalizationError(
                        f"{request.request_id} candidate {candidate.article_id} lacks metadata"
                    )
                candidate_count += 1
                positive_count += int(candidate.clicked)
                current = first_seen[split].get(candidate.article_id)
                if current is None or request.event_ts < current:
                    first_seen[split][candidate.article_id] = request.event_ts
        summaries[split] = {
            "requests": request_count,
            "candidates": candidate_count,
            "positives": positive_count,
            "users": len(users),
        }
    return first_seen, summaries, user_ids


def build_topic_maps(articles: Iterable[MindNews]) -> dict[str, int]:
    topic_keys = {f"category:{article.category}" for article in articles} | {
        f"subcategory:{article.category}/{article.subcategory}" for article in articles
    }
    return {key: index for index, key in enumerate(sorted(topic_keys), start=1)}


def _write_rows(
    path: Path,
    schema: pa.Schema,
    rows: Iterable[dict[str, Any]],
    *,
    batch_size: int = 50_000,
) -> int:
    count = 0
    batch: list[dict[str, Any]] = []
    writer = pq.ParquetWriter(path, schema, compression="zstd", use_dictionary=True)
    try:
        for row in rows:
            batch.append(row)
            if len(batch) >= batch_size:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                count += len(batch)
                batch.clear()
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))
            count += len(batch)
    finally:
        writer.close()
    return count


def _article_rows(
    articles: dict[str, MindNews],
    topic_ids: dict[str, int],
    first_seen: dict[str, dict[int, int]],
) -> Iterator[dict[str, Any]]:
    for article in sorted(articles.values(), key=lambda value: news_internal_id(value.news_id)):
        article_id = news_internal_id(article.news_id)
        train_ts = first_seen["train"].get(article_id)
        dev_ts = first_seen["dev"].get(article_id)
        observed_timestamps = [value for value in (train_ts, dev_ts) if value is not None]
        selected_ts = min(observed_timestamps) if observed_timestamps else None
        yield {
            "article_id": article_id,
            "news_id": article.news_id,
            "headline": article.title,
            "abstract": article.abstract,
            "source_url": article.url,
            "source_domain": source_domain(article.url),
            "category": article.category,
            "subcategory": article.subcategory,
            "category_topic_id": topic_ids[f"category:{article.category}"],
            "subcategory_topic_id": topic_ids[
                f"subcategory:{article.category}/{article.subcategory}"
            ],
            "first_seen_any_split_ts": selected_ts,
            "first_seen_train_ts": train_ts,
            "first_seen_dev_ts": dev_ts,
            "title_entities": json.dumps(
                article.title_entities, separators=(",", ":"), ensure_ascii=False
            ),
            "abstract_entities": json.dumps(
                article.abstract_entities, separators=(",", ":"), ensure_ascii=False
            ),
        }


def _request_rows(requests: Iterable[MindRequest]) -> Iterator[dict[str, Any]]:
    for request in requests:
        yield {
            "request_id": request.request_id,
            "impression_id": request.impression_id,
            "split": request.split,
            "user_id": request.user_id,
            "event_ts": request.event_ts,
            "history_article_ids": list(request.history_article_ids),
            "candidate_count": len(request.candidates),
            "positive_count": sum(candidate.clicked for candidate in request.candidates),
        }


def _impression_rows(requests: Iterable[MindRequest]) -> Iterator[dict[str, Any]]:
    for request in requests:
        for position, candidate in enumerate(request.candidates):
            yield {
                "request_id": request.request_id,
                "impression_id": request.impression_id,
                "split": request.split,
                "user_id": request.user_id,
                "event_ts": request.event_ts,
                "candidate_position": position,
                "article_id": candidate.article_id,
                "clicked": candidate.clicked,
            }


def _raw_checksums(raw_root: Path) -> dict[str, str]:
    return {
        f"{split}/{filename}": _sha256_file(raw_root / split / filename)
        for split in SPLITS
        for filename in ("news.tsv", "behaviors.tsv")
    }


def normalize_dataset(raw_root: Path, output_root: Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    for filename in (
        "articles.parquet",
        "requests_train.parquet",
        "requests_dev.parquet",
        "impressions_train.parquet",
        "impressions_dev.parquet",
        "id_maps.json",
        "normalization_manifest.json",
    ):
        (output_root / filename).unlink(missing_ok=True)

    articles = load_articles(raw_root)
    first_seen, summaries, user_ids = scan_requests(raw_root, articles)
    topic_ids = build_topic_maps(articles.values())
    article_ids = {
        article.news_id: news_internal_id(article.news_id)
        for article in sorted(
            articles.values(), key=lambda value: news_internal_id(value.news_id)
        )
    }
    article_count = _write_rows(
        output_root / "articles.parquet",
        ARTICLE_SCHEMA,
        _article_rows(articles, topic_ids, first_seen),
    )
    output_counts: dict[str, int] = {"articles.parquet": article_count}
    for split in SPLITS:
        request_name = f"requests_{split}.parquet"
        impression_name = f"impressions_{split}.parquet"
        output_counts[request_name] = _write_rows(
            output_root / request_name,
            REQUEST_SCHEMA,
            _request_rows(_iter_requests(raw_root, split)),
        )
        output_counts[impression_name] = _write_rows(
            output_root / impression_name,
            IMPRESSION_SCHEMA,
            _impression_rows(_iter_requests(raw_root, split)),
        )

    id_maps = {
        "schema_version": 1,
        "article_ids": article_ids,
        "user_ids": dict(sorted(user_ids.items(), key=lambda item: item[1])),
        "topic_ids": topic_ids,
    }
    _write_json(output_root / "id_maps.json", id_maps)

    output_files = [
        "articles.parquet",
        "requests_train.parquet",
        "requests_dev.parquet",
        "impressions_train.parquet",
        "impressions_dev.parquet",
        "id_maps.json",
    ]
    output_hashes = {filename: _sha256_file(output_root / filename) for filename in output_files}
    normalized_fingerprint = hashlib.sha256(
        json.dumps(output_hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "MIND-small",
        "raw_checksums": _raw_checksums(raw_root),
        "output_hashes": output_hashes,
        "output_rows": output_counts,
        "split_summary": summaries,
        "normalized_fingerprint": normalized_fingerprint,
        "provenance": {
            "timestamp_timezone_assumption": "UTC for timezone-naive MIND timestamps",
            "first_seen_any_split_semantics": (
                "serving metadata only; never use as a train feature"
            ),
            "first_seen_train_semantics": "first seen in train impressions only",
            "first_seen_dev_semantics": "first seen in dev impressions only",
            "history_semantics": "pre-request history without fabricated click timestamps",
            "negative_semantics": "exposed candidate with clicked=false",
            "request_namespace": "mind:{split}:{impression_id}",
            "train_outcome_isolation": (
                "train rows and first_seen_train_ts are computed only from train outcomes"
            ),
        },
    }
    _write_json(output_root / "normalization_manifest.json", manifest)
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize raw MIND-small TSV files.")
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/mind/raw/small"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("build/mind_normalized"),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        manifest = normalize_dataset(args.raw_root, args.output_root)
    except MindNormalizationError as exc:
        print(f"error: {exc}")
        return 1
    print(f"normalized {manifest['dataset']} fingerprint={manifest['normalized_fingerprint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
