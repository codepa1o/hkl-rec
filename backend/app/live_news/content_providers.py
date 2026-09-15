from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Protocol, cast
from urllib.parse import quote, urlencode, urlsplit
from xml.etree import ElementTree

from lxml import html as lxml_html  # type: ignore[import-untyped]
from trafilatura import extract

from backend.app.live_news.content_decode import decode_html
from backend.app.live_news.content_document import ImageBlock, StructuredBodyDocument
from backend.app.live_news.content_fetch import FetchPolicy, SafeFetcher
from backend.app.live_news.content_normalize import validate_body
from backend.app.live_news.content_parser import derive_body_text, parse_structured_document
from backend.app.live_news.content_types import (
    AcquiredContent,
    BodySource,
    ContentAcquisitionError,
    ContentRequest,
)
from backend.app.live_news.html_adapters import get_html_adapter
from backend.app.live_news.normalize import canonicalize_url

EXTRACTION_VERSION = "trafilatura-2.1"
CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"
PAYWALL_MARKERS = (
    "subscribe to continue",
    "sign in to continue",
    "log in to continue",
    "already a subscriber",
)


def _image_identity(url: str) -> str:
    path = urlsplit(url).path
    match = re.search(r"/img/media/([^/]+)", path)
    return match.group(1) if match else path


