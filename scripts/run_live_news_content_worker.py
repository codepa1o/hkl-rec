from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import time
from pathlib import Path
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

    def stop(_signum: int, _frame: object) -> None:
        worker.stop()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while True:
        result = worker.run_once()
        print(json.dumps(result.__dict__, sort_keys=True), flush=True)
        if args.once:
            return 0
        time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
