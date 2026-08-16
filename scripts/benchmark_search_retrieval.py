from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.search_retrieval import HybridSearchIndex  # noqa: E402
from scripts.eval_search_relevance import load_queries  # noqa: E402


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark in-process hybrid retrieval.")
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
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "metrics" / "mind_search_latency.json",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.iterations <= 0:
        raise ValueError("iterations must be positive")
    index = HybridSearchIndex.load(args.artifact_dir)
    query_texts = [
        query.text
        for query in load_queries(args.queries)
        if query.expected_relevant and query.slice != "lexical"
    ]
    for query_text in query_texts:
        index.search(query_text, limit=10)

    durations_ms = []
    for iteration in range(args.iterations):
        query_text = query_texts[iteration % len(query_texts)]
        started = time.perf_counter()
        index.search(query_text, limit=10)
        durations_ms.append((time.perf_counter() - started) * 1000.0)

    metadata = index.metadata()
    report = {
        "metric_type": "local_in_process_search_retrieval_latency",
        "iterations": args.iterations,
        "query_count": len(query_texts),
        "corpus_document_count": metadata["document_count"],
        "model_id": metadata["model_id"],
        "model_revision": metadata["model_revision"],
        "mean_ms": round(mean(durations_ms), 3),
        "p50_ms": round(_percentile(durations_ms, 0.5), 3),
        "p95_ms": round(_percentile(durations_ms, 0.95), 3),
        "evidence_boundary": (
            "Warm in-process retrieval over the 174-document demo index on one local "
            "machine. This excludes HTTP, PostgreSQL, event writes, concurrency, and production "
            "capacity."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output}: p50={report['p50_ms']}ms p95={report['p95_ms']}ms")


if __name__ == "__main__":
    main()
