"""Opt-in public HTML acquisition for local research, with no login or barrier bypass."""

from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from datetime import UTC, datetime
from difflib import SequenceMatcher
from threading import Lock
from typing import NoReturn
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from lxml import html as lxml_html  # type: ignore[import-untyped]
from lxml.etree import ParserError, XMLSyntaxError  # type: ignore[import-untyped]

from .content_decode import decode_html
from .content_document import PublisherTag
from .content_fetch import FetchResponse, SafeFetcher
from .content_normalize import validate_body
from .content_parser import derive_body_text, parse_structured_document, prose_segments
from .content_types import AcquiredContent, ContentAcquisitionError, ContentRequest
from .guardian_document import GUARDIAN_DOCUMENT_VERSION


def _fail(code: str, detail: str) -> NoReturn:
    raise ContentAcquisitionError(code, detail, retryable=False)


def _identity(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").removeprefix("www.")
    return host, parsed.path.rstrip("/")


def _title(value: str) -> str:
    return "".join(c.casefold() for c in value.split("|")[0] if c.isalnum())


def clean_guardian_interactive_markup(root: lxml_html.HtmlElement) -> None:
    """Remove rendering-only UI and caption clones within the selected article body."""

    def has_class(node: lxml_html.HtmlElement, name: str) -> bool:
        return name in (node.get("class") or "").split()

    for node in list(root.iterdescendants()):
        if node.getparent() is not None and (
            has_class(node, "scroll-tooltip")
            or (has_class(node, "caption-measurer") and node.get("aria-hidden") == "true")
        ):
            node.drop_tree()
    for sticky in list(root.iterdescendants()):
        if not has_class(sticky, "sticky-captions"):
            continue
        scope = next((a for a in sticky.iterancestors() if has_class(a, "horizontal")), None)
        if scope is None:
            continue
        captions = [
            " ".join(c.text_content().split()) for c in scope.xpath(".//figure//figcaption")
        ]
        for paragraph in sticky.xpath(".//p"):
            text = " ".join(paragraph.text_content().split())
            if text and any(c == text or c.startswith(text + " ") for c in captions):
                paragraph.drop_tree()


class GuardianHtmlProvider:
    def __init__(self, fetcher: SafeFetcher, *, local_research_allowed: bool):
        self._fetcher = fetcher
        self._allowed = local_research_allowed
        self._robots: dict[str, tuple[float, RobotFileParser]] = {}
        self._last_fetch = 0.0
        self._lock = Lock()

    def _fetch_page(self, request: ContentRequest) -> FetchResponse:
        parsed = urlsplit(request.canonical_url)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or _identity(request.canonical_url)[0] != "theguardian.com":
            _fail("invalid_url", "Only Guardian HTTPS article URLs are supported")
        origin = f"https://{host}"
        with self._lock:
            cached = self._robots.get(origin)
            if cached is None or time.monotonic() - cached[0] > 3600:
                response = self._fetcher.get(
                    origin + "/robots.txt",
                    expected_domain="theguardian.com",
                    accepted_content_types=frozenset({"text/plain"}),
                )
                rules = RobotFileParser()
                rules.parse(response.body.decode("utf-8", errors="replace").splitlines())
                self._robots[origin] = (time.monotonic(), rules)
            else:
                rules = cached[1]
            agent = "hkl-rec-live-content"
            if not rules.can_fetch(agent, request.canonical_url):
                _fail("publisher_blocked", "robots.txt disallows article acquisition")
            try:
                delay = max(1.0, float(rules.crawl_delay(agent) or 0))
            except (TypeError, ValueError):
                delay = 1.0
            if delay > 60:
                _fail("publisher_blocked", "Requested crawl delay exceeds local worker budget")
            remaining = delay - (time.monotonic() - self._last_fetch)
            if remaining > 0:
                time.sleep(remaining)
            self._last_fetch = time.monotonic()
            return self._fetcher.get(
                request.canonical_url,
                expected_domain="theguardian.com",
                accepted_content_types=frozenset({"text/html"}),
            )

    def acquire(self, request: ContentRequest) -> AcquiredContent:
        if not self._allowed:
            _fail("local_research_disabled", "HTML fallback requires local research mode")
        response = self._fetch_page(request)
        try:
            document = lxml_html.fromstring(decode_html(response.body, response.content_type))
        except (ParserError, XMLSyntaxError, ValueError):
            _fail("unsupported_template", "Publisher returned an empty or invalid HTML document")
        canonicals = document.xpath('//link[@rel="canonical"]/@href')
        if len(canonicals) != 1 or _identity(canonicals[0]) != _identity(response.final_url):
            _fail("publisher_url_mismatch", "Canonical article URL does not match fetched page")
        if re.search(r"/sudoku-\d+(?:-|$)", urlsplit(request.canonical_url).path):
            _fail(
                "unsupported_template",
                "Numbered puzzle pages require the original interactive view",
            )
        titles = document.xpath("//h1")
        expected = _title(request.title)
        if not expected or not any(
            SequenceMatcher(None, expected, _title(t.text_content())).ratio() >= 0.8 for t in titles
        ):
            _fail("extraction_quality_failed", "Page title does not match the requested article")
        metadata: list[dict[str, object]] = []
        for raw in document.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                value = json.loads(raw)
                values = value if isinstance(value, list) else [value]
                for entry in values:
                    if isinstance(entry, dict):
                        metadata.extend(
                            entry.get("@graph", [])
                            if isinstance(entry.get("@graph"), list)
                            else [entry]
                        )
            except ValueError:
                continue
        article_meta = next(
            (m for m in metadata if isinstance(m, dict) and "Article" in str(m.get("@type", ""))),
            {},
        )
        if str(article_meta.get("isAccessibleForFree", "true")).lower() == "false":
            _fail("paywall_or_login", "Page declares restricted article access")
        if document.xpath('//*[@id="paywall" or @data-component="paywall"]'):
            _fail("paywall_or_login", "Page presents an access gate")
        roots = document.xpath(
            '//*[contains(concat(" ",normalize-space(@class)," ")," article-body-commercial-selector ")]'
        )
        if len(roots) != 1:
            _fail("unsupported_template", "A unique Guardian article body container was not found")
        root = deepcopy(roots[0])
        clean_guardian_interactive_markup(root)
        for node in root.xpath(
            './/aside|.//nav|.//footer|.//*[@data-component="rich-link" or @data-component="newsletter-signup"]'
        ):
            if node.getparent() is not None:
                node.drop_tree()
        warnings = []
        unsupported = root.xpath(".//table|.//video|.//iframe")
        if unsupported:
            warnings.append("原文包含暂不支持的表格、视频或嵌入内容，请通过“阅读原文”查看。")
            for node in unsupported:
                if node.getparent() is not None:
                    node.drop_tree()
        raw = lxml_html.tostring(root, encoding="unicode")
        parsed_doc = parse_structured_document(
            raw,
            article_id=request.article_id,
            source="html",
            base_url=response.final_url,
            allowed_image_domains=frozenset(request.policy.images.allowed_domains)
            if request.policy.images.display != "omit"
            else frozenset(),
        )
        prose = prose_segments(parsed_doc)
        if len(prose) < 3 and sum(map(len, prose)) < 800:
            _fail("extraction_quality_failed", "Insufficient article prose")
        validate_body("\n\n".join(prose), language=request.language)
        tags = []
        seen = set()
        for heading in document.xpath(
            '//*[normalize-space(text())="Explore more on these topics"]'
        ):
            for parent in heading.iterancestors():
                links = parent.xpath(".//ul//a[@href]")
                if not links:
                    continue
                if len(links) > 50 or parent.tag in {"article", "body", "html"}:
                    break
                for link in links:
                    url = urljoin(response.final_url, link.get("href"))
                    if _identity(url)[0] != "theguardian.com" or url in seen:
                        continue
                    try:
                        tag = PublisherTag(name=" ".join(link.text_content().split()), url=url)
                    except ValueError:
                        continue
                    tags.append(tag)
                    seen.add(url)
                break
        authors = article_meta.get("author", [])
        if not isinstance(authors, list):
            authors = [authors]
        byline = (
            ", ".join(
                str(a.get("name", "")) if isinstance(a, dict) else str(a) for a in authors[:10]
            )[:1000]
            or None
        )
        visible_bylines = document.xpath('//*[@data-component="meta-byline"]')
        if len(visible_bylines) == 1:
            byline = " ".join(visible_bylines[0].text_content().split())[:1000] or byline
        published: datetime | None = None
        try:
            published = datetime.fromisoformat(
                str(article_meta.get("datePublished", "")).replace("Z", "+00:00")
            )
            if published.tzinfo is None:
                published = None
        except ValueError:
            published = None
        parsed_doc = parsed_doc.model_copy(
            update={
                "extraction_version": GUARDIAN_DOCUMENT_VERSION,
                "html_adapter_version": "guardian-html-2",
                "publisher_tags": tags[:50],
                "warnings": warnings,
                "byline": byline,
                "published_at": published,
            }
        )
        body = validate_body(derive_body_text(parsed_doc), language=request.language)
        return AcquiredContent(
            source="html",
            body_text=body,
            fetched_at=datetime.now(UTC),
            extraction_version="guardian-html-2",
            body_document=parsed_doc,
            access_scope="local_research",
        )
