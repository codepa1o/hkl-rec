from __future__ import annotations

import gzip
import hashlib
import json
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Protocol

from backend.app.live_news.allowlist import SourceAllowlist
from backend.app.live_news.normalize import classify_gal_record, deduplicate_articles
from backend.app.live_news.types import (
    LiveImportResult,
    LiveNewsArticle,
    LiveNewsCheckpoint,
    NormalizedGalBatch,
    RejectedGalRecord,
)
from backend.app.observability import record_live_batch

SOURCE_NAME = "gdelt_gal"
RSS_URL = "https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss"
GAL_URL_TEMPLATE = (
    "https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/{timestamp}.gal.json.gz"
)


@dataclass(frozen=True)
class FetchResult:
    data: bytes
    etag: str | None
    last_modified: str | None


class MissingBatch(FileNotFoundError):
    pass


class LiveNewsStore(Protocol):
    def load_checkpoint(self, source_name: str) -> LiveNewsCheckpoint | None: ...

    def persist_batch(self, batch: NormalizedGalBatch) -> LiveImportResult: ...

    def record_failure(self, source_name: str, error: str) -> None: ...


def fetch_url(url: str, *, timeout_seconds: int = 20) -> FetchResult:
    request = urllib.request.Request(url, headers={"User-Agent": "NewsIntentRec/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return FetchResult(
                data=response.read(),
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise MissingBatch(url) from exc
        raise


def parse_latest_batch_time(payload: bytes) -> datetime:
    root = ET.fromstring(payload)
    raw = root.findtext("./channel/lastBuildDate")
    if not raw:
        raise ValueError("GDELT RSS does not contain lastBuildDate")
    parsed = parsedate_to_datetime(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(second=0, microsecond=0)


def minute_range(start: datetime, end: datetime) -> Iterable[datetime]:
    current = start.replace(second=0, microsecond=0)
    finish = end.replace(second=0, microsecond=0)
    while current <= finish:
        yield current
        current += timedelta(minutes=1)


class LiveNewsCollector:
    def __init__(
        self,
        *,
        fetch: Callable[[str], FetchResult],
        store: LiveNewsStore,
        allowlist: SourceAllowlist,
        replay_minutes: int = 60,
        max_age_hours: int = 72,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        if replay_minutes < 0:
            raise ValueError("replay_minutes must be non-negative")
        if max_age_hours <= 0:
            raise ValueError("max_age_hours must be positive")
        self._fetch = fetch
        self._store = store
        self._allowlist = allowlist
        self._replay_minutes = replay_minutes
        self._max_age = timedelta(hours=max_age_hours)
        self._should_stop = should_stop or (lambda: False)

    def run_once(self, *, now: datetime | None = None) -> list[LiveImportResult]:
        observed_now = (now or datetime.now(UTC)).astimezone(UTC)
        rss = self._fetch(RSS_URL)
        latest = min(
            parse_latest_batch_time(rss.data), observed_now.replace(second=0, microsecond=0)
        )
        checkpoint = self._store.load_checkpoint(SOURCE_NAME)
        replay_start = latest - timedelta(minutes=self._replay_minutes)
        if checkpoint is None or checkpoint.last_batch_time is None:
            start = replay_start
        else:
            start = max(checkpoint.last_batch_time + timedelta(minutes=1), replay_start)
        results: list[LiveImportResult] = []
        try:
            for batch_time in minute_range(start, latest):
                if self._should_stop():
                    break
                timestamp = batch_time.strftime("%Y%m%d%H%M%S")
                source_url = GAL_URL_TEMPLATE.format(timestamp=timestamp)
                try:
                    fetched = self._fetch(source_url)
                except MissingBatch:
                    continue
                batch = self._normalize_batch(
                    batch_time=batch_time,
                    source_url=source_url,
                    fetched=fetched,
                )
                result = self._store.persist_batch(batch)
                results.append(result)
                record_live_batch(
                    raw_count=batch.raw_count,
                    accepted_count=result.accepted_count,
                    rejection_counts=dict(Counter(item.reason for item in batch.rejections)),
                    batch_timestamp=batch.batch_time.timestamp(),
                    observed_timestamp=observed_now.timestamp(),
                )
        except Exception as exc:
            self._store.record_failure(SOURCE_NAME, f"{type(exc).__name__}: {exc}")
            raise
        return results

    def _normalize_batch(
        self,
        *,
        batch_time: datetime,
        source_url: str,
        fetched: FetchResult,
    ) -> NormalizedGalBatch:
        try:
            lines = gzip.decompress(fetched.data).decode("utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"invalid GDELT gzip batch: {source_url}") from exc
        articles: list[LiveNewsArticle] = []
        rejections: list[RejectedGalRecord] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                rejections.append(
                    RejectedGalRecord(
                        "invalid_metadata",
                        {"raw_line": line[:1000]},
                        str(exc),
                    )
                )
                continue
            if not isinstance(raw, dict):
                rejections.append(RejectedGalRecord("invalid_metadata", {"raw_value": raw}))
                continue
            classified = classify_gal_record(
                raw,
                discovered_at=batch_time,
                allowlist=self._allowlist,
                max_age=self._max_age,
            )
            if isinstance(classified, LiveNewsArticle):
                articles.append(classified)
            else:
                rejections.append(classified)
        kept, duplicate_rejections = deduplicate_articles(articles)
        rejections.extend(duplicate_rejections)
        return NormalizedGalBatch(
            source_name=SOURCE_NAME,
            batch_id=f"{SOURCE_NAME}:{batch_time.strftime('%Y%m%d%H%M%S')}",
            batch_time=batch_time,
            source_url=source_url,
            source_sha256=hashlib.sha256(fetched.data).hexdigest(),
            etag=fetched.etag,
            last_modified=fetched.last_modified,
            raw_count=sum(1 for line in lines if line.strip()),
            articles=tuple(kept),
            rejections=tuple(rejections),
        )
