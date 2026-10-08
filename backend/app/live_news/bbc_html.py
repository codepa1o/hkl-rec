"""BBC News module-based HTML extraction for explicitly enabled local research."""

from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from datetime import UTC, datetime
from difflib import SequenceMatcher
from threading import Lock
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from lxml import html as lxml_html
from lxml.etree import ParserError, XMLSyntaxError
from pydantic import ValidationError

from .content_decode import decode_html
from .content_document import PublisherTag
from .content_fetch import SafeFetcher
from .content_normalize import validate_body
from .content_parser import derive_body_text, parse_structured_document
from .content_types import AcquiredContent, ContentAcquisitionError, ContentRequest
from .html_adapters import _normalize_srcset, _normalize_url

BBC_VERSION = "bbc-html-2"
BODY_MODULES = {
    "text-block",
    "image-block",
    "subheadline-block",
    "heading-block",
    "quote-block",
    "list-block",
    "layout-block",
}
SKIP_MODULES = {
    "headline-block",
    "byline-block",
    "links-block",
    "tag-list-block",
    "ad-slot",
    "advertisement-block",
}


def _error(code: str, detail: str) -> ContentAcquisitionError:
    return ContentAcquisitionError(code, detail, retryable=False)


def _bbc_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        return (
            p.scheme == "https"
            and p.hostname in {"bbc.com", "www.bbc.com"}
            and not p.username
            and not p.password
            and p.port in {None, 443}
        )
    except ValueError:
        return False


def _title(value: str) -> str:
    return "".join(c.casefold() for c in value if c.isalnum())


