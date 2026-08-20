from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast
from urllib.parse import urlsplit

ContentMode = Literal["guardian_api", "rss", "html", "link_only"]
ContentRights = Literal["full_text", "excerpt_only", "link_only"]

CONTENT_MODES = frozenset({"guardian_api", "rss", "html", "link_only"})
CONTENT_RIGHTS = frozenset({"full_text", "excerpt_only", "link_only"})


@dataclass(frozen=True)
class ContentPolicy:
    mode: ContentMode
    display: ContentRights
    feed_urls: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode == "rss" and not self.feed_urls:
            raise ValueError("rss content mode requires feed_urls")
        for url in self.feed_urls:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError("content feed URLs must use HTTPS")
        if self.mode == "link_only" and self.display != "link_only":
            raise ValueError("link_only content mode requires link_only display")


LINK_ONLY_CONTENT_POLICY = ContentPolicy(mode="link_only", display="link_only")


def parse_content_policy(raw: object) -> ContentPolicy:
    if raw is None:
        return LINK_ONLY_CONTENT_POLICY
    if not isinstance(raw, dict):
        raise ValueError("source content policy must be an object")
    mode = str(raw.get("mode") or "").strip()
    display = str(raw.get("display") or "").strip()
    raw_feed_urls = raw.get("feed_urls", [])
    if mode not in CONTENT_MODES:
        raise ValueError(f"unsupported content mode: {mode!r}")
    if display not in CONTENT_RIGHTS:
        raise ValueError(f"unsupported content display policy: {display!r}")
    if not isinstance(raw_feed_urls, list) or any(
        not isinstance(value, str) or not value.strip() for value in raw_feed_urls
    ):
        raise ValueError("content feed_urls must be a list of non-empty strings")
    return ContentPolicy(
        mode=cast(ContentMode, mode),
        display=cast(ContentRights, display),
        feed_urls=tuple(value.strip() for value in raw_feed_urls),
    )
