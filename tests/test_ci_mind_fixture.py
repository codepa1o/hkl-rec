from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

from scripts.build_ci_mind_fixture import build_fixture


def test_ci_fixture_is_deterministic_and_covers_twelve_news(tmp_path: Path) -> None:
    output = build_fixture(tmp_path / "raw", tmp_path / "normalized")
    first_manifest = json.loads(
        (output / "normalization_manifest.json").read_text(encoding="utf-8")
    )
    first_ids = pq.read_table(output / "articles.parquet", columns=["news_id"])[
        "news_id"
    ].to_pylist()

    build_fixture(tmp_path / "raw", output)
    second_manifest = json.loads(
        (output / "normalization_manifest.json").read_text(encoding="utf-8")
    )

    assert first_ids == [f"N{index}" for index in range(1, 13)]
    assert first_manifest["normalized_fingerprint"] == second_manifest["normalized_fingerprint"]
    assert first_manifest["split_summary"]["train"]["candidates"] == 12
    assert first_manifest["split_summary"]["dev"]["candidates"] == 12
