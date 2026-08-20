from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts.check_gdelt_connectivity import run_check, validate_rss

VALID_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><lastBuildDate>Mon, 17 Aug 2026 08:15:00 GMT</lastBuildDate></channel></rss>
"""


def test_validate_rss_requires_rss_channel_and_last_build_date() -> None:
    assert validate_rss(VALID_RSS) == datetime(2026, 8, 17, 8, 15, tzinfo=UTC)

    with pytest.raises(ValueError, match="RSS root"):
        validate_rss(b"<html><channel /></html>")
    with pytest.raises(ValueError, match="lastBuildDate"):
        validate_rss(b"<rss><channel /></rss>")


def test_run_check_uses_injected_bytes_without_network() -> None:
    calls: list[tuple[str, int]] = []

    def fetch(url: str, timeout_seconds: int) -> bytes:
        calls.append((url, timeout_seconds))
        return VALID_RSS

    observed = run_check(fetch=fetch, timeout_seconds=7)

    assert observed == datetime(2026, 8, 17, 8, 15, tzinfo=UTC)
    assert calls == [
        (
            "https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss",
            7,
        )
    ]
