from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.app.live_news.allowlist import SourceAllowlist
from backend.app.live_news.types import LiveNewsArticle, RejectedGalRecord, RejectionReason

TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    }
)
AGGREGATION_SEGMENTS = frozenset(
    {"tag", "tags", "topic", "topics", "category", "categories", "series"}
)
INVALID_TITLE_PATTERN = re.compile(r"^(404|page\s+expired|not\s+found|access\s+denied)\b", re.I)


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).replace("\ufffd", "")
    return " ".join(text.split())


def canonicalize_url(value: object) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    if scheme not in {"http", "https"} or not host:
        raise ValueError("article URL must use HTTP(S) and contain a host")
    port = parsed.port
    netloc = host if port is None else f"{host}:{port}"
    path = parsed.path or "/"
    retained = sorted(
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
    )
    return urlunsplit((scheme, netloc, path, urlencode(retained), ""))


def live_article_id(canonical_url: str) -> str:
    return "L" + hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:32]


def content_hash(title: str, summary: str) -> str:
    normalized = f"{normalize_text(title)}\n{normalize_text(summary)}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _parse_gdelt_date(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _invalid_article_path(path: str) -> bool:
    segments = {segment.lower() for segment in path.split("/") if segment}
    return bool(segments & AGGREGATION_SEGMENTS)


def classify_gal_record(
    raw: dict[str, Any],
    *,
    discovered_at: datetime,
    allowlist: SourceAllowlist,
    max_age: timedelta = timedelta(hours=72),
    future_tolerance: timedelta = timedelta(minutes=30),
) -> LiveNewsArticle | RejectedGalRecord:
    try:
        canonical_url = canonicalize_url(raw.get("url"))
        parsed_url = urlsplit(canonical_url)
    except (TypeError, ValueError) as exc:
        return RejectedGalRecord("invalid_metadata", dict(raw), str(exc))
    policy = allowlist.match(parsed_url.hostname or "")
    if policy is None:
        return RejectedGalRecord("domain_not_allowed", dict(raw))
    language = str(raw.get("lang") or "").strip().lower()
    if language not in {"zh", "en"} or language not in policy.languages:
        return RejectedGalRecord("unsupported_language", dict(raw))
    title = normalize_text(raw.get("title"))
    if not title:
        return RejectedGalRecord("missing_title", dict(raw))
    if INVALID_TITLE_PATTERN.search(title) or _invalid_article_path(parsed_url.path):
        return RejectedGalRecord("invalid_page", dict(raw))
    try:
        published_at = _parse_gdelt_date(raw.get("date"))
    except ValueError as exc:
        return RejectedGalRecord("invalid_metadata", dict(raw), str(exc))
    if published_at is not None and (
        published_at < discovered_at - max_age or published_at > discovered_at + future_tolerance
    ):
        return RejectedGalRecord("stale_article", dict(raw))
    summary = normalize_text(raw.get("desc"))
    image_url = normalize_text(raw.get("image")) or None
    publisher = normalize_text(raw.get("outletName")) or policy.domain
    author = normalize_text(raw.get("author")) or None
    return LiveNewsArticle(
        article_id=live_article_id(canonical_url),
        canonical_url=canonical_url,
        source_external_id=canonical_url,
        title=title,
        summary=summary,
        image_url=image_url,
        publisher=publisher,
        source_domain=parsed_url.hostname or policy.domain,
        language=cast(Literal["zh", "en"], language),
        author=author,
        published_at=published_at,
        published_at_quality="gdelt_unverified" if published_at else "unknown",
        discovered_at=discovered_at.astimezone(UTC),
        fetched_at=discovered_at.astimezone(UTC),
        content_hash=content_hash(title, summary),
        publisher_quality=policy.quality_weight,
        raw_metadata=dict(raw),
    )


def _normalized_title(value: str) -> str:
    return "".join(
        character for character in normalize_text(value).casefold() if character.isalnum()
    )


def _trigrams(value: str) -> set[str]:
    normalized = _normalized_title(value)
    if len(normalized) < 3:
        return {normalized} if normalized else set()
    return {normalized[index : index + 3] for index in range(len(normalized) - 2)}


def title_trigram_jaccard(first: str, second: str) -> float:
    left = _trigrams(first)
    right = _trigrams(second)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _quality_key(article: LiveNewsArticle) -> tuple[float, int, float]:
    completeness = int(bool(article.summary)) + int(bool(article.image_url))
    return (article.publisher_quality, completeness, -article.discovered_at.timestamp())


def deduplicate_articles(
    articles: list[LiveNewsArticle],
) -> tuple[list[LiveNewsArticle], list[RejectedGalRecord]]:
    kept: list[LiveNewsArticle] = []
    rejected: list[RejectedGalRecord] = []
    for article in articles:
        duplicate_index: int | None = None
        reason: RejectionReason = "duplicate_content"
        for index, current in enumerate(kept):
            if article.canonical_url == current.canonical_url:
                duplicate_index = index
                reason = "duplicate_url"
                break
            if article.content_hash == current.content_hash or (
                abs((article.discovered_at - current.discovered_at).total_seconds()) <= 86_400
                and title_trigram_jaccard(article.title, current.title) >= 0.92
            ):
                duplicate_index = index
                break
        if duplicate_index is None:
            kept.append(article)
            continue
        current = kept[duplicate_index]
        if _quality_key(article) > _quality_key(current):
            kept[duplicate_index] = article
            rejected.append(RejectedGalRecord(reason, current.raw_metadata))
        else:
            rejected.append(RejectedGalRecord(reason, article.raw_metadata))
    kept.sort(key=lambda item: (item.discovered_at, item.article_id))
    return kept, rejected
