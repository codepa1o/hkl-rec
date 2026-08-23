from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast
from urllib.parse import urlsplit

ContentMode = Literal["guardian_api", "rss", "html", "link_only"]
ContentRights = Literal["full_text", "excerpt_only", "link_only"]
ImageDisplay = Literal["remote_url", "cached_only", "omit"]
ImageCache = Literal["never", "when_authorized"]

CONTENT_MODES = frozenset({"guardian_api", "rss", "html", "link_only"})
CONTENT_RIGHTS = frozenset({"full_text", "excerpt_only", "link_only"})


@dataclass(frozen=True)
class ImagePolicy:
    display: ImageDisplay = "omit"
    cache: ImageCache = "never"
    allowed_domains: tuple[str, ...] = ()
    max_images_per_article: int = 20
    max_bytes_per_image: int = 8_388_608

    def __post_init__(self) -> None:
        if self.display != "omit" and not self.allowed_domains:
            raise ValueError("displayed content images require allowed_domains")
        if not 1 <= self.max_images_per_article <= 100:
            raise ValueError("max_images_per_article must be between 1 and 100")
        if not 1_024 <= self.max_bytes_per_image <= 50 * 1024 * 1024:
            raise ValueError("max_bytes_per_image is outside the supported range")
        for domain in self.allowed_domains:
            if not domain or "://" in domain or "/" in domain:
                raise ValueError("image allowed_domains must contain hostnames")


def parse_image_policy(raw: object) -> ImagePolicy:
    if raw is None:
        return ImagePolicy()
    if isinstance(raw, ImagePolicy):
        return raw
    if not isinstance(raw, dict):
        raise ValueError("content images policy must be an object")
    display = str(raw.get("display") or "omit")
    cache = str(raw.get("cache") or "never")
    domains = raw.get("allowed_domains", [])
    if display not in {"remote_url", "cached_only", "omit"}:
        raise ValueError(f"unsupported image display policy: {display!r}")
    if cache not in {"never", "when_authorized"}:
        raise ValueError(f"unsupported image cache policy: {cache!r}")
    if not isinstance(domains, list) or any(not isinstance(item, str) for item in domains):
        raise ValueError("image allowed_domains must be a list of hostnames")
    return ImagePolicy(
        display=cast(ImageDisplay, display),
        cache=cast(ImageCache, cache),
        allowed_domains=tuple(item.strip().lower().rstrip(".") for item in domains),
        max_images_per_article=int(raw.get("max_images_per_article", 20)),
        max_bytes_per_image=int(raw.get("max_bytes_per_image", 8_388_608)),
    )


@dataclass(frozen=True)
class ContentPolicy:
    mode: ContentMode
    display: ContentRights
    feed_urls: tuple[str, ...] = ()
    images: ImagePolicy = ImagePolicy()

    def __post_init__(self) -> None:
        object.__setattr__(self, "images", parse_image_policy(self.images))
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
        images=parse_image_policy(raw.get("images")),
    )
