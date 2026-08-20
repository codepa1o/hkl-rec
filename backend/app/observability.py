from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)

HTTP_REQUESTS = Counter(
    "newsrec_http_requests_total",
    "HTTP requests handled by the API.",
    ("method", "path", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "newsrec_http_request_duration_seconds",
    "HTTP request duration.",
    ("method", "path"),
)
CONSUMER_EVENTS = Counter(
    "newsrec_consumer_events_total",
    "Kafka profile-consumer outcomes.",
    ("outcome", "event_type"),
)
CONSUMER_RETRIES = Counter(
    "newsrec_consumer_retries_total",
    "Kafka profile-consumer transient retries.",
)
CONSUMER_LAG = Gauge(
    "newsrec_consumer_lag_messages",
    "Approximate Kafka consumer lag by partition.",
    ("topic", "partition"),
)
OUTBOX_PUBLISHED = Counter(
    "newsrec_outbox_published_total",
    "Outbox messages delivered to Kafka.",
)
OUTBOX_FAILURES = Counter(
    "newsrec_outbox_failures_total",
    "Outbox publish batch failures.",
)
OUTBOX_ROWS = Gauge(
    "newsrec_outbox_rows",
    "Current outbox rows by status.",
    ("status",),
)
SEARCH_RESOLUTIONS = Counter(
    "newsrec_search_resolutions_total",
    "Search query resolution outcomes.",
    ("mode", "source", "outcome"),
)
SEARCH_RETRIEVAL_DURATION = Histogram(
    "newsrec_search_retrieval_duration_seconds",
    "Search query resolution and retrieval duration.",
    ("mode",),
)
PROFILE_V2_PROJECTION_UPDATES = Counter(
    "profile_v2_projection_updates_total",
    "Profile V2 projection updates by source event type.",
    ("event_type",),
)
PROFILE_V2_LATE_EVENTS = Counter(
    "profile_v2_late_events_total",
    "Profile events skipped because they are before reset or out of order.",
    ("reason",),
)
PROFILE_V2_READ_FALLBACK = Counter(
    "profile_v2_read_fallback_total",
    "Feed requests that rolled back a failed Profile V2 read to a savepoint.",
)
PROFILE_V2_RESET = Counter(
    "profile_v2_reset_total",
    "Profile V2 reset outcomes.",
    ("status",),
)
PROFILE_V2_PROJECTION_DURATION = Histogram(
    "profile_v2_projection_seconds",
    "Profile V2 projection duration in seconds.",
)
LIVE_COLLECTOR_LAST_SUCCESS = Gauge(
    "live_collector_last_success_timestamp",
    "Unix timestamp of the last successful Live collector batch.",
)
LIVE_COLLECTOR_LAG = Gauge(
    "live_collector_lag_seconds",
    "Seconds between collector observation time and the latest imported batch.",
)
LIVE_INGEST_RAW = Counter(
    "live_ingest_raw_total",
    "Raw GDELT GAL rows processed by the Live collector.",
)
LIVE_INGEST_ACCEPTED = Counter(
    "live_ingest_accepted_total",
    "GDELT GAL rows accepted into the Live catalog.",
)
LIVE_INGEST_REJECTED = Counter(
    "live_ingest_rejected_total",
    "GDELT GAL rows rejected by stable reason.",
    ("reason",),
)
LIVE_NEWS_ACTIVE = Gauge(
    "live_news_active_total",
    "Active Live catalog rows by bounded language and approved domain.",
    ("language", "domain"),
)
NEWS_FEED_REQUESTS = Counter(
    "news_feed_requests_total",
    "Feed requests by news space.",
    ("source_space",),
)
USER_EVENTS = Counter(
    "user_events_total",
    "Accepted user events by news space and event type.",
    ("source_space", "event_type"),
)
PROFILE_UPDATES = Counter(
    "profile_updates_total",
    "Profile mutations by news space.",
    ("source_space",),
)
CROSS_SPACE_VALIDATION_FAILURES = Counter(
    "cross_space_validation_failures_total",
    "Requests rejected because source and article identity disagree.",
)

_LIVE_REJECTION_REASONS = frozenset(
    {
        "domain_not_allowed",
        "unsupported_language",
        "stale_article",
        "invalid_page",
        "duplicate_url",
        "duplicate_content",
        "missing_title",
        "invalid_metadata",
    }
)


class JsonLogFormatter(logging.Formatter):
    _standard_fields: ClassVar[set[str]] = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._standard_fields and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(getattr(handler, "_newsrec_json", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    handler._newsrec_json = True  # type: ignore[attr-defined]
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


def start_worker_metrics_server(port: int) -> None:
    start_http_server(port)


def set_outbox_status_counts(counts: dict[str, int]) -> None:
    for status in ("pending", "publishing", "published", "dead"):
        OUTBOX_ROWS.labels(status=status).set(counts.get(status, 0))


def record_live_batch(
    *,
    raw_count: int,
    accepted_count: int,
    rejection_counts: dict[str, int],
    batch_timestamp: float,
    observed_timestamp: float,
) -> None:
    LIVE_INGEST_RAW.inc(max(0, raw_count))
    LIVE_INGEST_ACCEPTED.inc(max(0, accepted_count))
    for reason, count in rejection_counts.items():
        stable_reason = reason if reason in _LIVE_REJECTION_REASONS else "invalid_metadata"
        LIVE_INGEST_REJECTED.labels(reason=stable_reason).inc(max(0, count))
    LIVE_COLLECTOR_LAST_SUCCESS.set(observed_timestamp)
    LIVE_COLLECTOR_LAG.set(max(0.0, observed_timestamp - batch_timestamp))


def set_live_news_active_counts(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        language = str(row.get("language") or "")
        domain = str(row.get("source_domain") or "")
        if language not in {"zh", "en"} or not domain:
            continue
        LIVE_NEWS_ACTIVE.labels(language=language, domain=domain).set(int(row.get("count") or 0))
