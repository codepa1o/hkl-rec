from __future__ import annotations

import pytest

from backend.app.config import get_settings
from backend.app.live_news.content_fetch import SafeFetcher
from backend.app.live_news.content_policy import ContentPolicy, ImagePolicy
from backend.app.live_news.content_providers import GuardianContentProvider
from backend.app.live_news.content_types import ContentRequest

SETTINGS = get_settings()


@pytest.mark.skipif(not SETTINGS.guardian_api_key, reason="NEWSREC_GUARDIAN_API_KEY is not set")
def test_guardian_single_item_returns_real_structured_lloyds_article() -> None:
    provider = GuardianContentProvider(
        SafeFetcher(
            connect_timeout_seconds=SETTINGS.live_content_connect_timeout_seconds,
            read_timeout_seconds=SETTINGS.live_content_read_timeout_seconds,
            max_response_bytes=SETTINGS.live_content_max_response_bytes,
        ),
        SETTINGS.guardian_api_key,
    )
    request = ContentRequest(
        article_id="L8c9744585e25ce284d0afe62c422577e",
        canonical_url=(
            "https://www.theguardian.com/artanddesign/2026/aug/18/"
            "lloyds-building-hi-tech-inside-out-open-house-parthenon"
        ),
        expected_domain="theguardian.com",
        language="en",
        policy=ContentPolicy(
            mode="guardian_api",
            display="full_text",
            images=ImagePolicy(
                display="remote_url",
                cache="never",
                allowed_domains=("i.guim.co.uk",),
            ),
        ),
    )

    result = provider.acquire(request)

    assert result.body_document is not None
    assert sum(block.type == "paragraph" for block in result.body_document.blocks) >= 10
    assert sum(block.type == "image" for block in result.body_document.blocks) >= 2
    assert len(result.body_text) >= 5_000
