from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db.migration import migrate_mysql_to_postgres  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate all NewsIntentRec history from read-only MySQL to PostgreSQL."
    )
    parser.add_argument(
        "--source-url",
        default=os.environ.get("NEWSREC_MYSQL_SOURCE_URL", ""),
        help="MySQL source URL (or NEWSREC_MYSQL_SOURCE_URL).",
    )
    parser.add_argument(
        "--target-url",
        default=os.environ.get("NEWSREC_DATABASE_URL", ""),
        help="PostgreSQL target URL (or NEWSREC_DATABASE_URL).",
    )
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("build/migrations/mysql-to-postgres-report.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.source_url or not args.target_url:
        raise SystemExit("both source and target database URLs are required")
    report = migrate_mysql_to_postgres(
        args.source_url,
        args.target_url,
        batch_size=args.batch_size,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
