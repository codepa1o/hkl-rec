from __future__ import annotations

import pytest

from backend.app.config import Settings
from backend.app.live_news.content_fetch import FetchResponse
from backend.app.live_news.content_policy import ContentPolicy
from backend.app.live_news.content_types import ContentAcquisitionError, ContentRequest
from scripts.run_live_news_content_worker import build_provider_registry, parse_args


class FakeFetcher:
    def get(self, *_args, **_kwargs) -> FetchResponse:
        paragraph = "本地研究模式下的虚构中文正文，用于验证正文适配器注册。" * 10
        body = (
            "<html><body><div id='detail'>"
            f"<p>{paragraph}</p><p>{paragraph}</p><p>{paragraph}</p>"
            "</div></body></html>"
        ).encode()
        return FetchResponse("http://www.xinhuanet.com/story.html", 200, "text/html", body, None)


def test_parse_args_supports_one_shot_mode() -> None:
    args = parse_args(["--once", "--poll-interval-seconds", "3"])

    assert args.once is True
    assert args.poll_interval_seconds == 3.0


def test_provider_registry_exposes_html_and_rss_without_credentials() -> None:
    registry = build_provider_registry(Settings(), FakeFetcher())

    assert registry.for_mode("html") is not None
    assert registry.for_mode("rss") is not None
    with pytest.raises(ContentAcquisitionError) as raised:
        registry.for_mode("guardian_api")
    assert raised.value.code == "provider_unavailable"


def test_provider_registry_enables_guardian_when_key_is_configured() -> None:
    registry = build_provider_registry(
        Settings(guardian_api_key="guardian-test-key"),
        FakeFetcher(),
    )

    assert registry.for_mode("guardian_api") is not None


def test_provider_registry_keeps_local_research_disabled_outside_gate() -> None:
    registry = build_provider_registry(
        Settings(environment="production", local_research_fulltext_enabled=True),
        FakeFetcher(),
    )
    request = ContentRequest(
        article_id="L0123456789abcdef0123456789abcdef",
        canonical_url="http://www.xinhuanet.com/story.html",
        expected_domain="xinhuanet.com",
        language="zh",
        policy=ContentPolicy(
            "html",
            "full_text",
            access_scope="local_research",
            adapter="xinhuanet",
            target_extraction_version="zh-xinhua-1",
            allow_insecure_http=True,
        ),
    )

    with pytest.raises(ContentAcquisitionError) as raised:
        registry.for_mode("html").acquire(request)

    assert raised.value.code == "local_research_disabled"


def test_provider_registry_enables_local_research_only_in_development() -> None:
    registry = build_provider_registry(
        Settings(environment="development", local_research_fulltext_enabled=True),
        FakeFetcher(),
    )
    request = ContentRequest(
        article_id="L0123456789abcdef0123456789abcdef",
        canonical_url="http://www.xinhuanet.com/story.html",
        expected_domain="xinhuanet.com",
        language="zh",
        policy=ContentPolicy(
            "html",
            "full_text",
            access_scope="local_research",
            adapter="xinhuanet",
            target_extraction_version="zh-xinhua-1",
            allow_insecure_http=True,
        ),
    )

    result = registry.for_mode("html").acquire(request)

    assert result.extraction_version == "zh-xinhua-1"
