from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from backend.app.data_contracts.mind import (
    MindContractError,
    parse_news_id,
    parse_user_id,
)
from scripts.normalize_mind import MindNormalizationError, normalize_dataset


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
    (split_root / "behaviors.tsv").write_text(
        "\n".join(behavior_rows) + "\n",
        encoding="utf-8",
    )


def _fixture(root: Path) -> None:
    train_news = [
        "N1\tNews\tLocal\tOne\tFirst abstract\thttps://www.msn.com/one\t[]\t[]",
        "N2\tSports\tGolf\tTwo\t\thttps://sports.example.com/two\t[]\t[]",
        "N3\tNews\tLocal\tThree\tThird abstract\thttps://www.msn.com/three\t[]\t[]",
    ]
    dev_news = [
        *train_news,
        "N4\tFinance\tMarkets\tFour\tFourth abstract\thttps://finance.example/four\t[]\t[]",
    ]
    _write_split(
        root,
        "train",
        news_rows=train_news,
        behavior_rows=[
            "1\tU1\t11/13/2019 8:36:57 AM\t\tN1-0 N2-1",
            "2\tU2\t11/13/2019 9:36:57 AM\tN1 N2\tN3-1 N2-1",
        ],
    )
    _write_split(
        root,
        "dev",
        news_rows=dev_news,
        behavior_rows=[
            "1\tU1\t11/14/2019 8:36:57 AM\tN2\tN1-1 N4-0",
        ],
    )


def test_mind_ids_require_expected_prefixes():
    assert parse_news_id("N123") == "N123"
    assert parse_user_id("U456") == 456
    with pytest.raises(MindContractError):
        parse_news_id("123")
    with pytest.raises(MindContractError):
        parse_user_id("user-456")


def test_normalizer_writes_item_impressions_and_stable_fingerprint(tmp_path: Path):
    raw_root = tmp_path / "raw"
    _fixture(raw_root)
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"

    first = normalize_dataset(raw_root, first_output)
    second = normalize_dataset(raw_root, second_output)

    assert first["normalized_fingerprint"] == second["normalized_fingerprint"]
    assert first["split_summary"]["train"]["candidates"] == 4
    assert first["split_summary"]["train"]["positives"] == 3
    assert first["output_rows"]["impressions_train.parquet"] == 4
    train = pq.read_table(first_output / "impressions_train.parquet").to_pylist()
    assert {row["request_id"] for row in train} == {"mind:train:1", "mind:train:2"}
    assert sum(row["clicked"] for row in train) == 3
    requests = pq.read_table(first_output / "requests_train.parquet").to_pylist()
    assert requests[0]["history_article_ids"] == []
    assert requests[1]["positive_count"] == 2
    articles = {
        row["article_id"]: row
        for row in pq.read_table(first_output / "articles.parquet").to_pylist()
    }
    assert articles[2]["abstract"] == ""
    assert articles[1]["source_domain"] == "msn.com"
    assert articles[4]["first_seen_train_ts"] is None
    assert articles[4]["first_seen_dev_ts"] is not None
    assert articles[4]["first_seen_any_split_ts"] == articles[4]["first_seen_dev_ts"]
    id_maps = json.loads((first_output / "id_maps.json").read_text())
    assert id_maps["article_ids"] == {"N1": 1, "N2": 2, "N3": 3, "N4": 4}
    assert list(id_maps["topic_ids"]) == sorted(id_maps["topic_ids"])


def test_normalizer_rejects_orphan_candidate(tmp_path: Path):
    raw_root = tmp_path / "raw"
    news = ["N1\tNews\tLocal\tOne\tAbstract\thttps://example.com\t[]\t[]"]
    _write_split(
        raw_root,
        "train",
        news_rows=news,
        behavior_rows=["1\tU1\t11/13/2019 8:36:57 AM\t\tN404-1"],
    )
    _write_split(
        raw_root,
        "dev",
        news_rows=news,
        behavior_rows=["1\tU1\t11/14/2019 8:36:57 AM\t\tN1-1"],
    )

    with pytest.raises(MindNormalizationError, match="lacks metadata"):
        normalize_dataset(raw_root, tmp_path / "output")
