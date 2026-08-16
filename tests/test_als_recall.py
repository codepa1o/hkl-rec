from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from backend.app.repositories.als_recall import ALSRecall


def test_faiss_recall_matches_numpy_inner_product(tmp_path: Path):
    import faiss

    user_embeddings = np.array([[1.0, 2.0]], dtype=np.float32)
    item_embeddings = np.array(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
            [0.0, 0.0],
        ],
        dtype=np.float32,
    )
    index = faiss.IndexFlatIP(2)
    index.add(item_embeddings)

    np.save(tmp_path / "als_user_embeddings.npy", user_embeddings)
    np.save(tmp_path / "als_item_embeddings.npy", item_embeddings)
    faiss.write_index(index, str(tmp_path / "faiss_index.bin"))
    (tmp_path / "als_user_id_map.json").write_text(
        json.dumps({"index_to_id": [7248], "id_to_index": {"7248": 0}}),
        encoding="utf-8",
    )
    (tmp_path / "als_item_id_map.json").write_text(
        json.dumps(
            {
                "index_to_id": [301, 302, 303, 304],
                "id_to_index": {"301": 0, "302": 1, "303": 2, "304": 3},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "als_meta.json").write_text(
        json.dumps({"schema_version": 1, "similarity": "inner_product", "factors": 2}),
        encoding="utf-8",
    )

    recall = ALSRecall(str(tmp_path))
    results = recall.get_candidates(7248, k=4)
    expected_order = list(np.argsort(-(item_embeddings @ user_embeddings[0])))

    assert [news_id for news_id, _ in results] == [
        f"N{[301, 302, 303, 304][index]}" for index in expected_order
    ]
    assert recall.get_candidates(999999, k=3) == []
    assert recall.item_cosine_similarity("N301", "N303") == pytest.approx(2**-0.5)
    assert recall.item_cosine_similarity("N301", "N302") == pytest.approx(0.0)
    assert recall.item_cosine_similarity("N301", "N304") is None
    assert recall.item_cosine_similarity("N301", "N999999") is None
    mismatched = ALSRecall(
        str(tmp_path),
        expected_normalized_fingerprint="active-catalog",
    )
    assert mismatched.get_candidates(7248, k=4) == []
    assert mismatched.metadata() == {}


def test_item_similarity_returns_none_without_artifacts(tmp_path: Path):
    assert ALSRecall(str(tmp_path)).item_cosine_similarity("N301", "N302") is None
