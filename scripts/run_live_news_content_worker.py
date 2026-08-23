from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings, get_settings  # noqa: E402
from backend.app.live_news.allowlist import load_allowlist  # noqa: E402
from backend.app.live_news.content_dao import PostgresLiveContentStore  # noqa: E402
from backend.app.live_news.content_fetch import SafeFetcher  # noqa: E402
from backend.app.live_news.content_providers import (  # noqa: E402
    GuardianContentProvider,
    HtmlContentProvider,
    RssContentProvider,
)
from backend.app.live_news.content_worker import (  # noqa: E402
    LiveNewsContentWorker,
    ProviderRegistry,
)
from backend.app.repositories.connection import connect, parse_database_url  # noqa: E402


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Acquire body text for queued Live news.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--source-config", type=Path)
    return parser.parse_args(argv)


def build_provider_registry(settings: Settings, fetcher: SafeFetcher) -> ProviderRegistry:
    providers = {
        "rss": RssContentProvider(fetcher),
        "html": HtmlContentProvider(fetcher),
    }
    if settings.guardian_api_key:
        providers["guardian_api"] = GuardianContentProvider(
            fetcher,
            settings.guardian_api_key,
        )
    return ProviderRegistry(providers)


def run_loop(
    worker: LiveNewsContentWorker,
    *,
    once: bool,
    interval: float,
    stop_event: Event,
    sleep: Callable[[float], object] = time.sleep,
    emit: Callable[[dict[str, int]], None] | None = None,
) -> int:
    output = emit or (lambda payload: print(json.dumps(payload, sort_keys=True), flush=True))
    while not stop_event.is_set():
        result = worker.run_once()
        output(result.__dict__)
        if once or stop_event.is_set():
            return 0
        sleep(interval)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    if not settings.database_configured:
        raise SystemExit("NEWSREC_DATABASE_URL is required")
    if not args.once and not settings.live_content_worker_enabled:
        raise SystemExit("NEWSREC_LIVE_CONTENT_WORKER_ENABLED=1 is required")
    if args.poll_interval_seconds <= 0:
        raise SystemExit("poll interval must be positive")

    allowlist = load_allowlist(args.source_config or Path(settings.live_news_source_config))
    connection_config = parse_database_url(settings.database_url)
    store = PostgresLiveContentStore(
        lambda: connect(
            connection_config,
            connect_timeout=settings.postgres_connect_timeout_seconds,
        ),
        allowlist,
    )
    fetcher = SafeFetcher(
        connect_timeout_seconds=settings.live_content_connect_timeout_seconds,
        read_timeout_seconds=settings.live_content_read_timeout_seconds,
        max_response_bytes=settings.live_content_max_response_bytes,
    )
    worker = LiveNewsContentWorker(
        store,
        build_provider_registry(settings, fetcher),
        worker_id=f"{socket.gethostname()}:{os.getpid()}",
        batch_size=settings.live_content_worker_batch_size,
    )
    stop_event = Event()

    def stop(_signum: int, _frame: object) -> None:
        worker.stop()
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    return run_loop(
        worker,
        once=args.once,
        interval=args.poll_interval_seconds,
        stop_event=stop_event,
        sleep=stop_event.wait,
    )


if __name__ == "__main__":
    raise SystemExit(main())
