from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

RejectionReason = Literal[
    "domain_not_allowed",
    "unsupported_language",
    "stale_article",
    "invalid_page",
    "duplicate_url",
    "duplicate_content",
    "missing_title",
    "invalid_metadata",
]


@dataclass(frozen=True)
class LiveNewsArticle:
    article_id: str
    canonical_url: str
    source_external_id: str | None
    title: str
    summary: str
    image_url: str | None
    publisher: str
    source_domain: str
    language: Literal["zh", "en"]
    author: str | None
    published_at: datetime | None
    published_at_quality: Literal["gdelt_unverified", "publisher", "unknown"]
    discovered_at: datetime
    fetched_at: datetime
    content_hash: str
    publisher_quality: float
    raw_metadata: dict[str, Any]


@dataclass(frozen=True)
class RejectedGalRecord:
    reason: RejectionReason
    raw_metadata: dict[str, Any]
    detail: str | None = None


@dataclass(frozen=True)
class LiveNewsCheckpoint:
    source_name: str
    last_batch_time: datetime | None
    last_etag: str | None
    last_modified: str | None
    last_success_at: datetime | None
    last_error: str | None

    def with_error(self, error: str) -> LiveNewsCheckpoint:
        return LiveNewsCheckpoint(
            source_name=self.source_name,
            last_batch_time=self.last_batch_time,
            last_etag=self.last_etag,
            last_modified=self.last_modified,
            last_success_at=self.last_success_at,
            last_error=error,
        )


@dataclass(frozen=True)
class NormalizedGalBatch:
    source_name: str
    batch_id: str
    batch_time: datetime
    source_url: str
    source_sha256: str
    etag: str | None
    last_modified: str | None
    raw_count: int
    articles: tuple[LiveNewsArticle, ...]
    rejections: tuple[RejectedGalRecord, ...]


@dataclass(frozen=True)
class LiveImportResult:
    batch_id: str
    accepted_count: int
    rejected_count: int
