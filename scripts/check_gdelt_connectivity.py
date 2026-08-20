from __future__ import annotations

import argparse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

RSS_URL = "https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss"
MAX_RSS_BYTES = 1_000_000


def validate_rss(payload: bytes) -> datetime:
    root = ET.fromstring(payload)
    if root.tag.rsplit("}", 1)[-1].lower() != "rss":
        raise ValueError("GDELT response does not have an RSS root")
    channel = root.find("./channel")
    if channel is None:
        raise ValueError("GDELT RSS does not contain a channel")
    raw_date = channel.findtext("lastBuildDate")
    if not raw_date:
        raise ValueError("GDELT RSS does not contain lastBuildDate")
    parsed = parsedate_to_datetime(raw_date)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def fetch_rss(url: str, timeout_seconds: int) -> bytes:
    headers = {"User-Agent": "NewsIntentRec/1.0"}
    try:
        head = urllib.request.Request(url, headers=headers, method="HEAD")
        with urllib.request.urlopen(head, timeout=timeout_seconds):
            pass
    except urllib.error.HTTPError as exc:
        if exc.code not in {405, 501}:
            raise
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read(MAX_RSS_BYTES + 1)
    if len(payload) > MAX_RSS_BYTES:
        raise ValueError("GDELT RSS exceeds the bounded response size")
    return payload


def run_check(
    *,
    fetch: Callable[[str, int], bytes] = fetch_rss,
    timeout_seconds: int = 10,
) -> datetime:
    return validate_rss(fetch(RSS_URL, timeout_seconds))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check the public GDELT GAL RSS endpoint.")
    parser.add_argument("--timeout-seconds", type=int, default=10)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.timeout_seconds <= 60:
        raise SystemExit("--timeout-seconds must be between 1 and 60")
    observed = run_check(timeout_seconds=args.timeout_seconds)
    print(f"GDELT GAL RSS OK: lastBuildDate={observed.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
