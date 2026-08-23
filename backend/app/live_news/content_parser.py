from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Literal, cast
from urllib.parse import urljoin, urlsplit

from lxml import html as lxml_html  # type: ignore[import-untyped]
from lxml.html import HtmlElement  # type: ignore[import-untyped]

from .content_document import (
    ContentBlock,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    ParagraphBlock,
    QuoteBlock,
    StructuredBodyDocument,
)
from .content_normalize import normalize_body
from .content_types import BodySource

NOISE_TAGS = frozenset({"nav", "aside", "script", "style", "form", "noscript"})


def _text(element: HtmlElement) -> str:
    return re.sub(r"\s+", " ", element.text_content()).strip()


def _host_allowed(url: str, allowed_domains: frozenset[str]) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.rstrip(".").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


def _srcset_url(value: str) -> str | None:
    candidates: list[tuple[int, str]] = []
    for raw in value.split(","):
        parts = raw.strip().split()
        if not parts:
            continue
        score = 0
        if len(parts) > 1:
            descriptor = parts[-1].lower()
            try:
                score = int(
                    float(descriptor.rstrip("wx")) * (1000 if descriptor.endswith("x") else 1)
                )
            except ValueError:
                score = 0
        candidates.append((score, parts[0]))
    return max(candidates, default=(0, ""))[1] or None


def _image_url(figure: HtmlElement, base_url: str) -> str | None:
    sources = figure.xpath(".//source[@srcset or @data-srcset]")
    images = figure.xpath(".//img")
    candidates: list[str] = []
    for element in [*sources, *images]:
        for attribute in ("data-srcset", "srcset"):
            if element.get(attribute):
                selected = _srcset_url(str(element.get(attribute)))
                if selected:
                    candidates.append(selected)
        for attribute in ("data-src", "src"):
            if element.get(attribute):
                candidates.append(str(element.get(attribute)))
    return urljoin(base_url, candidates[0]) if candidates else None


def _stable_id(article_id: str, index: int, block_type: str, content: str) -> str:
    digest = hashlib.sha256(f"{article_id}\0{index}\0{block_type}\0{content}".encode()).hexdigest()[
        :16
    ]
    prefix = {"paragraph": "p", "heading": "h", "quote": "q", "list": "l", "image": "img"}[
        block_type
    ]
    return f"{prefix}-{digest}"


def _image_block(
    element: HtmlElement,
    *,
    article_id: str,
    index: int,
    base_url: str,
    allowed_image_domains: frozenset[str],
) -> ImageBlock | None:
    url = _image_url(element, base_url)
    if not url or not _host_allowed(url, allowed_image_domains):
        return None
    images = element.xpath(".//img")
    image = images[0] if images else element
    captions = element.xpath(".//figcaption")
    caption = _text(captions[0]) if captions else None
    credits = element.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' credit ')]")
    credit = _text(credits[0]) if credits else None
    width = int(image.get("width")) if str(image.get("width") or "").isdigit() else None
    height = int(image.get("height")) if str(image.get("height") or "").isdigit() else None
    block_id = _stable_id(article_id, index, "image", url)
    return ImageBlock(
        id=block_id,
        asset_id=hashlib.sha256(
            f"{article_id}\0{block_id}\0{url}".encode()
        ).hexdigest()[:32],
        source_url=url,
        display_url=url,
        alt=str(image.get("alt") or "").strip() or None,
        caption=caption,
        credit=credit,
        width=width,
        height=height,
        mime_type=None,
        cache_status="remote_only",
    )


def parse_structured_document(
    document_html: str,
    *,
    article_id: str,
    source: BodySource,
    base_url: str,
    allowed_image_domains: frozenset[str],
) -> StructuredBodyDocument:
    document = lxml_html.fromstring(document_html)
    for element in document.xpath("//nav|//aside|//script|//style|//form|//noscript|//*[@hidden]"):
        element.drop_tree()
    containers = document.xpath("//article") or document.xpath("//body") or [document]
    root = cast(HtmlElement, containers[0])
    blocks: list[ContentBlock] = []

    def append_text(
        block_type: Literal["paragraph", "heading", "quote"], value: str, **extra: object
    ) -> None:
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized:
            return
        block_id = _stable_id(article_id, len(blocks), block_type, normalized)
        if block_type == "paragraph":
            blocks.append(ParagraphBlock(id=block_id, text=normalized))
        elif block_type == "heading":
            blocks.append(
                HeadingBlock(id=block_id, text=normalized, level=cast(int, extra["level"]))
            )
        else:
            blocks.append(
                QuoteBlock(
                    id=block_id,
                    text=normalized,
                    attribution=cast(str | None, extra.get("attribution")),
                )
            )

    def walk(elements: Iterable[HtmlElement]) -> None:
        for element in elements:
            tag = str(element.tag).lower()
            if tag in NOISE_TAGS:
                continue
            if tag == "p":
                append_text("paragraph", _text(element))
                continue
            if tag in {"h2", "h3", "h4"}:
                append_text("heading", _text(element), level=int(tag[1]))
                continue
            if tag == "blockquote":
                cites = element.xpath(".//cite")
                attribution = _text(cites[0]) if cites else None
                for cite in cites:
                    cite.drop_tree()
                append_text("quote", _text(element), attribution=attribution)
                continue
            if tag in {"ul", "ol"}:
                items = [_text(item) for item in element.xpath("./li") if _text(item)]
                if items:
                    content = "\0".join(items)
                    blocks.append(
                        ListBlock(
                            id=_stable_id(article_id, len(blocks), "list", content),
                            ordered=tag == "ol",
                            items=items,
                        )
                    )
                continue
            if tag in {"figure", "img", "picture"}:
                image = _image_block(
                    element,
                    article_id=article_id,
                    index=len(blocks),
                    base_url=base_url,
                    allowed_image_domains=allowed_image_domains,
                )
                if image:
                    blocks.append(image)
                continue
            walk(cast(list[HtmlElement], list(element)))

    walk(cast(list[HtmlElement], list(root)))
    return StructuredBodyDocument(
        extraction_version="structured-1",
        source=source,
        blocks=blocks,
    )


def derive_body_text(document: StructuredBodyDocument) -> str:
    values: list[str] = []
    for block in document.blocks:
        if isinstance(block, (ParagraphBlock, HeadingBlock, QuoteBlock)):
            values.append(block.text)
        elif isinstance(block, ListBlock):
            values.extend(block.items)
        elif isinstance(block, ImageBlock) and block.caption:
            values.append(block.caption)
    return normalize_body("\n\n".join(values))


def document_hash(document: StructuredBodyDocument) -> str:
    payload = json.dumps(
        document.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
