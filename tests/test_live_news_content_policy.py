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
