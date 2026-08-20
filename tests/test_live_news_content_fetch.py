from __future__ import annotations

from email.message import Message
from io import BytesIO
from typing import Any

import pytest

from backend.app.live_news.content_fetch import SafeFetcher
from backend.app.live_news.content_types import ContentAcquisitionError


class FakeResponse:
    def __init__(
        self,
        status: int,
        body: bytes = b"",
        *,
        content_type: str = "text/html; charset=utf-8",
        location: str | None = None,
        retry_after: str | None = None,
    ) -> None:
        self.status = status
        self._body = BytesIO(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if location is not None:
            self.headers["Location"] = location
        if retry_after is not None:
            self.headers["Retry-After"] = retry_after

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def close(self) -> None:
        return None


class FakeTransport:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        return self.responses.pop(0)


def public_resolver(_host: str) -> tuple[str, ...]:
    return ("93.184.216.34",)


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"],
)
def test_fetcher_rejects_non_global_addresses(address: str) -> None:
    fetcher = SafeFetcher(
        transport=FakeTransport(FakeResponse(200, b"article")),
        resolver=lambda _host: (address,),
    )

    with pytest.raises(ContentAcquisitionError) as raised:
        fetcher.get("https://example.com/article", expected_domain="example.com")

    assert raised.value.code == "unsafe_address"


def test_fetcher_revalidates_each_same_domain_redirect() -> None:
    transport = FakeTransport(
        FakeResponse(302, location="https://www.example.com/final"),
        FakeResponse(200, b"article body"),
    )
    resolved: list[str] = []

    def resolver(host: str) -> tuple[str, ...]:
        resolved.append(host)
        return public_resolver(host)

    response = SafeFetcher(transport=transport, resolver=resolver).get(
        "https://example.com/start",
        expected_domain="example.com",
    )

    assert response.final_url == "https://www.example.com/final"
    assert resolved == ["example.com", "www.example.com"]


def test_fetcher_rejects_cross_domain_redirect() -> None:
    transport = FakeTransport(FakeResponse(302, location="https://evil.test/final"))

    with pytest.raises(ContentAcquisitionError) as raised:
        SafeFetcher(transport=transport, resolver=public_resolver).get(
            "https://example.com/start",
            expected_domain="example.com",
        )

    assert raised.value.code == "invalid_redirect"
    assert len(transport.requests) == 1


def test_fetcher_rejects_response_larger_than_limit() -> None:
    fetcher = SafeFetcher(
        transport=FakeTransport(FakeResponse(200, b"x" * 33)),
        resolver=public_resolver,
        max_response_bytes=32,
    )

    with pytest.raises(ContentAcquisitionError) as raised:
        fetcher.get("https://example.com/article", expected_domain="example.com")

    assert raised.value.code == "response_too_large"


def test_fetcher_rejects_unsupported_content_type() -> None:
    fetcher = SafeFetcher(
        transport=FakeTransport(FakeResponse(200, b"{}", content_type="application/octet-stream")),
        resolver=public_resolver,
    )

    with pytest.raises(ContentAcquisitionError) as raised:
        fetcher.get(
            "https://example.com/article",
            expected_domain="example.com",
            accepted_content_types=frozenset({"text/html"}),
        )

    assert raised.value.code == "unsupported_content_type"


def test_fetcher_classifies_rate_limit_as_retryable() -> None:
    fetcher = SafeFetcher(
        transport=FakeTransport(FakeResponse(429, retry_after="120")),
        resolver=public_resolver,
    )

    with pytest.raises(ContentAcquisitionError) as raised:
        fetcher.get("https://example.com/article", expected_domain="example.com")

    assert raised.value.code == "http_429"
    assert raised.value.retryable is True
    assert raised.value.retry_after == "120"


def test_fetcher_classifies_forbidden_article_as_authentication_required() -> None:
    fetcher = SafeFetcher(
        transport=FakeTransport(FakeResponse(403)),
        resolver=public_resolver,
    )

    with pytest.raises(ContentAcquisitionError) as raised:
        fetcher.get("https://example.com/article", expected_domain="example.com")

    assert raised.value.code == "authentication_required"
    assert raised.value.retryable is False
