from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.live_news.allowlist import load_allowlist


def _write_sources(path: Path, content: dict[str, object] | None) -> None:
    source: dict[str, object] = {
        "domain": "example.com",
        "languages": ["en"],
        "quality_weight": 0.8,
    }
    if content is not None:
        source["content"] = content
    path.write_text(json.dumps({"sources": [source]}), encoding="utf-8")


def test_allowlist_defaults_to_link_only_content_policy(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    _write_sources(path, None)

    policy = load_allowlist(path).match("news.example.com")

    assert policy is not None
    assert policy.content.mode == "link_only"
    assert policy.content.display == "link_only"
    assert policy.content.feed_urls == ()


def test_allowlist_parses_guardian_content_policy(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    _write_sources(
        path,
        {
            "mode": "guardian_api",
            "display": "full_text",
            "feed_urls": [],
            "images": {
                "display": "remote_url",
                "cache": "when_authorized",
                "allowed_domains": ["i.guim.co.uk"],
                "max_images_per_article": 20,
                "max_bytes_per_image": 8_388_608,
            },
        },
    )

    policy = load_allowlist(path).match("example.com")

    assert policy is not None
    assert policy.content.mode == "guardian_api"
    assert policy.content.display == "full_text"
    assert policy.content.images.display == "remote_url"
    assert policy.content.images.cache == "when_authorized"
    assert policy.content.images.allowed_domains == ("i.guim.co.uk",)


def test_allowlist_parses_local_research_html_policy(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    _write_sources(
        path,
        {
            "mode": "html",
            "display": "full_text",
            "access_scope": "local_research",
            "adapter": "xinhuanet",
            "target_extraction_version": "zh-xinhua-1",
            "allow_insecure_http": True,
            "feed_urls": [],
        },
    )

    policy = load_allowlist(path).match("news.example.com")

    assert policy is not None
    assert policy.content.access_scope == "local_research"
    assert policy.content.adapter == "xinhuanet"
    assert policy.content.target_extraction_version == "zh-xinhua-1"
    assert policy.content.allow_insecure_http is True


@pytest.mark.parametrize(
    "content",
    [
        {"mode": "rss", "display": "full_text", "feed_urls": []},
        {
            "mode": "rss",
            "display": "full_text",
            "feed_urls": ["http://example.com/feed.xml"],
        },
        {"mode": "link_only", "display": "full_text", "feed_urls": []},
        {"mode": "browser", "display": "full_text", "feed_urls": []},
        {"mode": "html", "display": "unknown", "feed_urls": []},
        {
            "mode": "html",
            "display": "full_text",
            "feed_urls": [],
            "images": {"display": "remote_url", "allowed_domains": []},
        },
        {
            "mode": "html",
            "display": "full_text",
            "access_scope": "public",
            "adapter": "xinhuanet",
            "target_extraction_version": "zh-xinhua-1",
            "allow_insecure_http": True,
        },
        {
            "mode": "guardian_api",
            "display": "full_text",
            "adapter": "xinhuanet",
        },
    ],
)
def test_allowlist_rejects_invalid_content_policy(
    tmp_path: Path,
    content: dict[str, object],
) -> None:
    path = tmp_path / "sources.json"
    _write_sources(path, content)

    with pytest.raises(ValueError):
        load_allowlist(path)


def test_project_allowlist_configures_chinese_local_research_sources() -> None:
    allowlist = load_allowlist(Path("config/live_news_sources.json"))

    expected = {
        "xinhuanet.com": ("xinhuanet", "zh-xinhua-1", True),
        "people.com.cn": ("people", "zh-people-1", True),
        "chinanews.com.cn": ("chinanews", "zh-chinanews-1", True),
    }
    for domain, (adapter, version, allow_http) in expected.items():
        source = allowlist.match(f"www.{domain}")
        assert source is not None
        assert source.content.mode == "html"
        assert source.content.display == "full_text"
        assert source.content.access_scope == "local_research"
        assert source.content.adapter == adapter
        assert source.content.target_extraction_version == version
        assert source.content.allow_insecure_http is allow_http

    thepaper = allowlist.match("www.thepaper.cn")
    assert thepaper is not None
    assert thepaper.content.mode == "link_only"
