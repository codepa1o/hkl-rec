from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def _request_json(
    base_url: str,
    path: str,
    *,
    params: dict[str, object] | None = None,
    body: dict[str, object] | None = None,
) -> dict:
    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{base_url}{path}{query}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _measure(operation, iterations: int) -> dict[str, float | int]:
    durations = []
    for index in range(iterations):
        started = time.perf_counter()
        operation(index)
        durations.append((time.perf_counter() - started) * 1000)
    return {
        "iterations": iterations,
        "p50_ms": round(_percentile(durations, 0.50), 3),
        "p95_ms": round(_percentile(durations, 0.95), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark local MIND feed/search APIs.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "metrics" / "mind_system.json",
    )
    args = parser.parse_args()
    personas = _request_json(args.base_url, "/personas", params={"limit": 1})
    user_id = int(personas["items"][0]["user_id"])
    suggestions = _request_json(
        args.base_url,
        "/search/suggestions",
        params={"limit": 1},
    )
    query_key = str(suggestions["items"][0]["query_key"])
    run_id = uuid.uuid4().hex[:8]

    _request_json(
        args.base_url,
        "/feed",
        params={"user_id": user_id, "page_size": 10, "include_sponsored": "false"},
    )
    feed = _measure(
        lambda index: _request_json(
            args.base_url,
            "/feed",
            params={
                "user_id": user_id,
                "page_size": 10,
                "include_sponsored": "false",
                "request_id": f"bench-feed-{run_id}-{index}",
            },
        ),
        args.iterations,
    )
    search = _measure(
        lambda index: _request_json(
            args.base_url,
            "/search",
            body={
                "event_id": f"bench-search-{run_id}-{index}",
                "user_id": user_id,
                "query_key": query_key,
                "page_size": 10,
            },
        ),
        args.iterations,
    )
    report = {
        "environment": "local workstation, FastAPI + PostgreSQL, loopback HTTP",
        "user_id": user_id,
        "feed": feed,
        "search": search,
        "limitations": (
            "Local demo latency only; not a production capacity or tail-latency claim."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
