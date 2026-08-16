from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.search_retrieval import (  # noqa: E402
    HybridSearchConfig,
    SearchDocument,
    configure_transformer_backend,
    document_embedding_text,
    file_sha256,
    write_search_documents,
)


def _load_full_documents(input_dir: Path) -> tuple[list[SearchDocument], str]:
    articles_path = input_dir / "articles.parquet"
    manifest_path = input_dir / "normalization_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_hashes = manifest.get("output_hashes")
    if not isinstance(output_hashes, dict):
        raise RuntimeError(f"normalization manifest lacks output_hashes: {manifest_path}")
    expected_articles_hash = output_hashes.get("articles.parquet")
    actual_articles_hash = file_sha256(articles_path)
    if expected_articles_hash != actual_articles_hash:
        raise RuntimeError(
            "normalized articles checksum mismatch: "
            f"expected {expected_articles_hash}, got {actual_articles_hash}"
        )
    computed_fingerprint = hashlib.sha256(
        json.dumps(output_hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if manifest.get("normalized_fingerprint") != computed_fingerprint:
        raise RuntimeError("normalization manifest fingerprint mismatch")
    rows = pq.read_table(
        articles_path,
        columns=[
            "news_id",
            "headline",
            "abstract",
            "category",
            "subcategory",
            "category_topic_id",
            "subcategory_topic_id",
        ],
    ).to_pylist()
    documents = [
        SearchDocument(
            news_id=str(row["news_id"]),
            headline=str(row.get("headline") or ""),
            abstract=str(row.get("abstract") or ""),
            topic_ids=(
                int(row["category_topic_id"]),
                int(row["subcategory_topic_id"]),
            ),
            category=str(row.get("category") or ""),
            subcategory=str(row.get("subcategory") or ""),
        )
        for row in rows
    ]
    return documents, str(manifest["normalized_fingerprint"])


def build_search_index(
    *,
    documents: list[SearchDocument],
    source_fingerprint: str,
    output_dir: Path,
    model_id: str,
    model_revision: str | None,
    config: HybridSearchConfig,
    batch_size: int,
) -> dict[str, Any]:
    configure_transformer_backend()
    import faiss
    from sentence_transformers import SentenceTransformer

    resolved_revision = model_revision
    if resolved_revision is None:
        from huggingface_hub import HfApi

        resolved_revision = HfApi().model_info(model_id).sha
    if not resolved_revision:
        raise RuntimeError(f"could not resolve model revision for {model_id}")
    encoder = SentenceTransformer(model_id, revision=resolved_revision)
    embeddings = np.asarray(
        encoder.encode(
            [document_embedding_text(document) for document in documents],
            batch_size=batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ),
        dtype=np.float32,
    )
    if embeddings.ndim != 2 or embeddings.shape[0] != len(documents):
        raise RuntimeError("encoder returned an unexpected embedding matrix")

    output_dir.mkdir(parents=True, exist_ok=True)
    documents_path = output_dir / "documents.jsonl"
    id_map_path = output_dir / "news_id_map.json"
    index_path = output_dir / "dense.faiss"
    metadata_path = output_dir / "metadata.json"

    write_search_documents(documents_path, documents)
    id_map_path.write_text(
        json.dumps(
            {"index_to_news_id": [document.news_id for document in documents]},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    index = faiss.IndexFlatIP(int(embeddings.shape[1]))
    index.add(embeddings)
    faiss.write_index(index, str(index_path))

    metadata = {
        "schema_version": 2,
        "text_schema_version": 1,
        "source_fingerprint": source_fingerprint,
        "document_count": len(documents),
        "model_id": model_id,
        "model_revision": resolved_revision,
        "embedding_dimension": int(embeddings.shape[1]),
        "similarity": "cosine_via_normalized_inner_product",
        "faiss_index_type": "IndexFlatIP",
        "hybrid_config": config.to_dict(),
        "built_at": datetime.now(UTC).isoformat(),
        "file_sha256": {
            path.name: file_sha256(path) for path in (documents_path, id_map_path, index_path)
        },
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BM25+dense search artifacts.")
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--model-id",
        default="sentence-transformers/all-MiniLM-L6-v2",
    )
    parser.add_argument(
        "--model-revision",
        default="1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--online-config", type=Path)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--bm25-weight", type=float, default=1.0)
    parser.add_argument("--dense-weight", type=float, default=1.0)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--min-dense-score", type=float, default=0.4)
    parser.add_argument("--min-dense-score-with-bm25", type=float, default=0.28)
    parser.add_argument("--min-bm25-score", type=float, default=20.0)
    parser.add_argument("--min-fusion-margin", type=float, default=0.002)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    input_dir = args.input_dir or ROOT / "build" / "mind_normalized"
    output_dir = args.output_dir or ROOT / "build" / "mind_search" / "full"
    documents, source_fingerprint = _load_full_documents(input_dir)

    config = (
        HybridSearchConfig.from_dict(json.loads(args.config.read_text(encoding="utf-8")))
        if args.config is not None
        else HybridSearchConfig(
            bm25_weight=args.bm25_weight,
            dense_weight=args.dense_weight,
            rrf_k=args.rrf_k,
            candidate_k=args.candidate_k,
            min_dense_score=args.min_dense_score,
            min_dense_score_with_bm25=args.min_dense_score_with_bm25,
            min_bm25_score=args.min_bm25_score,
            min_fusion_margin=args.min_fusion_margin,
        )
    )
    if args.online_config is not None:
        online_config = HybridSearchConfig.from_dict(
            json.loads(args.online_config.read_text(encoding="utf-8"))
        )
        config = HybridSearchConfig(
            bm25_weight=config.bm25_weight,
            dense_weight=config.dense_weight,
            rrf_k=config.rrf_k,
            candidate_k=config.candidate_k,
            min_dense_score=online_config.min_dense_score,
            min_dense_score_with_bm25=online_config.min_dense_score_with_bm25,
            min_bm25_score=online_config.min_bm25_score,
            min_fusion_margin=online_config.min_fusion_margin,
        )
    metadata = build_search_index(
        documents=documents,
        source_fingerprint=source_fingerprint,
        output_dir=output_dir,
        model_id=args.model_id,
        model_revision=args.model_revision,
        config=config,
        batch_size=args.batch_size,
    )
    print(
        f"wrote {output_dir}: documents={metadata['document_count']} "
        f"dimension={metadata['embedding_dimension']} "
        f"revision={metadata['model_revision']}"
    )


if __name__ == "__main__":
    main()
