from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from backend.app.live_news.content_policy import ContentPolicy, ContentRights

if TYPE_CHECKING:
    from backend.app.live_news.content_document import StructuredBodyDocument

BodySource = Literal["guardian_api", "rss", "html"]
BodyStatus = Literal["metadata_only", "pending", "available", "blocked", "failed"]
JobStatus = Literal["pending", "fetching", "completed", "blocked", "failed"]


@dataclass(frozen=True)
class ContentRequest:
    article_id: str
    canonical_url: str
    expected_domain: str
    language: Literal["zh", "en"]
    policy: ContentPolicy
    lead_image_url: str | None = None
    title: str = ""


@dataclass(frozen=True)
class AcquiredContent:
    source: BodySource
    body_text: str
    fetched_at: datetime
    extraction_version: str
    body_document: StructuredBodyDocument | None = None


@dataclass(frozen=True)
class ContentJob:
    article_id: str
    request: ContentRequest
    content_rights: ContentRights
    attempt_count: int


class ContentAcquisitionError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        retryable: bool,
        retry_after: str | None = None,
    ) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.retryable = retryable
        self.retry_after = retry_after
