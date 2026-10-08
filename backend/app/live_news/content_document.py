from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from backend.app.schemas.common import ApiModel

from .content_types import BodySource

BodyStructureStatus = Literal["missing", "pending", "available", "failed", "blocked"]
ImageCacheStatus = Literal["remote_only", "pending", "cached", "failed", "omitted"]


class ContentBlockBase(ApiModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")


class ParagraphBlock(ContentBlockBase):
    type: Literal["paragraph"] = "paragraph"
    text: str = Field(min_length=1, max_length=200_000)


class HeadingBlock(ContentBlockBase):
    type: Literal["heading"] = "heading"
    level: int = Field(ge=2, le=4)
    text: str = Field(min_length=1, max_length=2_000)


class QuoteBlock(ContentBlockBase):
    type: Literal["quote"] = "quote"
    text: str = Field(min_length=1, max_length=20_000)
    attribution: str | None = Field(default=None, max_length=2_000)


class ListBlock(ContentBlockBase):
    type: Literal["list"] = "list"
    ordered: bool
    items: list[str] = Field(min_length=1, max_length=100)

    @field_validator("items")
    @classmethod
    def validate_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 20_000 for value in values):
            raise ValueError("list items must contain bounded non-empty text")
        return values


class ImageBlock(ContentBlockBase):
    type: Literal["image"] = "image"
    asset_id: str = Field(min_length=1, max_length=64)
    source_url: str = Field(max_length=4_096)
    display_url: str | None = Field(default=None, max_length=4_096)
    alt: str | None = Field(default=None, max_length=2_000)
    caption: str | None = Field(default=None, max_length=2_000)
    credit: str | None = Field(default=None, max_length=2_000)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    mime_type: str | None = Field(default=None, max_length=64)
    cache_status: ImageCacheStatus
    access_scope: Literal["public", "local_research"] = "public"

    @model_validator(mode="after")
    def validate_urls(self) -> ImageBlock:
        internal = bool(
            self.display_url
            and re.fullmatch(r"/articles/live/L[0-9a-f]{32}/assets/[0-9a-f]{32}", self.display_url)
        )
        for field, value in (("source", self.source_url), ("display", self.display_url)):
            if value is None or (field == "display" and internal):
                continue
            parsed = urlsplit(value)
            research_source = (
                field == "source"
                and self.access_scope == "local_research"
                and internal
                and parsed.scheme == "http"
            )
            if (
                not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in {None, 80 if parsed.scheme == "http" else 443}
                or (parsed.scheme != "https" and not research_source)
            ):
                raise ValueError("image URLs must use HTTPS or a guarded research image endpoint")
        if internal and (
            self.access_scope != "local_research"
            or not (self.display_url or "").endswith("/" + self.asset_id)
        ):
            raise ValueError("internal image endpoint requires matching research asset")
        return self


ContentBlock = Annotated[
    ParagraphBlock | HeadingBlock | QuoteBlock | ListBlock | ImageBlock,
    Field(discriminator="type"),
]


class PublisherTag(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(max_length=4096)

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("publisher tag URLs must use HTTPS without credentials")
        return value


class StructuredBodyDocument(ApiModel):
    schema_version: Literal[1] = 1
    extraction_version: str = Field(min_length=1, max_length=32)
    source: BodySource
    blocks: list[ContentBlock] = Field(min_length=1, max_length=1_000)
    publisher_tags: list[PublisherTag] = Field(default_factory=list, max_length=50)
    fallback_reason: str | None = Field(default=None, max_length=64)
    html_adapter_version: str | None = Field(default=None, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=10)
    byline: str | None = Field(default=None, max_length=1000)
    published_at: datetime | None = None
