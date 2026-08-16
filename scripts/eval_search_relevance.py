from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.evaluate import graded_ndcg_at_k, mrr_at_k, recall_at_k  # noqa: E402
from backend.app.search_retrieval import (  # noqa: E402
    BM25Index,
    DenseSearchIndex,
    HybridSearchConfig,
    HybridSearchIndex,
    LexicalBaselineIndex,
    RetrievalHit,
    SearchDocument,
)


@dataclass(frozen=True)
class EvaluationQuery:
    query_id: str
    text: str
    slice: str
    split: str
    intended_meaning: str
    expected_relevant: bool
    anchor_article_ids: tuple[int, ...]


@dataclass(frozen=True)
class QueryRun:
    query: EvaluationQuery
    accepted: bool
    article_ids: tuple[int, ...]
    candidate_article_ids: tuple[int, ...]
    query_key: str | None
    resolution_source: str
    top_bm25_score: float = 0.0
    top_dense_score: float = 0.0
    fusion_margin: float = 0.0


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_queries(path: Path) -> list[EvaluationQuery]:
    rows = _read_jsonl(path)
    queries = [
        EvaluationQuery(
            query_id=str(row["query_id"]),
            text=str(row["text"]),
            slice=str(row["slice"]),
            split=str(row["split"]),
            intended_meaning=str(row["intended_meaning"]),
            expected_relevant=bool(row["expected_relevant"]),
            anchor_article_ids=tuple(int(value) for value in row.get("anchor_article_ids", [])),
        )
        for row in rows
    ]
    query_ids = [query.query_id for query in queries]
    if len(query_ids) != len(set(query_ids)):
        raise ValueError("query_id values must be unique")
    if any(query.split not in {"calibration", "test"} for query in queries):
        raise ValueError("query split must be calibration or test")
    return queries


def load_qrels(path: Path) -> dict[str, dict[int, float]]:
    qrels: dict[str, dict[int, float]] = {}
    for row in _read_jsonl(path):
        relevance = float(row["relevance"])
        if relevance not in {0.0, 1.0, 2.0}:
            raise ValueError("relevance must be 0, 1, or 2")
        query_id = str(row["query_id"])
        article_id = int(row["article_id"])
        query_qrels = qrels.setdefault(query_id, {})
        if article_id in query_qrels:
            raise ValueError(f"duplicate qrel for {query_id}/{article_id}")
        query_qrels[article_id] = relevance
    return qrels


