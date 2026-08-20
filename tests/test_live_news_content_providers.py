from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from backend.app.live_news.content_fetch import FetchResponse
from backend.app.live_news.content_policy import ContentPolicy
from backend.app.live_news.content_providers import (
    GuardianContentProvider,
    HtmlContentProvider,
    RssContentProvider,
)
from backend.app.live_news.content_types import ContentAcquisitionError, ContentRequest

NOW = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
LONG_ENGLISH = " ".join(
    ["This is a complete publisher paragraph with reliable news article content."] * 12
)


class FakeFetcher:
    def __init__(self, *responses: FetchResponse) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, frozenset[str] | None]] = []

    def get(
        self,
        url: str,
        *,
        expected_domain: str,
        accepted_content_types: frozenset[str] | None = None,
        headers=None,
    ) -> FetchResponse:
        self.calls.append((url, expected_domain, accepted_content_types))
        return self.responses.pop(0)


def _response(body: bytes, content_type: str, url: str) -> FetchResponse:
    return FetchResponse(url, 200, content_type, body, None)


def _request(
    *,
    url: str = "https://www.theguardian.com/world/2026/aug/18/example-story",
    domain: str = "theguardian.com",
    policy: ContentPolicy | None = None,
) -> ContentRequest:
    return ContentRequest(
        article_id="L0123456789abcdef0123456789abcdef",
        canonical_url=url,
        expected_domain=domain,
        language="en",
        policy=policy or ContentPolicy("guardian_api", "full_text"),
    )


def test_guardian_provider_extracts_fields_body() -> None:
    payload = {
        "response": {
            "status": "ok",
            "content": {
                "webUrl": "https://www.theguardian.com/world/2026/aug/18/example-story",
                "fields": {"body": f"<p>{LONG_ENGLISH}</p>"},
            },
        }
    }
    fetcher = FakeFetcher(
        _response(
            json.dumps(payload).encode(), "application/json", "https://content.guardianapis.com/x"
        )
    )

    result = GuardianContentProvider(fetcher, "api-key", clock=lambda: NOW).acquire(_request())

    assert result.source == "guardian_api"
    assert result.body_text == LONG_ENGLISH
    assert result.fetched_at == NOW
    assert fetcher.calls[0][1] == "content.guardianapis.com"
    assert "api-key=api-key" in fetcher.calls[0][0]


def test_guardian_provider_rejects_returned_url_mismatch() -> None:
    payload = {
        "response": {
            "status": "ok",
            "content": {
                "webUrl": "https://evil.test/world/story",
                "fields": {"body": f"<p>{LONG_ENGLISH}</p>"},
            },
        }
    }
    fetcher = FakeFetcher(
        _response(
            json.dumps(payload).encode(), "application/json", "https://content.guardianapis.com/x"
        )
    )

    with pytest.raises(ContentAcquisitionError) as raised:
        GuardianContentProvider(fetcher, "api-key", clock=lambda: NOW).acquire(_request())

    assert raised.value.code == "publisher_url_mismatch"


def test_rss_provider_prefers_content_encoded_and_matches_canonical_url() -> None:
    rss = f"""<?xml version="1.0"?>
    <rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item>
      <link>https://example.com/story?utm_source=feed</link>
      <description><![CDATA[<p>Short description only.</p>]]></description>
      <content:encoded><![CDATA[<p>{LONG_ENGLISH}</p>]]></content:encoded>
    </item></channel></rss>""".encode()
    feed_url = "https://example.com/feed.xml"
    fetcher = FakeFetcher(_response(rss, "application/rss+xml", feed_url))
    request = _request(
        url="https://example.com/story",
        domain="example.com",
        policy=ContentPolicy("rss", "full_text", (feed_url,)),
    )

    result = RssContentProvider(fetcher, clock=lambda: NOW).acquire(request)

    assert result.source == "rss"
    assert result.body_text == LONG_ENGLISH
    assert "Short description" not in result.body_text


def test_rss_provider_reports_missing_item_as_retryable() -> None:
    rss = b"<rss><channel></channel></rss>"
    feed_url = "https://example.com/feed.xml"
    fetcher = FakeFetcher(_response(rss, "application/rss+xml", feed_url))
    request = _request(
        url="https://example.com/story",
        domain="example.com",
        policy=ContentPolicy("rss", "full_text", (feed_url,)),
    )

    with pytest.raises(ContentAcquisitionError) as raised:
        RssContentProvider(fetcher, clock=lambda: NOW).acquire(request)

    assert raised.value.code == "rss_item_missing"
    assert raised.value.retryable is True


def test_html_provider_extracts_article_and_drops_comments() -> None:
    html = f"""<html><body><nav>Navigation</nav><article><p>{LONG_ENGLISH}</p></article>
    <section class="comments">Reader comment should not appear.</section></body></html>""".encode()
    fetcher = FakeFetcher(_response(html, "text/html", "https://example.com/story"))
    request = _request(
        url="https://example.com/story",
        domain="example.com",
        policy=ContentPolicy("html", "full_text"),
    )

    result = HtmlContentProvider(fetcher, clock=lambda: NOW).acquire(request)

    assert result.source == "html"
    assert LONG_ENGLISH in result.body_text
    assert "Reader comment" not in result.body_text
    assert "Navigation" not in result.body_text


def test_html_provider_blocks_paywall_marker() -> None:
    html = f"<html><body><article><p>{LONG_ENGLISH}</p><p>Subscribe to continue</p></article></body></html>"
    fetcher = FakeFetcher(_response(html.encode(), "text/html", "https://example.com/story"))
    request = _request(
        url="https://example.com/story",
        domain="example.com",
        policy=ContentPolicy("html", "full_text"),
    )

    with pytest.raises(ContentAcquisitionError) as raised:
        HtmlContentProvider(fetcher, clock=lambda: NOW).acquire(request)

    assert raised.value.code == "paywall_or_login"
    assert raised.value.retryable is False