class ContentProvider(Protocol):
    def acquire(self, request: ContentRequest) -> AcquiredContent: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _html_to_valid_body(html: str, request: ContentRequest) -> tuple[str, StructuredBodyDocument]:
    document = (
        html if "<html" in html.lower() else f"<html><body><article>{html}</article></body></html>"
    )
    extracted = extract(
        document,
        url=request.canonical_url,
        output_format="txt",
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not extracted:
        raise ContentAcquisitionError(
            "extraction_too_short", "provider returned no extractable body", retryable=False
        )
    document_model = parse_structured_document(
        document,
        article_id=request.article_id,
        source=cast(BodySource, request.policy.mode),
        base_url=request.canonical_url,
        allowed_image_domains=frozenset(request.policy.images.allowed_domains),
    )
    body_text = validate_body(derive_body_text(document_model), language=request.language)
    return body_text, document_model


def _host_matches(host: str, domain: str) -> bool:
    host = host.rstrip(".").lower()
    domain = domain.rstrip(".").lower()
    return host == domain or host.endswith(f".{domain}")


def _normalized_title(value: str) -> str:
    value = re.sub(r"(?:[-_—|]\s*)?(?:新华网.*|人民网.*|中新网.*)$", "", value.strip())
    return "".join(character.casefold() for character in value if character.isalnum())


def _page_title_matches(document_html: str, expected_title: str) -> bool:
    expected = _normalized_title(expected_title)
    if not expected:
        return True
    document = lxml_html.fromstring(document_html)
    candidates = [
        _normalized_title(str(value))
        for value in document.xpath("//h1//text() | //title/text()")
        if str(value).strip()
    ]
    if not candidates:
        return True
    return any(
        expected in candidate
        or candidate in expected
        or SequenceMatcher(None, expected, candidate).ratio() >= 0.45
        for candidate in candidates
        if candidate
    )


class GuardianContentProvider:
    def __init__(
        self,
        fetcher: SafeFetcher,
        api_key: str,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Guardian API key is required")
        self._fetcher = fetcher
        self._api_key = api_key.strip()
        self._clock = clock

    def acquire(self, request: ContentRequest) -> AcquiredContent:
        path = urlsplit(request.canonical_url).path.strip("/")
        if not path:
            raise ContentAcquisitionError(
                "invalid_url", "Guardian article URL has no content path", retryable=False
            )
        query = urlencode(
            {
                "show-fields": "body,headline,standfirst,thumbnail,byline",
                "show-blocks": "all",
                "show-elements": "image",
                "show-rights": "all",
                "api-key": self._api_key,
            }
        )
        api_url = f"https://content.guardianapis.com/{quote(path, safe='/')}?{query}"
        response = self._fetcher.get(
            api_url,
            expected_domain="content.guardianapis.com",
            accepted_content_types=frozenset({"application/json"}),
        )
        try:
            payload = json.loads(response.body.decode("utf-8"))
            content = payload["response"]["content"]
            web_url = str(content["webUrl"])
            body_html = str(content["fields"]["body"])
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContentAcquisitionError(
                "invalid_provider_payload",
                "Guardian response does not contain a valid article body",
                retryable=False,
            ) from exc
        returned_host = urlsplit(web_url).hostname or ""
        if not _host_matches(returned_host, request.expected_domain):
            raise ContentAcquisitionError(
                "publisher_url_mismatch",
                "Guardian response URL does not match the requested publisher",
                retryable=False,
            )
        body_text, body_document = _html_to_valid_body(body_html, request)
        if request.policy.images.display != "omit":
            try:
                page_response = self._fetcher.get(
                    request.canonical_url,
                    expected_domain=request.expected_domain,
                    accepted_content_types=frozenset({"text/html"}),
                )
                page_html = page_response.body.decode("utf-8")
                enriched_text, enriched_document = _html_to_valid_body(page_html, request)
                if any(block.type == "image" for block in enriched_document.blocks):
                    body_text = enriched_text
                    body_document = enriched_document
            except (ContentAcquisitionError, UnicodeDecodeError):
                pass
        main_image_ids = {
            _image_identity(str(asset["file"]))
            for element in content.get("elements", [])
            if element.get("type") == "image" and element.get("relation") == "main"
            for asset in element.get("assets", [])
            if asset.get("file")
        }
        if request.lead_image_url:
            main_image_ids.add(_image_identity(request.lead_image_url))
        if main_image_ids:
            filtered_blocks = [
                block
                for block in body_document.blocks
                if not (
                    isinstance(block, ImageBlock)
                    and _image_identity(block.source_url) in main_image_ids
                )
            ]
            body_document = body_document.model_copy(update={"blocks": filtered_blocks})
            body_text = validate_body(derive_body_text(body_document), language=request.language)
        return AcquiredContent(
            source="guardian_api",
            body_text=body_text,
            fetched_at=self._clock(),
            extraction_version=EXTRACTION_VERSION,
            body_document=body_document,
        )


class RssContentProvider:
    def __init__(
        self,
        fetcher: SafeFetcher,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._fetcher = fetcher
        self._clock = clock

    def acquire(self, request: ContentRequest) -> AcquiredContent:
        expected_url = canonicalize_url(request.canonical_url)
        for feed_url in request.policy.feed_urls:
            feed_host = urlsplit(feed_url).hostname or ""
            response = self._fetcher.get(
                feed_url,
                expected_domain=feed_host,
                accepted_content_types=frozenset(
                    {"application/rss+xml", "application/xml", "text/xml"}
                ),
            )
            try:
                root = ElementTree.fromstring(response.body)
            except ElementTree.ParseError as exc:
                raise ContentAcquisitionError(
                    "invalid_provider_payload", "RSS feed is not valid XML", retryable=True
                ) from exc
            for item in root.findall(".//item"):
                link = (item.findtext("link") or "").strip()
                try:
                    matches = canonicalize_url(link) == expected_url
                except ValueError:
                    matches = False
                if not matches:
                    continue
                content = item.findtext(CONTENT_ENCODED) or item.findtext("description") or ""
                body_text, body_document = _html_to_valid_body(content, request)
                return AcquiredContent(
                    source="rss",
                    body_text=body_text,
                    fetched_at=self._clock(),
                    extraction_version=EXTRACTION_VERSION,
                    body_document=body_document,
                )
        raise ContentAcquisitionError(
            "rss_item_missing", "article is not present in configured feeds", retryable=True
        )


class HtmlContentProvider:
    def __init__(
        self,
        fetcher: SafeFetcher,
        *,
        clock: Callable[[], datetime] = _utc_now,
        local_research_allowed: bool = False,
    ) -> None:
        self._fetcher = fetcher
        self._clock = clock
        self._local_research_allowed = local_research_allowed

    def acquire(self, request: ContentRequest) -> AcquiredContent:
        is_local_research = request.policy.access_scope == "local_research"
        if is_local_research and not self._local_research_allowed:
            raise ContentAcquisitionError(
                "local_research_disabled",
                "local research full text is disabled in this runtime",
                retryable=False,
            )
        fetch_policy = (
            FetchPolicy.local_research_http()
            if request.policy.allow_insecure_http and is_local_research
            else None
        )
        response = self._fetcher.get(
            request.canonical_url,
            expected_domain=request.expected_domain,
            accepted_content_types=frozenset({"text/html"}),
            fetch_policy=fetch_policy,
        )
        html = decode_html(response.body, response.content_type)
        lowered = html.casefold()
        if any(marker in lowered for marker in PAYWALL_MARKERS):
            raise ContentAcquisitionError(
                "paywall_or_login", "publisher page requires subscription or login", retryable=False
            )
        adapter = get_html_adapter(request.policy.adapter)
        document_html = html
        extraction_version = EXTRACTION_VERSION
        if adapter is not None:
            if not _page_title_matches(html, request.title):
                raise ContentAcquisitionError(
                    "extraction_quality_failed",
                    "publisher page title does not match the stored article title",
                    retryable=False,
                )
            if adapter.extraction_version != request.policy.target_extraction_version:
                raise ContentAcquisitionError(
                    "unsupported_template",
                    "configured extraction version does not match the HTML adapter",
                    retryable=False,
                )
            prepared = adapter.prepare(html, base_url=request.canonical_url)
            document_html = lxml_html.tostring(prepared, encoding="unicode")
            extraction_version = adapter.extraction_version
        try:
            body_text, body_document = _html_to_valid_body(document_html, request)
        except ContentAcquisitionError as exc:
            if adapter is not None and exc.code == "extraction_too_short":
                raise ContentAcquisitionError(
                    "extraction_quality_failed",
                    "article body does not meet local research quality thresholds",
                    retryable=False,
                ) from exc
            raise
        if adapter is not None:
            body_document = body_document.model_copy(
                update={"extraction_version": extraction_version}
            )
            text_block_count = sum(block.type != "image" for block in body_document.blocks)
            if len(body_text) < 300 or text_block_count < 3:
                raise ContentAcquisitionError(
                    "extraction_quality_failed",
                    "article body does not meet local research quality thresholds",
                    retryable=False,
                )
        return AcquiredContent(
            source="html",
            body_text=body_text,
            fetched_at=self._clock(),
            extraction_version=extraction_version,
            body_document=body_document,
        )
