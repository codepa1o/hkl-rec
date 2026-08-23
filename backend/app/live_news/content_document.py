from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator

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

    @field_validator("source_url", "display_url")
    @classmethod
    def require_https(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("image URLs must use HTTPS")
        return value


ContentBlock = Annotated[
    ParagraphBlock | HeadingBlock | QuoteBlock | ListBlock | ImageBlock,
    Field(discriminator="type"),
]


class StructuredBodyDocument(ApiModel):
    schema_version: Literal[1] = 1
    extraction_version: str = Field(min_length=1, max_length=32)
    source: BodySource
    blocks: list[ContentBlock] = Field(min_length=1, max_length=1_000)
