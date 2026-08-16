from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import faiss
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.app.search_retrieval import (
    DenseSearchIndex,
    HybridSearchConfig,
    HybridSearchIndex,
    SearchArtifactError,
    SearchDocument,
    configure_transformer_backend,
    file_sha256,
    write_search_documents,
)
from scripts.build_search_index import _load_full_documents


def test_search_builder_verifies_normalized_articles_hash(tmp_path: Path) -> None:
    articles_path = tmp_path / "articles.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "news_id": "N1",
                    "headline": "One",
                    "abstract": "Abstract",
                    "category": "News",
                    "subcategory": "Local",
                    "category_topic_id": 1,
                    "subcategory_topic_id": 2,
                }
            ]
        ),
        articles_path,
    )
    output_hashes = {"articles.parquet": file_sha256(articles_path)}
    fingerprint = hashlib.sha256(
        json.dumps(output_hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (tmp_path / "normalization_manifest.json").write_text(
        json.dumps(
            {
                "output_hashes": output_hashes,
                "normalized_fingerprint": fingerprint,
            }
        ),
        encoding="utf-8",
    )

    documents, source_fingerprint = _load_full_documents(tmp_path)
    assert [document.news_id for document in documents] == ["N1"]
    assert source_fingerprint == fingerprint

    articles_path.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        _load_full_documents(tmp_path)


def test_search_index_builder_forces_pytorch_backend(monkeypatch):
    monkeypatch.setenv("USE_TF", "AUTO")
    monkeypatch.setenv("USE_TORCH", "AUTO")

    configure_transformer_backend()

    assert os.environ["USE_TF"] == "0"
    assert os.environ["USE_TORCH"] == "1"


class FakeEncoder:
    def encode(
        self,
        sentences: str | list[str],
        *,
        batch_size: int = 32,
        show_progress_bar: bool = False,
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = True,
    ) -> np.ndarray:
        del batch_size, show_progress_bar, convert_to_numpy, normalize_embeddings
        if isinstance(sentences, list):
            return np.array([[1.0, 0.0] for _ in sentences], dtype=np.float32)
        return np.array([1.0, 0.0], dtype=np.float32)


def _write_artifact(tmp_path: Path) -> Path:
    documents = [
        SearchDocument(
            news_id="N10",
            headline="Football tactics",
            abstract="Defensive formations.",
            category="sports",
            subcategory="football_nfl",
        ),
        SearchDocument(
            news_id="N20",
            headline="Celebrity awards",
            abstract="Red carpet fashion.",
            category="entertainment",
            subcategory="celebrity",
        ),
    ]
    write_search_documents(tmp_path / "documents.jsonl", documents)
    (tmp_path / "news_id_map.json").write_text(
        json.dumps({"index_to_news_id": ["N10", "N20"]}),
        encoding="utf-8",
    )
    index = faiss.IndexFlatIP(2)
    index.add(np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))
    faiss.write_index(index, str(tmp_path / "dense.faiss"))
    metadata = {
        "schema_version": 2,
        "source_fingerprint": "fixture",
        "document_count": 2,
        "model_id": "fixture/model",
        "model_revision": "fixture-revision",
        "similarity": "cosine_via_normalized_inner_product",
        "hybrid_config": HybridSearchConfig(
            min_dense_score=0.5,
            min_bm25_score=100.0,
        ).to_dict(),
        "file_sha256": {
            name: file_sha256(tmp_path / name)
            for name in ("documents.jsonl", "news_id_map.json", "dense.faiss")
        },
    }
    (tmp_path / "metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )
    return tmp_path


def test_dense_artifact_loads_and_searches_with_injected_encoder(tmp_path: Path):
    artifact_dir = _write_artifact(tmp_path)

    index = DenseSearchIndex.load(
        artifact_dir,
        expected_source_fingerprint="fixture",
        encoder_factory=lambda _model, _revision: FakeEncoder(),
    )

    hits = index.search("football strategy", limit=2)
    assert [hit.news_id for hit in hits] == ["N10", "N20"]
    assert hits[0].score == pytest.approx(1.0)


def test_hybrid_artifact_applies_confidence_guard(tmp_path: Path):
    artifact_dir = _write_artifact(tmp_path)
    index = HybridSearchIndex.load(
        artifact_dir,
        expected_source_fingerprint="fixture",
        encoder_factory=lambda _model, _revision: FakeEncoder(),
    )

    result = index.search("football tactics", limit=2)

    assert result.accepted is True
    assert result.hits[0].news_id == "N10"
    assert result.top_dense_score == pytest.approx(1.0)


def test_dense_artifact_rejects_hash_mismatch(tmp_path: Path):
    artifact_dir = _write_artifact(tmp_path)
    (artifact_dir / "documents.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(SearchArtifactError, match="hash mismatch"):
        DenseSearchIndex.load(
            artifact_dir,
            encoder_factory=lambda _model, _revision: FakeEncoder(),
        )
