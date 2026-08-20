from __future__ import annotations

import pytest

from backend.app import config
from backend.app.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_live_news_settings_have_safe_defaults(monkeypatch) -> None:
    monkeypatch.setattr(config, "_DOTENV_VALUES", {}, raising=False)
    for key in (
        "NEWSREC_LIVE_NEWS_ENABLED",
        "NEWSREC_LIVE_NEWS_COLLECTOR_ENABLED",
        "NEWSREC_LIVE_NEWS_SOURCE_CONFIG",
        "NEWSREC_LIVE_NEWS_POLL_INTERVAL_SECONDS",
        "NEWSREC_LIVE_NEWS_REPLAY_MINUTES",
        "NEWSREC_LIVE_NEWS_MAX_AGE_HOURS",
        "NEWSREC_LIVE_NEWS_COLLECTOR_METRICS_PORT",
    ):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.live_news_enabled is False
    assert settings.live_news_collector_enabled is False
    assert settings.live_news_source_config == "config/live_news_sources.json"
    assert settings.live_news_poll_interval_seconds == 60
    assert settings.live_news_replay_minutes == 60
    assert settings.live_news_max_age_hours == 72
    assert settings.live_news_collector_metrics_port == 9103


def test_live_news_settings_read_environment(monkeypatch) -> None:
    monkeypatch.setenv("NEWSREC_LIVE_NEWS_ENABLED", "1")
    monkeypatch.setenv("NEWSREC_LIVE_NEWS_COLLECTOR_ENABLED", "1")
    monkeypatch.setenv("NEWSREC_LIVE_NEWS_SOURCE_CONFIG", "custom/sources.json")
    monkeypatch.setenv("NEWSREC_LIVE_NEWS_POLL_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("NEWSREC_LIVE_NEWS_REPLAY_MINUTES", "90")
    monkeypatch.setenv("NEWSREC_LIVE_NEWS_MAX_AGE_HOURS", "48")
    monkeypatch.setenv("NEWSREC_LIVE_NEWS_COLLECTOR_METRICS_PORT", "9203")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.live_news_enabled is True
    assert settings.live_news_collector_enabled is True
    assert settings.live_news_source_config == "custom/sources.json"
    assert settings.live_news_poll_interval_seconds == 30
    assert settings.live_news_replay_minutes == 90
    assert settings.live_news_max_age_hours == 48
    assert settings.live_news_collector_metrics_port == 9203


def test_live_content_settings_have_safe_defaults(monkeypatch) -> None:
    monkeypatch.setattr(config, "_DOTENV_VALUES", {}, raising=False)
    for key in (
        "NEWSREC_LIVE_CONTENT_WORKER_ENABLED",
        "NEWSREC_GUARDIAN_API_KEY",
        "NEWSREC_LIVE_CONTENT_CONNECT_TIMEOUT_SECONDS",
        "NEWSREC_LIVE_CONTENT_READ_TIMEOUT_SECONDS",
        "NEWSREC_LIVE_CONTENT_MAX_RESPONSE_BYTES",
        "NEWSREC_LIVE_CONTENT_WORKER_BATCH_SIZE",
        "NEWSREC_LIVE_CONTENT_WORKER_CONCURRENCY",
    ):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.live_content_worker_enabled is False
    assert settings.guardian_api_key == ""
    assert settings.live_content_connect_timeout_seconds == 5
    assert settings.live_content_read_timeout_seconds == 15
    assert settings.live_content_max_response_bytes == 2 * 1024 * 1024
    assert settings.live_content_worker_batch_size == 20
    assert settings.live_content_worker_concurrency == 4


def test_live_content_settings_read_environment(monkeypatch) -> None:
    monkeypatch.setenv("NEWSREC_LIVE_CONTENT_WORKER_ENABLED", "1")
    monkeypatch.setenv("NEWSREC_GUARDIAN_API_KEY", "guardian-test-key")
    monkeypatch.setenv("NEWSREC_LIVE_CONTENT_CONNECT_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("NEWSREC_LIVE_CONTENT_READ_TIMEOUT_SECONDS", "21")
    monkeypatch.setenv("NEWSREC_LIVE_CONTENT_MAX_RESPONSE_BYTES", "4096")
    monkeypatch.setenv("NEWSREC_LIVE_CONTENT_WORKER_BATCH_SIZE", "8")
    monkeypatch.setenv("NEWSREC_LIVE_CONTENT_WORKER_CONCURRENCY", "2")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.live_content_worker_enabled is True
    assert settings.guardian_api_key == "guardian-test-key"
    assert settings.live_content_connect_timeout_seconds == 7
    assert settings.live_content_read_timeout_seconds == 21
    assert settings.live_content_max_response_bytes == 4096
    assert settings.live_content_worker_batch_size == 8
    assert settings.live_content_worker_concurrency == 2
