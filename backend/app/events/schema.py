from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, Literal

from pydantic import Field, model_validator

from backend.app.schemas.common import ApiModel

UserEventType = Literal[
    "search_query",
    "recommendation_click",
    "search_result_click",
    "feed_impression",
    "detail_view",
    "dwell",
    "upvote",
    "downvote",
    "share",
]


def new_event_id() -> str:
    return f"evt-{uuid.uuid4().hex}"


class UserEventMessage(ApiModel):
    schema_version: Literal[4] = 4
    event_id: str = Field(default_factory=new_event_id)
    event_type: UserEventType
    user_id: int
    news_id: str | None = Field(None, pattern=r"^N[0-9]+$")
    query_key: str | None = None
    query_text: str | None = None
    request_id: str | None = None
    sponsored_delivery_id: str | None = None
    campaign_id: int | None = None
    creative_id: int | None = None
    surface: str = "feed"
    event_ts: int
    producer_ts: int = Field(default_factory=lambda: int(time.time()))
    source: str = "api"
    dwell_ms: int | None = None
    debug: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_dwell(self) -> UserEventMessage:
        if self.event_type == "dwell" and self.dwell_ms is None:
            raise ValueError("dwell event requires dwell_ms")
        if self.dwell_ms is not None and not 0 <= self.dwell_ms <= 86_400_000:
            raise ValueError("dwell_ms must be between 0 and 86400000")
        return self

    @property
    def partition_key(self) -> str:
        return str(self.user_id)

    def to_json_bytes(self) -> bytes:
        return self.model_dump_json(exclude_none=True).encode("utf-8")

    @property
    def idempotency_fingerprint(self) -> str:
        payload = {
            "event_type": self.event_type,
            "user_id": self.user_id,
            "query_key": self.query_key,
            "query_text": self.query_text,
            "request_id": self.request_id,
            "sponsored_delivery_id": self.sponsored_delivery_id,
            "surface": self.surface,
            "dwell_ms": self.dwell_ms,
            "source": self.source,
        }
        payload["news_id"] = self.news_id
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class TrainingInteractionMessage(ApiModel):
    schema_version: Literal[4] = 4
    example_id: str
    user_id: int
    news_id: str | None = Field(None, pattern=r"^N[0-9]+$")
    query_key: str | None = None
    request_id: str | None = None
    surface: str | None = None
    sponsored_delivery_id: str | None = None
    campaign_id: int | None = None
    creative_id: int | None = None
    label: float | None = None
    event_type: UserEventType
    event_ts: int
    source: str = "profile-consumer"

    @property
    def partition_key(self) -> str:
        return str(self.user_id)

    def to_json_bytes(self) -> bytes:
        return self.model_dump_json(exclude_none=True).encode("utf-8")


class DlqEventMessage(ApiModel):
    schema_version: int = 2
    original_topic: str
    original_partition: int | None = None
    original_offset: int | None = None
    original_payload: str
    original_payload_encoding: Literal["utf-8", "base64"] = "utf-8"
    error_type: str
    error_message: str
    failed_at: int = Field(default_factory=lambda: int(time.time()))

    @property
    def partition_key(self) -> str:
        return self.original_topic

    def to_json_bytes(self) -> bytes:
        return self.model_dump_json(exclude_none=True).encode("utf-8")
