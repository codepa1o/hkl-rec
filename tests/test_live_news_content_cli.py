from __future__ import annotations

import pytest

from backend.app.config import Settings
from backend.app.live_news.content_types import ContentAcquisitionError
from scripts.run_live_news_content_worker import build_provider_registry, parse_args


class FakeFetcher:
    pass


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