class BbcHtmlProvider:
    def __init__(self, fetcher: SafeFetcher, *, local_research_allowed: bool):
        self._fetcher = fetcher
        self._allowed = local_research_allowed
        self._robots: dict[str, tuple[float, RobotFileParser]] = {}
        self._lock = Lock()
        self._last_fetch = 0.0

    def acquire(self, request: ContentRequest) -> AcquiredContent:
        if not self._allowed or request.policy.access_scope != "local_research":
            raise _error(
                "local_research_disabled", "BBC HTML requires local research mode and scope"
            )
        if request.policy.target_extraction_version != BBC_VERSION:
            raise _error("unsupported_template", "BBC extraction version is not supported")
        url = request.canonical_url
        if not _bbc_url(url) or not re.fullmatch(r"/news/articles/[a-z0-9]+", urlsplit(url).path):
            raise _error("invalid_url", "Only BBC.com News article URLs are supported")
        origin = f"https://{urlsplit(url).hostname}"
        with self._lock:
            cached = self._robots.get(origin)
            if cached is None or time.monotonic() - cached[0] > 3600:
                response = self._fetcher.get(
                    origin + "/robots.txt",
                    expected_domain="bbc.com",
                    accepted_content_types=frozenset({"text/plain"}),
                )
                rules = RobotFileParser()
                rules.parse(response.body.decode("utf-8", errors="replace").splitlines())
                self._robots[origin] = (time.monotonic(), rules)
            else:
                rules = cached[1]
            if not rules.can_fetch("hkl-rec-live-content", url):
                raise _error("publisher_blocked", "BBC robots.txt disallows article acquisition")
            delay = max(1, rules.crawl_delay("hkl-rec-live-content") or 0)
            if delay > 60:
                raise _error("publisher_blocked", "BBC crawl delay exceeds the worker budget")
            remaining = delay - (time.monotonic() - self._last_fetch)
            if remaining > 0:
                time.sleep(remaining)
            self._last_fetch = time.monotonic()
            response = self._fetcher.get(
                url, expected_domain="bbc.com", accepted_content_types=frozenset({"text/html"})
            )
        try:
            document = lxml_html.fromstring(decode_html(response.body, response.content_type))
        except (ParserError, XMLSyntaxError, ValueError) as exc:
            raise _error("unsupported_template", "BBC returned empty or invalid HTML") from exc
        canonicals = document.xpath('//link[@rel="canonical"]/@href')
        paths = {urlsplit(u).path.rstrip("/") for u in canonicals if _bbc_url(u)}
        if (
            not canonicals
            or any(not _bbc_url(u) for u in canonicals)
            or paths != {urlsplit(url).path}
            or not _bbc_url(response.final_url)
            or urlsplit(response.final_url).path != urlsplit(url).path
        ):
            raise _error(
                "publisher_url_mismatch",
                "BBC canonical or final URL does not match the requested article",
            )
        articles = document.xpath('//main[@id="bbc-main"]//article[not(ancestor::article)]')
        if len(articles) != 1:
            raise _error("unsupported_template", "A unique BBC News article was not found")
        article = articles[0]
        titles = article.xpath(".//h1")
        expected_title = _title(request.title)
        document_titles = document.xpath("//head/title/text()")
        exact_document_title = (
            len(document_titles) == 1 and _title(document_titles[0]) == expected_title
        )
        if (
            not expected_title
            or len(titles) != 1
            or not _title(titles[0].text_content())
            or (
                SequenceMatcher(None, expected_title, _title(titles[0].text_content())).ratio()
                < 0.8
                and not exact_document_title
            )
        ):
            raise _error("extraction_quality_failed", "BBC title does not match the stored article")
        metadata = []
        for raw in document.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                value = json.loads(raw)
                entries = value if isinstance(value, list) else [value]
                for entry in entries:
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
        if str(article_meta.get("isAccessibleForFree", "true")).lower() == "false" or article.xpath(
            './/*[@data-testid="paywall"]'
        ):
            raise _error("paywall_or_login", "BBC article requires restricted access")
        clean = lxml_html.Element("article")
        warnings = []
        modules = article.xpath(".//*[@data-component]")
        count = 0
        for module in modules:
            if any(a is not article and a.get("data-component") for a in module.iterancestors()):
                continue
            name = module.get("data-component")
            if name in SKIP_MODULES:
                continue
            if name not in BODY_MODULES:
                warnings.append("原文包含暂不支持的媒体或交互模块，请通过“阅读原文”查看。")
                continue
            if (
                name == "image-block"
                and request.lead_image_url
                and module.xpath('.//*[@data-testid="hero-image"]')
            ):
                continue
            node = deepcopy(module)
            for nested in node.xpath(".//*[@data-component]"):
                nested_name = nested.get("data-component")
                if nested_name not in BODY_MODULES and nested.getparent() is not None:
                    if nested_name not in SKIP_MODULES:
                        warnings.append("原文包含暂不支持的媒体或交互模块，请通过“阅读原文”查看。")
                    nested.drop_tree()
            for unwanted in node.xpath(
                './/aside|.//nav|.//footer|.//script|.//noscript|.//*[@hidden]|.//*[@data-testid="links-grid"]'
            ):
                if unwanted.getparent() is not None:
                    unwanted.drop_tree()
            if name == "image-block":
                # BBC wraps images/captions in divs and includes a non-content placeholder img.
                node.tag = "figure"
                for media in node.xpath(".//img|.//source"):
                    valid = False
                    for attribute in ("src", "data-src", "srcset", "data-srcset"):
                        value = media.get(attribute)
                        if not value:
                            continue
                        normalizer = _normalize_srcset if "srcset" in attribute else _normalize_url
                        try:
                            normalized = normalizer(
                                value, url, request.policy.images.allowed_domains
                            )
                        except ValueError:
                            normalized = None
                        if normalized:
                            media.set(attribute, normalized)
                            valid = True
                        else:
                            media.attrib.pop(attribute, None)
                    if not valid:
                        media.drop_tree()
            unsupported = node.xpath(".//table|.//iframe|.//video")
            if unsupported:
                warnings.append("原文包含暂不支持的表格或视频，请通过“阅读原文”查看。")
                for element in unsupported:
                    if element.getparent() is not None:
                        element.drop_tree()
            clean.append(node)
            count += 1
        if not count:
            raise _error("unsupported_template", "BBC article has no supported body modules")
        try:
            doc = parse_structured_document(
                lxml_html.tostring(clean, encoding="unicode"),
                article_id=request.article_id,
                source="html",
                base_url=url,
                allowed_image_domains=frozenset(request.policy.images.allowed_domains)
                if request.policy.images.display != "omit"
                else frozenset(),
                max_images=request.policy.images.max_images_per_article
                if request.policy.images.display != "omit"
                else 0,
            )
        except (ValueError, ParserError, XMLSyntaxError) as exc:
            raise _error(
                "extraction_quality_failed", "BBC body did not produce valid structured blocks"
            ) from exc
        if sum(b.type == "paragraph" for b in doc.blocks) < 2:
            raise _error("extraction_quality_failed", "Insufficient BBC article paragraphs")
        tags = []
        seen = set()
        for link in article.xpath('.//*[@data-component="tag-list-block"]//a[@href]'):
            try:
                href = urljoin(url, link.get("href"))
            except ValueError:
                continue
            if not _bbc_url(href) or href in seen:
                continue
            try:
                tag = PublisherTag(name=" ".join(link.text_content().split()), url=href)
            except ValidationError:
                continue
            tags.append(tag)
            seen.add(href)
        bylines = article.xpath('.//*[@data-testid="byline-contributors"]')
        byline = " ".join(bylines[0].text_content().split())[:1000] if len(bylines) == 1 else None
        dates = article.xpath('.//*[@data-component="byline-block"]//time/@datetime')
        try:
            published = datetime.fromisoformat(
                str(dates[0] if dates else article_meta.get("datePublished", "")).replace(
                    "Z", "+00:00"
                )
            )
            if published.tzinfo is None:
                published = None
        except ValueError:
            published = None
        doc = doc.model_copy(
            update={
                "extraction_version": BBC_VERSION,
                "html_adapter_version": BBC_VERSION,
                "publisher_tags": tags[:50],
                "byline": byline,
                "published_at": published,
                "warnings": list(dict.fromkeys(warnings))[:10],
            }
        )
        body = validate_body(derive_body_text(doc), language=request.language)
        return AcquiredContent(
            "html", body, datetime.now(UTC), BBC_VERSION, doc, access_scope="local_research"
        )
