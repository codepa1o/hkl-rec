"""Preview blocked Guardian API articles; --apply revalidates API and repairs at most 20."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import get_settings, local_research_content_allowed  # noqa: E402
from backend.app.live_news.allowlist import load_allowlist  # noqa: E402
from backend.app.repositories.connection import connect, parse_database_url  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--since-days", type=int, default=7)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 20 or not 1 <= args.since_days <= 30:
        parser.error("limit must be 1..20; since-days must be 1..30")
    settings = get_settings()
    policy = load_allowlist(Path(settings.live_news_source_config)).match("theguardian.com")
    if (
        not settings.guardian_html_fallback_enabled
        or not local_research_content_allowed(settings)
        or not policy
        or not policy.content.html_fallback_enabled
        or not settings.guardian_api_key
    ):
        parser.error("Enabled Guardian HTML fallback, API key and local research mode are required")
    connection = connect(parse_database_url(settings.database_url))
    try:
        with connection.cursor() as cur:
            cur.execute(
                """SELECT n.article_id, n.title, j.last_error_code FROM live_news n
                JOIN live_news_content_job j ON j.article_id=n.article_id
                WHERE n.status='active' AND (n.source_domain='theguardian.com' OR n.source_domain LIKE '%%.theguardian.com')
                  AND j.status='blocked' AND n.body_text IS NULL
                  AND (j.last_error_code='api_tier_restricted' OR
                       (j.last_error_code='authentication_required' AND j.last_error_detail='publisher returned HTTP 403'))
                  AND n.discovered_at>=CURRENT_TIMESTAMP-(%s*INTERVAL '1 day')
                ORDER BY n.discovered_at DESC,n.article_id LIMIT %s""",
                (args.since_days, args.limit),
            )
            rows = [dict(row) for row in cur.fetchall()]
    finally:
        connection.close()
    print(json.dumps({"apply": args.apply, "candidates": rows}, ensure_ascii=True), flush=True)
    failures = 0
    if args.apply:
        for row in rows:
            # Each invocation rechecks API permissions; generic 403 alone never permits HTML.
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/repair_guardian_content.py"),
                    "--article-id",
                    row["article_id"],
                    "--apply",
                ],
                cwd=ROOT,
                check=False,
            )
            failures += result.returncode != 0
        print(json.dumps({"selected": len(rows), "failed": failures}), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
