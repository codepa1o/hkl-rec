from __future__ import annotations

import argparse
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from backend.app.config import get_settings
from backend.app.repositories.connection import connect, parse_database_url


@dataclass(frozen=True)
class LinkProbeResult:
    ok: bool
    permanent: bool = False
    detail: str = ""


def next_link_state(
    current_failures: int,
    result: LinkProbeResult,
    *,
    deactivate_after: int = 3,
) -> tuple[int, str]:
    failures = 0 if result.ok else max(0, current_failures) + 1
    return failures, "inactive" if failures >= deactivate_after else "active"


def probe_url(
    url: str,
    timeout_seconds: int,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> LinkProbeResult:
    headers = {"User-Agent": "NewsIntentRec/1.0"}
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, headers=headers, method=method)
        try:
            with opener(request, timeout=timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
            return LinkProbeResult(ok=200 <= status < 400, detail=str(status))
        except urllib.error.HTTPError as exc:
            if exc.code in {404, 410}:
                return LinkProbeResult(ok=False, permanent=True, detail=str(exc.code))
            if method == "HEAD" and exc.code in {405, 501}:
                continue
            return LinkProbeResult(ok=False, detail=f"http_{exc.code}")
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            return LinkProbeResult(ok=False, detail=type(exc).__name__)
    return LinkProbeResult(ok=False, detail="unsupported_head")


def check_links(
    connection: Any,
    *,
    limit: int,
    timeout_seconds: int,
    probe: Callable[[str, int], LinkProbeResult] = probe_url,
) -> dict[str, int]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT article_id, canonical_url, link_failure_count
            FROM live_news
            WHERE status = 'active'
            ORDER BY last_link_check_at ASC NULLS FIRST, article_id ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cursor.fetchall()
    checked = 0
    inactive = 0
    for row in rows:
        result = probe(str(row["canonical_url"]), timeout_seconds)
        failures, status = next_link_state(int(row["link_failure_count"]), result)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE live_news
                SET link_failure_count = %s,
                    status = %s,
                    last_link_check_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE article_id = %s AND status = 'active'
                """,
                (failures, status, row["article_id"]),
            )
        checked += 1
        inactive += int(status == "inactive")
    return {"checked": checked, "inactive": inactive}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check a bounded batch of Live publisher links.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=int, default=10)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.timeout_seconds <= 60:
        raise SystemExit("--timeout-seconds must be between 1 and 60")
    settings = get_settings()
    if not settings.database_configured:
        raise SystemExit("NEWSREC_DATABASE_URL is not configured")
    connection = connect(parse_database_url(settings.database_url))
    try:
        connection.begin()
        summary = check_links(
            connection,
            limit=args.limit,
            timeout_seconds=args.timeout_seconds,
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    print(f"Live link check complete: checked={summary['checked']} inactive={summary['inactive']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