def load_documents(normalized_dir: Path) -> list[SearchDocument]:
    rows = pq.read_table(normalized_dir / "articles.parquet").to_pylist()
    return [
        SearchDocument(
            news_id=str(row.get("news_id") or f"N{int(row['article_id'])}"),
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


def _run_lexical(
    index: LexicalBaselineIndex,
    query: EvaluationQuery,
    *,
    limit: int,
) -> QueryRun:
    result = index.search(query.text, limit=limit)
    if result is None:
        return QueryRun(
            query=query,
            accepted=False,
            article_ids=(),
            candidate_article_ids=(),
            query_key=None,
            resolution_source="unresolved",
        )
    return QueryRun(
        query=query,
        accepted=True,
        article_ids=tuple(int(hit.news_id[1:]) for hit in result.hits),
        candidate_article_ids=tuple(int(hit.news_id[1:]) for hit in result.hits),
        query_key=result.query_key,
        resolution_source=result.source,
    )


def _run_bm25(
    index: BM25Index,
    aliases: LexicalBaselineIndex,
    query: EvaluationQuery,
    *,
    limit: int,
    min_score: float,
) -> QueryRun:
    exact = aliases.search_exact_alias(query.text, limit=limit)
    if exact is not None:
        return QueryRun(
            query=query,
            accepted=True,
            article_ids=tuple(int(hit.news_id[1:]) for hit in exact.hits),
            candidate_article_ids=tuple(int(hit.news_id[1:]) for hit in exact.hits),
            query_key=exact.query_key,
            resolution_source="exact_alias",
        )
    hits: list[RetrievalHit] = index.search(query.text, limit=limit)
    top_score = hits[0].score if hits else 0.0
    accepted = bool(hits) and top_score >= min_score
    return QueryRun(
        query=query,
        accepted=accepted,
        article_ids=tuple(int(hit.news_id[1:]) for hit in hits) if accepted else (),
        candidate_article_ids=tuple(int(hit.news_id[1:]) for hit in hits),
        query_key=None,
        resolution_source="bm25" if accepted else "unresolved",
        top_bm25_score=top_score,
    )


def _run_dense(
    index: DenseSearchIndex,
    aliases: LexicalBaselineIndex,
    query: EvaluationQuery,
    *,
    limit: int,
    min_score: float,
) -> QueryRun:
    exact = aliases.search_exact_alias(query.text, limit=limit)
    if exact is not None:
        return QueryRun(
            query=query,
            accepted=True,
            article_ids=tuple(int(hit.news_id[1:]) for hit in exact.hits),
            candidate_article_ids=tuple(int(hit.news_id[1:]) for hit in exact.hits),
            query_key=exact.query_key,
            resolution_source="exact_alias",
        )
    hits = index.search(query.text, limit=limit)
    top_score = hits[0].score if hits else 0.0
    accepted = bool(hits) and top_score >= min_score
    return QueryRun(
        query=query,
        accepted=accepted,
        article_ids=tuple(int(hit.news_id[1:]) for hit in hits) if accepted else (),
        candidate_article_ids=tuple(int(hit.news_id[1:]) for hit in hits),
        query_key=None,
        resolution_source="dense" if accepted else "unresolved",
        top_dense_score=top_score,
    )


def _run_hybrid(
    index: HybridSearchIndex,
    aliases: LexicalBaselineIndex,
    query: EvaluationQuery,
    *,
    limit: int,
) -> QueryRun:
    exact = aliases.search_exact_alias(query.text, limit=limit)
    if exact is not None:
        return QueryRun(
            query=query,
            accepted=True,
            article_ids=tuple(int(hit.news_id[1:]) for hit in exact.hits),
            candidate_article_ids=tuple(int(hit.news_id[1:]) for hit in exact.hits),
            query_key=exact.query_key,
            resolution_source="exact_alias",
        )
    result = index.search(query.text, limit=limit)
    return QueryRun(
        query=query,
        accepted=result.accepted,
        article_ids=(tuple(int(hit.news_id[1:]) for hit in result.hits) if result.accepted else ()),
        candidate_article_ids=tuple(int(hit.news_id[1:]) for hit in result.hits),
        query_key=None,
        resolution_source="hybrid" if result.accepted else "unresolved",
        top_bm25_score=result.top_bm25_score,
        top_dense_score=result.top_dense_score,
        fusion_margin=result.fusion_margin,
    )


def evaluate_runs(
    runs: list[QueryRun],
    qrels: dict[str, dict[int, float]],
    *,
    k_values: tuple[int, ...] = (5, 10),
) -> dict[str, Any]:
    relevant_rows: list[dict[str, Any]] = []
    reject_rows: list[dict[str, Any]] = []
    for run in runs:
        relevance = qrels.get(run.query.query_id, {})
        relevant_ids = {article_id for article_id, grade in relevance.items() if grade > 0}
        row: dict[str, Any] = {
            "query_id": run.query.query_id,
            "split": run.query.split,
            "slice": run.query.slice,
            "accepted": run.accepted,
            "query_key": run.query_key,
            "resolution_source": run.resolution_source,
            "article_ids": list(run.article_ids),
            "candidate_article_ids": list(run.candidate_article_ids),
            "top_bm25_score": round(run.top_bm25_score, 6),
            "top_dense_score": round(run.top_dense_score, 6),
            "fusion_margin": round(run.fusion_margin, 9),
        }
        if run.query.expected_relevant:
            row["false_reject"] = not run.accepted
            for k in k_values:
                row[f"recall@{k}"] = recall_at_k(run.article_ids, relevant_ids, k)
            row["ndcg@10"] = graded_ndcg_at_k(run.article_ids, relevance, 10)
            row["mrr@10"] = mrr_at_k(run.article_ids, relevant_ids, 10)
            relevant_rows.append(row)
        else:
            row["correct_reject"] = not run.accepted
            reject_rows.append(row)

    query_rows = [*relevant_rows, *reject_rows]
    return {
        "aggregate": _aggregate_query_rows(query_rows),
        "by_split": {
            split: _aggregate_query_rows([row for row in query_rows if row["split"] == split])
            for split in ("calibration", "test")
        },
        "by_slice": {
            slice_name: _aggregate_query_rows(
                [row for row in query_rows if row["slice"] == slice_name]
            )
            for slice_name in sorted({str(row["slice"]) for row in query_rows})
        },
        "queries": query_rows,
    }


def _aggregate_query_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    relevant_rows = [row for row in rows if "false_reject" in row]
    reject_rows = [row for row in rows if "correct_reject" in row]
    aggregate: dict[str, Any] = {
        "relevant_query_count": len(relevant_rows),
        "irrelevant_query_count": len(reject_rows),
        "false_reject_rate": round(
            mean(float(row["false_reject"]) for row in relevant_rows),
            6,
        )
        if relevant_rows
        else 0.0,
        "reject_accuracy": round(
            mean(float(row["correct_reject"]) for row in reject_rows),
            6,
        )
        if reject_rows
        else 0.0,
    }
    for metric in ("recall@5", "recall@10", "ndcg@10", "mrr@10"):
        aggregate[metric] = (
            round(mean(float(row[metric]) for row in relevant_rows), 6) if relevant_rows else 0.0
        )
    return aggregate


def _paired_bootstrap_delta(
    baseline_rows: list[dict[str, Any]],
    challenger_rows: list[dict[str, Any]],
    *,
    metric: str,
    samples: int = 2000,
    seed: int = 20260727,
) -> dict[str, float | int]:
    baseline_by_query = {
        str(row["query_id"]): float(row[metric])
        for row in baseline_rows
        if row["split"] == "test" and "false_reject" in row
    }
    challenger_by_query = {
        str(row["query_id"]): float(row[metric])
        for row in challenger_rows
        if row["split"] == "test" and "false_reject" in row
    }
    query_ids = sorted(baseline_by_query.keys() & challenger_by_query.keys())
    if not query_ids:
        return {
            "query_count": 0,
            "observed_delta": 0.0,
            "ci95_lower": 0.0,
            "ci95_upper": 0.0,
        }
    deltas = [challenger_by_query[query_id] - baseline_by_query[query_id] for query_id in query_ids]
    rng = random.Random(seed)
    bootstrap = sorted(mean(rng.choice(deltas) for _ in deltas) for _sample_index in range(samples))
    return {
        "query_count": len(query_ids),
        "observed_delta": round(mean(deltas), 6),
        "ci95_lower": round(bootstrap[round(0.025 * (samples - 1))], 6),
        "ci95_upper": round(bootstrap[round(0.975 * (samples - 1))], 6),
    }


def _build_comparisons(results: dict[str, Any]) -> dict[str, Any]:
    if "lexical_v1" not in results or "hybrid_v1" not in results:
        return {}
    return {
        "hybrid_v1_vs_lexical_v1": {
            metric: _paired_bootstrap_delta(
                results["lexical_v1"]["queries"],
                results["hybrid_v1"]["queries"],
                metric=metric,
            )
            for metric in ("recall@10", "ndcg@10", "mrr@10")
        }
    }


def _hybrid_default_gate(
    results: dict[str, Any],
    comparisons: dict[str, Any],
) -> dict[str, Any]:
    comparison = comparisons.get("hybrid_v1_vs_lexical_v1")
    if not isinstance(comparison, dict):
        return {
            "primary_metric": "ndcg@10",
            "checks": {},
            "metrics_passed": False,
            "recommended_default": "lexical_v1",
        }
    lexical_test = results["lexical_v1"]["by_split"]["test"]
    hybrid_test = results["hybrid_v1"]["by_split"]["test"]
    primary = comparison["ndcg@10"]
    checks = {
        "ndcg_ci_lower_positive": float(primary["ci95_lower"]) > 0,
        "recall10_not_lower": (float(hybrid_test["recall@10"]) >= float(lexical_test["recall@10"])),
        "reject_accuracy_is_one": float(hybrid_test["reject_accuracy"]) == 1.0,
        "false_reject_rate_not_higher": (
            float(hybrid_test["false_reject_rate"]) <= float(lexical_test["false_reject_rate"])
        ),
    }
    passed = all(checks.values())
    return {
        "primary_metric": "ndcg@10",
        "checks": checks,
        "metrics_passed": passed,
        "recommended_default": "hybrid_v1" if passed else "lexical_v1",
    }


def evaluate_search_relevance(
    *,
    normalized_dir: Path,
    queries_path: Path,
    qrels_path: Path,
    arms: tuple[str, ...],
    artifact_dir: Path | None = None,
    config_path: Path | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    documents = load_documents(normalized_dir)
    queries = load_queries(queries_path)
    qrels = load_qrels(qrels_path)
    unknown_qrels = set(qrels) - {query.query_id for query in queries}
    if unknown_qrels:
        raise ValueError(f"qrels reference unknown queries: {sorted(unknown_qrels)}")

    manifest = json.loads(
        (normalized_dir / "normalization_manifest.json").read_text(encoding="utf-8")
    )
    aliases = LexicalBaselineIndex(documents)
    config = HybridSearchConfig()
    dense_index: DenseSearchIndex | None = None
    if {"dense_v1", "hybrid_v1"} & set(arms):
        if artifact_dir is None:
            raise ValueError("artifact_dir is required for dense or hybrid evaluation")
        dense_index = DenseSearchIndex.load(
            artifact_dir,
            expected_source_fingerprint=str(manifest["normalized_fingerprint"]),
        )
        config_value = dense_index.metadata().get("hybrid_config")
        if not isinstance(config_value, dict):
            raise ValueError("search artifact hybrid_config is missing")
        config = HybridSearchConfig.from_dict(config_value)
    if config_path is not None:
        config_value = json.loads(config_path.read_text(encoding="utf-8"))
        config = HybridSearchConfig.from_dict(config_value)

    results: dict[str, Any] = {}
    for arm in arms:
        if arm == "lexical_v1":
            runs = [_run_lexical(aliases, query, limit=limit) for query in queries]
        elif arm == "bm25_v1":
            index = BM25Index(documents)
            runs = [
                _run_bm25(
                    index,
                    aliases,
                    query,
                    limit=limit,
                    min_score=config.min_bm25_score,
                )
                for query in queries
            ]
        elif arm == "dense_v1":
            if dense_index is None:
                raise ValueError("dense index was not loaded")
            runs = [
                _run_dense(
                    dense_index,
                    aliases,
                    query,
                    limit=limit,
                    min_score=config.min_dense_score,
                )
                for query in queries
            ]
        elif arm == "hybrid_v1":
            if dense_index is None:
                raise ValueError("dense index was not loaded")
            hybrid_index = HybridSearchIndex(dense_index, config=config)
            runs = [_run_hybrid(hybrid_index, aliases, query, limit=limit) for query in queries]
        else:
            raise ValueError(f"unsupported arm: {arm}")
        results[arm] = evaluate_runs(runs, qrels)

    comparisons = _build_comparisons(results)
    implementation_paths = (
        ROOT / "backend" / "app" / "search_retrieval.py",
        ROOT / "backend" / "app" / "repositories" / "query_resolver.py",
        ROOT / "scripts" / "eval_search_relevance.py",
    )
    label_manifest_path = qrels_path.parent / "label_manifest.json"
    return {
        "metric_type": "mind_search_relevance",
        "dataset": manifest["dataset"],
        "source_fingerprint": manifest["normalized_fingerprint"],
        "article_count": len(documents),
        "query_count": len(queries),
        "queries_sha256": _file_sha256(queries_path),
        "qrels_sha256": _file_sha256(qrels_path),
        "label_evidence": (
            json.loads(label_manifest_path.read_text(encoding="utf-8"))
            if label_manifest_path.is_file()
            else None
        ),
        "implementation_file_sha256": {
            str(path.relative_to(ROOT)): _file_sha256(path) for path in implementation_paths
        },
        "hybrid_config": config.to_dict(),
        "arms": results,
        "comparisons": comparisons,
        "default_gate": _hybrid_default_gate(results, comparisons),
        "evidence_boundary": (
            "Offline relevance evaluation over AI-assisted labels with human spot-checking. "
            "MIND has no observed search logs. This report does not estimate CTR or causal "
            "user benefit."
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate MIND search relevance.")
    parser.add_argument(
        "--normalized-dir",
        type=Path,
        default=ROOT / "build" / "mind_normalized",
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=ROOT / "evaluation" / "search_relevance" / "queries.jsonl",
    )
    parser.add_argument(
        "--qrels",
        type=Path,
        default=ROOT / "evaluation" / "search_relevance" / "qrels.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "metrics" / "mind_search_relevance.json",
    )
    parser.add_argument(
        "--arms",
        default="lexical_v1,bm25_v1,dense_v1,hybrid_v1",
        help="Comma-separated retrieval arms.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ROOT / "build" / "mind_search" / "full",
    )
    parser.add_argument("--config", type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    arms = tuple(value.strip() for value in args.arms.split(",") if value.strip())
    report = evaluate_search_relevance(
        normalized_dir=args.normalized_dir,
        queries_path=args.queries,
        qrels_path=args.qrels,
        arms=arms,
        artifact_dir=args.artifact_dir,
        config_path=args.config,
    )
    report["source_revision"] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {args.output}: articles={report['article_count']} "
        f"queries={report['query_count']} arms={','.join(arms)}"
    )


if __name__ == "__main__":
    main()
