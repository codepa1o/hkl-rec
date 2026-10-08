"""Guardian metadata and conservative image-only enrichment of API body blocks."""

from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from .content_document import (
    ContentBlock,
    ImageBlock,
    ListBlock,
    PublisherTag,
    StructuredBodyDocument,
)

GUARDIAN_DOCUMENT_VERSION = "guardian-structured-3"


def guardian_tags(content: dict[str, Any]) -> list[PublisherTag]:
    tags: list[PublisherTag] = []
    seen: set[str] = set()
    raw_tags = content.get("tags")
    if not isinstance(raw_tags, list):
        return tags
    for item in raw_tags:
        if not isinstance(item, dict) or item.get("type") not in {"keyword", "tone"}:
            continue
        try:
            tag = PublisherTag(
                name=str(item.get("webTitle") or "").strip(), url=str(item.get("webUrl") or "")
            )
            host = urlsplit(tag.url).hostname or ""
            if not (host == "theguardian.com" or host.endswith(".theguardian.com")):
                continue
        except (ValueError, ValidationError):
            continue
        if tag.url not in seen:
            tags.append(tag)
            seen.add(tag.url)
        if len(tags) == 50:
            break
    return tags


def _block_text(block: ContentBlock) -> str:
    if isinstance(block, ImageBlock):
        return ""
    return " ".join((" ".join(block.items) if isinstance(block, ListBlock) else block.text).split())


def merge_guardian_images(
    api: StructuredBodyDocument, page: StructuredBodyDocument
) -> StructuredBodyDocument:
    """Keep ALL API text; insert only page images anchored between matching API text blocks."""
    indexes: dict[str, list[int]] = defaultdict(list)
    for index, block in enumerate(api.blocks):
        if text := _block_text(block):
            indexes[text].append(index)
    seen = {urlsplit(b.source_url).path for b in api.blocks if isinstance(b, ImageBlock)}
    inserts: dict[int, list[ImageBlock]] = defaultdict(list)
    for index, block in enumerate(page.blocks):
        if not isinstance(block, ImageBlock) or urlsplit(block.source_url).path in seen:
            continue
        before = next(
            (_block_text(b) for b in reversed(page.blocks[:index]) if _block_text(b)), None
        )
        after = next((_block_text(b) for b in page.blocks[index + 1 :] if _block_text(b)), None)
        following = indexes.get(after or "", [])
        previous = indexes.get(before or "", [])
        if len(following) != 1:
            continue  # No trustworthy position: do not invent an image placement.
        target = following[0]
        if before is None:
            if target != 0:
                continue
        elif (
            len(previous) != 1
            or previous[0] >= target
            or any(not isinstance(b, ImageBlock) for b in api.blocks[previous[0] + 1 : target])
        ):
            continue
        if any(b.id == block.id for b in api.blocks):
            continue
        inserts[target].append(block)
        seen.add(urlsplit(block.source_url).path)
    blocks: list[ContentBlock] = []
    for index, block in enumerate(api.blocks):
        blocks.extend(inserts.get(index, []))
        blocks.append(block)
    return api.model_copy(update={"blocks": blocks})
