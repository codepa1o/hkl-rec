from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, Literal

from pydantic import Field, model_validator

from backend.app.news_spaces.types import NewsSpace, validate_article_id_shape
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
    "outbound_click",
]

ARTICLE_EVENTS = frozenset(
    {
        "recommendation_click",
        "search_result_click",
        "feed_impression",
        "detail_view",
        "dwell",
        "upvote",
        "downvote",
        "share",
        "outbound_click",
    }
)


def new_event_id() -> str:
    return f"evt-{uuid.uuid4().hex}"


class UserEventMessage(ApiModel):
    schema_version: Literal[2, 3, 4, 5] = 5
    event_id: str = Field(default_factory=new_event_id)
    event_type: UserEventType
    user_id: int
    source_space: NewsSpace
    article_id: str | None = None
    news_id: str | None = Field(default=None, description="Deprecated MIND compatibility alias")
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

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        migrated = value.copy()
        schema_version = migrated.get("schema_version", 5)
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise ValueError("schema_version must be an integer")
        if schema_version in {2, 3, 4}:
            if schema_version == 2:
                authoritative_id = migrated.pop("answer_id", None)
            elif schema_version == 3:
                authoritative_id = migrated.get("article_id")
            else:
                authoritative_id = migrated.get("news_id")

            migrated["source_space"] = "mind"
            migrated.pop("answer_id", None)
            migrated.pop("article_id", None)
            migrated.pop("news_id", None)
            if authoritative_id is not None:
                if schema_version in {2, 3}:
                    if isinstance(authoritative_id, bool) or not isinstance(authoritative_id, int):
                        raise ValueError(
                            f"schema v{schema_version} article identity must be an integer"
                        )
                    migrated["article_id"] = f"N{authoritative_id}"
                else:
                    migrated["article_id"] = authoritative_id
                    migrated["news_id"] = authoritative_id
        return migrated

    @model_validator(mode="after")
    def validate_event(self) -> UserEventMessage:
        if self.source_space == "live" and self.news_id is not None:
            raise ValueError("news_id is only supported for source_space 'mind'")
        if self.schema_version == 5 and self.news_id is not None and self.article_id is None:
            raise ValueError("news_id alias requires canonical article_id")
        if (
            self.source_space == "mind"
            and self.news_id is not None
            and self.article_id is not None
            and self.news_id != self.article_id
        ):
            raise ValueError("article_id and news_id must match")
        if self.article_id is not None:
            self.article_id = validate_article_id_shape(self.source_space, self.article_id)
        if self.event_type in ARTICLE_EVENTS and self.article_id is None:
            raise ValueError(f"{self.event_type} event requires article_id")
        if self.event_type in {"search_query", "search_result_click"} and not self.query_key:
            raise ValueError(f"{self.event_type} event requires query_key")
        if self.source_space == "live" and any(
            value is not None
            for value in (
                self.sponsored_delivery_id,
                self.campaign_id,
                self.creative_id,
            )
        ):
            raise ValueError("Sponsored identity is only supported for source_space 'mind'")
        if self.event_type == "dwell" and self.dwell_ms is None:
            raise ValueError("dwell event requires dwell_ms")
        if self.dwell_ms is not None and not 0 <= self.dwell_ms <= 86_400_000:
            raise ValueError("dwell_ms must be between 0 and 86400000")
        return self

    @property
    def partition_key(self) -> str:
        return f"{self.source_space}:{self.user_id}"

    def publish_partition_key(self, source_keys_enabled: bool) -> str:
        if self.source_space == "mind" and not source_keys_enabled:
            return str(self.user_id)
        return self.partition_key

    def to_json_bytes(self) -> bytes:
        if self.schema_version == 5:
            return self.model_dump_json(exclude_none=True).encode("utf-8")
        payload = self.model_dump(
            exclude={"source_space", "article_id", "news_id"},
            exclude_none=True,
        )
        if self.article_id is not None:
            if self.schema_version == 2:
                payload["answer_id"] = int(self.article_id[1:])
            elif self.schema_version == 3:
                payload["article_id"] = int(self.article_id[1:])
            else:
                payload["news_id"] = self.news_id
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

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
        if self.schema_version == 2:
            payload["answer_id"] = int(self.article_id[1:]) if self.article_id is not None else None
        elif self.schema_version == 3:
            payload["article_id"] = (
                int(self.article_id[1:]) if self.article_id is not None else None
            )
        elif self.schema_version == 4:
            payload["news_id"] = self.news_id
        else:
            payload["source_space"] = self.source_space
            payload["article_id"] = self.article_id
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class TrainingInteractionMessage(ApiModel):
    schema_version: Literal[5] = 5
    example_id: str
    user_id: int
    source_space: NewsSpace
    article_id: str | None = None
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

    @model_validator(mode="after")
    def validate_event(self) -> TrainingInteractionMessage:
        if self.article_id is not None:
            self.article_id = validate_article_id_shape(self.source_space, self.article_id)
        if self.event_type in ARTICLE_EVENTS and self.article_id is None:
            raise ValueError(f"{self.event_type} event requires article_id")
        if self.source_space == "live" and any(
            value is not None
            for value in (
                self.sponsored_delivery_id,
                self.campaign_id,
                self.creative_id,
            )
        ):
            raise ValueError("Sponsored identity is only supported for source_space 'mind'")
        return self

    @property
    def partition_key(self) -> str:
        return f"{self.source_space}:{self.user_id}"

    def publish_partition_key(self, source_keys_enabled: bool) -> str:
        if self.source_space == "mind" and not source_keys_enabled:
            return str(self.user_id)
        return self.partition_key

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
