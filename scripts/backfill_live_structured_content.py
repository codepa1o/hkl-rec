from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import get_settings, local_research_content_allowed  # noqa: E402
from backend.app.live_news.allowlist import load_allowlist  # noqa: E402
from backend.app.live_news.content_backfill import (  # noqa: E402
    BackfillFilters,
    enqueue_structured_backfill,
)
from backend.app.repositories.connection import connect, parse_database_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enqueue active Live articles missing structured body documents."
    )
    parser.add_argument("--source-domain")
    parser.add_argument("--source-suffix")
    parser.add_argument("--language", choices=("zh", "en"))
    parser.add_argument("--since-days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    allowlist = load_allowlist(Path(settings.live_news_source_config))
    connection = connect(
        parse_database_url(settings.database_url),
        connect_timeout=settings.postgres_connect_timeout_seconds,
    )
    try:
        count = enqueue_structured_backfill(
            connection,
            BackfillFilters(
                source_domain=args.source_domain,
                source_suffix=args.source_suffix,
                language=args.language,
                since_days=args.since_days,
                limit=args.limit,
            ),
            dry_run=args.dry_run,
            allowlist=allowlist,
            local_research_allowed=local_research_content_allowed(settings),
        )
    finally:
        connection.close()
    print(json.dumps({"dry_run": args.dry_run, "article_count": count}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
