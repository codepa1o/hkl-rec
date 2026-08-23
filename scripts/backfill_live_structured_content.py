from __future__ import annotations

import argparse
import json

from backend.app.config import get_settings
from backend.app.live_news.content_backfill import BackfillFilters, enqueue_structured_backfill
from backend.app.repositories.connection import connect, parse_database_url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enqueue active Live articles missing structured body documents."
    )
    parser.add_argument("--source-domain")
    parser.add_argument("--language", choices=("zh", "en"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    connection = connect(
        parse_database_url(settings.database_url),
        connect_timeout=settings.postgres_connect_timeout_seconds,
    )
    try:
        count = enqueue_structured_backfill(
            connection,
            BackfillFilters(
                source_domain=args.source_domain,
                language=args.language,
                limit=args.limit,
            ),
            dry_run=args.dry_run,
        )
    finally:
        connection.close()
    print(json.dumps({"dry_run": args.dry_run, "article_count": count}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
