from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.search_retrieval import (  # noqa: E402
    BM25Index,
    DenseSearchIndex,
    HybridSearchConfig,
    LexicalBaselineIndex,
    RetrievalHit,
    build_hybrid_search_result,
)
from scripts.eval_search_relevance import (  # noqa: E402
    EvaluationQuery,
    QueryRun,
    evaluate_runs,
    load_documents,
    load_qrels,
    load_queries,
)


@dataclass(frozen=True)
class RawQueryRun:
    query: EvaluationQuery
    exact_run: QueryRun | None
    bm25_hits: tuple[RetrievalHit, ...]
    dense_hits: tuple[RetrievalHit, ...]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate hybrid search on calibration queries.")
    parser.add_argument(
        "--normalized-dir",
        type=Path,
        default=ROOT / "build" / "mind_normalized",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ROOT / "build" / "mind_search" / "full",
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
        "--config-output",
        type=Path,
        default=ROOT / "evaluation" / "search_relevance" / "selected_config.json",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=ROOT / "evaluation" / "search_relevance" / "calibration_report.json",
    )
    return parser.parse_args()


def _precompute_runs(
    *,
    queries: list[EvaluationQuery],
    aliases: LexicalBaselineIndex,
    bm25: BM25Index,
    dense: DenseSearchIndex,
) -> list[RawQueryRun]:
    runs = []
    for query in queries:
        exact = aliases.search_exact_alias(query.text, limit=10)
        if exact is not None:
            article_ids = tuple(int(hit.news_id[1:]) for hit in exact.hits)
            exact_run = QueryRun(
                query=query,
                accepted=True,
                article_ids=article_ids,
                candidate_article_ids=article_ids,
                query_key=exact.query_key,
                resolution_source="exact_alias",
            )
            runs.append(
                RawQueryRun(
                    query=query,
                    exact_run=exact_run,
                    bm25_hits=(),
                    dense_hits=(),
                )
            )
            continue
        runs.append(
            RawQueryRun(
                query=query,
                exact_run=None,
                bm25_hits=tuple(bm25.search(query.text, limit=50)),
                dense_hits=tuple(dense.search(query.text, limit=50)),
            )
        )
    return runs


def _evaluate_config(
    raw_runs: list[RawQueryRun],
    qrels: dict[str, dict[int, float]],
    config: HybridSearchConfig,
) -> dict[str, Any]:
    runs = []
    for raw in raw_runs:
        if raw.exact_run is not None:
            runs.append(raw.exact_run)
            continue
        result = build_hybrid_search_result(
            list(raw.bm25_hits),
            list(raw.dense_hits),
            config=config,
            limit=10,
        )
        candidate_ids = tuple(int(hit.news_id[1:]) for hit in result.hits)
        runs.append(
            QueryRun(
                query=raw.query,
                accepted=result.accepted,
                article_ids=candidate_ids if result.accepted else (),
                candidate_article_ids=candidate_ids,
                query_key=None,
                resolution_source="hybrid" if result.accepted else "unresolved",
                top_bm25_score=result.top_bm25_score,
                top_dense_score=result.top_dense_score,
                fusion_margin=result.fusion_margin,
            )
        )
    return evaluate_runs(runs, qrels)["aggregate"]


def main() -> None:
    args = _parse_args()
    all_queries = load_queries(args.queries)
    queries = [query for query in all_queries if query.split == "calibration"]
    qrels = load_qrels(args.qrels)
    documents = load_documents(args.normalized_dir)
    manifest = json.loads(
        (args.normalized_dir / "normalization_manifest.json").read_text(encoding="utf-8")
    )
    aliases = LexicalBaselineIndex(documents)
    bm25 = BM25Index(documents)
    dense = DenseSearchIndex.load(
        args.artifact_dir,
        expected_source_fingerprint=str(manifest["normalized_fingerprint"]),
    )
    raw_runs = _precompute_runs(
        queries=queries,
        aliases=aliases,
        bm25=bm25,
        dense=dense,
    )

    configs = (
        HybridSearchConfig(
            bm25_weight=1.0,
            dense_weight=dense_weight,
            rrf_k=rrf_k,
            candidate_k=50,
            min_dense_score=min_dense,
            min_dense_score_with_bm25=min_dense_with_bm25,
            min_bm25_score=min_bm25,
            min_fusion_margin=min_margin,
        )
        for (
            dense_weight,
            rrf_k,
            min_dense,
            min_dense_with_bm25,
            min_bm25,
            min_margin,
        ) in itertools.product(
            (0.5, 1.0, 1.5, 2.0, 3.0, 4.0),
            (10, 30, 60),
            (0.36, 0.38, 0.4, 0.42),
            (0.24, 0.26, 0.28, 0.3),
            (15.0, 20.0, 25.0),
            (0.0, 0.001, 0.002, 0.004),
        )
    )

    evaluated = []
    for config in configs:
        metrics = _evaluate_config(raw_runs, qrels, config)
        evaluated.append({"config": config.to_dict(), "metrics": metrics})
    eligible = [
        row
        for row in evaluated
        if float(row["metrics"]["reject_accuracy"]) == 1.0
        and float(row["metrics"]["false_reject_rate"]) <= 0.05
    ]
    if not eligible:
        raise RuntimeError("no hybrid configuration satisfied the calibration safety gate")
    ranked = sorted(
        eligible,
        key=lambda row: (
            -float(row["metrics"]["ndcg@10"]),
            -float(row["metrics"]["recall@10"]),
            -float(row["metrics"]["mrr@10"]),
            -float(row["config"]["min_dense_score"]),
            -float(row["config"]["min_dense_score_with_bm25"]),
            -float(row["config"]["min_bm25_score"]),
            -float(row["config"]["min_fusion_margin"]),
            float(row["config"]["dense_weight"]),
            int(row["config"]["rrf_k"]),
        ),
    )
    selected = ranked[0]
    args.config_output.write_text(
        json.dumps(selected["config"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = {
        "selection_scope": "calibration_only",
        "calibration_query_ids": [query.query_id for query in queries],
        "config_count": len(evaluated),
        "eligible_config_count": len(eligible),
        "selection_metric": "ndcg@10",
        "safety_gate": {
            "reject_accuracy": 1.0,
            "max_false_reject_rate": 0.05,
        },
        "selected": selected,
        "top_configs": ranked[:10],
        "queries_sha256": hashlib.sha256(args.queries.read_bytes()).hexdigest(),
        "qrels_sha256": hashlib.sha256(args.qrels.read_bytes()).hexdigest(),
        "source_fingerprint": manifest["normalized_fingerprint"],
    }
    args.report_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {args.config_output}: configs={len(evaluated)} "
        f"eligible={len(eligible)} ndcg@10={selected['metrics']['ndcg@10']}"
    )


if __name__ == "__main__":
    main()
