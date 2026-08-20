from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.app.live_news.allowlist import load_allowlist
from backend.app.live_news.collector import FetchResult, LiveNewsCollector, MissingBatch
from backend.app.live_news.types import LiveImportResult, LiveNewsCheckpoint, NormalizedGalBatch

LATEST = datetime(2026, 8, 17, 2, 16, tzinfo=UTC)


class FakeStore:
    def __init__(self) -> None:
        self.checkpoint: LiveNewsCheckpoint | None = None
        self.batches: list[NormalizedGalBatch] = []

    def load_checkpoint(self, source_name: str) -> LiveNewsCheckpoint | None:
        assert source_name == "gdelt_gal"
        return self.checkpoint

    def persist_batch(self, batch: NormalizedGalBatch) -> LiveImportResult:
        self.batches.append(batch)
        self.checkpoint = LiveNewsCheckpoint(
            source_name=batch.source_name,
            last_batch_time=batch.batch_time,
            last_etag=batch.etag,
            last_modified=batch.last_modified,
            last_success_at=batch.batch_time,
            last_error=None,
        )
        return LiveImportResult(
            batch_id=batch.batch_id,
            accepted_count=len(batch.articles),
            rejected_count=len(batch.rejections),
        )

    def record_failure(self, source_name: str, error: str) -> None:
        if self.checkpoint is not None:
            self.checkpoint = self.checkpoint.with_error(error)


def rss_bytes() -> bytes:
    return (
        b"<?xml version='1.0'?><rss><channel>"
        b"<lastBuildDate>17 Aug 2026 02:16:00 +0000</lastBuildDate>"
        b"</channel></rss>"
    )


def gal_bytes() -> bytes:
    rows = Path("tests/fixtures/gdelt_gal_sample.jsonl").read_bytes()
    return gzip.compress(rows)


def test_collector_normalizes_and_persists_latest_batch() -> None:
    store = FakeStore()

    def fetch(url: str) -> FetchResult:
        if url.endswith("feed.rss"):
            return FetchResult(rss_bytes(), '"rss-etag"', "rss-modified")
        if "20260817021600" in url:
            return FetchResult(gal_bytes(), '"batch-etag"', "batch-modified")
        raise MissingBatch(url)

    collector = LiveNewsCollector(
        fetch=fetch,
        store=store,
        allowlist=load_allowlist(Path("config/live_news_sources.json")),
        replay_minutes=0,
    )

    results = collector.run_once(now=LATEST)

    assert len(results) == 1
    assert results[0].accepted_count == 2
    assert results[0].rejected_count == 1
    assert store.checkpoint is not None
    assert store.checkpoint.last_batch_time == LATEST
    assert store.batches[0].source_sha256


def test_failed_fetch_does_not_advance_checkpoint() -> None:
    store = FakeStore()

    def fetch(url: str) -> FetchResult:
        if url.endswith("feed.rss"):
            return FetchResult(rss_bytes(), None, None)
        raise OSError("network down")

    collector = LiveNewsCollector(
        fetch=fetch,
        store=store,
        allowlist=load_allowlist(Path("config/live_news_sources.json")),
        replay_minutes=0,
    )

    with pytest.raises(OSError, match="network down"):
        collector.run_once(now=LATEST)

    assert store.checkpoint is None
    assert store.batches == []


def test_malformed_json_line_is_rejected_without_losing_valid_rows() -> None:
    valid = json.loads(
        Path("tests/fixtures/gdelt_gal_sample.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    payload = gzip.compress((json.dumps(valid) + "\n{bad json}\n").encode())
    store = FakeStore()

    def fetch(url: str) -> FetchResult:
        if url.endswith("feed.rss"):
            return FetchResult(rss_bytes(), None, None)
        return FetchResult(payload, None, None)

    collector = LiveNewsCollector(
        fetch=fetch,
        store=store,
        allowlist=load_allowlist(Path("config/live_news_sources.json")),
        replay_minutes=0,
    )

    result = collector.run_once(now=LATEST)[0]

    assert result.accepted_count == 1
    assert result.rejected_count == 1
