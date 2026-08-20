from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.live_news.allowlist import load_allowlist  # noqa: E402
from backend.app.live_news.collector import LiveNewsCollector, fetch_url  # noqa: E402
from backend.app.live_news.dao import PostgresLiveNewsStore  # noqa: E402
from backend.app.observability import start_worker_metrics_server  # noqa: E402
from backend.app.repositories.connection import connect, parse_database_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Continuously ingest GDELT GAL metadata.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-interval-seconds", type=int)
    parser.add_argument("--source-config", type=Path)
    return parser.parse_args()


def run_loop(
    collector: Any,
    *,
    once: bool,
    interval: float,
    stop_event: Event,
    sleep: Callable[[float], None] = time.sleep,
    emit: Callable[[dict[str, object]], None] | None = None,
) -> int:
    output = emit or (lambda payload: print(json.dumps(payload, sort_keys=True), flush=True))
    while not stop_event.is_set():
        try:
            results = collector.run_once()
        except Exception as exc:
            output(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "detail": str(exc)[:500],
                }
            )
            if once:
                raise
        else:
            output(
                {
                    "status": "ok",
                    "batches": len(results),
                    "accepted": sum(item.accepted_count for item in results),
                    "rejected": sum(item.rejected_count for item in results),
                }
            )
            if once:
                return 0
        if stop_event.is_set():
            return 0
        sleep(interval)
    return 0


def main() -> int:
    args = parse_args()
    settings = get_settings()
    if not settings.database_configured:
        raise SystemExit("NEWSREC_DATABASE_URL is required")
    if not args.once and not settings.live_news_collector_enabled:
        raise SystemExit("NEWSREC_LIVE_NEWS_COLLECTOR_ENABLED=1 is required for long-running mode")
    interval = args.poll_interval_seconds or settings.live_news_poll_interval_seconds
    if interval <= 0:
        raise SystemExit("poll interval must be positive")
    source_config = args.source_config or Path(settings.live_news_source_config)
    allowlist = load_allowlist(source_config)
    connection_config = parse_database_url(settings.database_url)
    store = PostgresLiveNewsStore(
        lambda: connect(
            connection_config,
            connect_timeout=settings.postgres_connect_timeout_seconds,
        ),
        allowlist,
    )
    collector = LiveNewsCollector(
        fetch=fetch_url,
        store=store,
        allowlist=allowlist,
        replay_minutes=settings.live_news_replay_minutes,
        max_age_hours=settings.live_news_max_age_hours,
    )
    stop_event = Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    if not args.once:
        start_worker_metrics_server(settings.live_news_collector_metrics_port)
    return run_loop(
        collector,
        once=args.once,
        interval=interval,
        stop_event=stop_event,
    )


if __name__ == "__main__":
    raise SystemExit(main())
