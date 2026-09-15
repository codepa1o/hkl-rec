from __future__ import annotations

import codecs
import re

from backend.app.live_news.content_types import ContentAcquisitionError

_HEADER_CHARSET = re.compile(r"charset\s*=\s*['\"]?\s*([a-zA-Z0-9._-]+)", re.IGNORECASE)
_META_CHARSET = re.compile(
    r"<meta\b[^>]*\bcharset\s*=\s*['\"]?\s*([a-zA-Z0-9._-]+)",
    re.IGNORECASE,
)


def _normalized_charset(value: str) -> str | None:
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"gb2312", "gbk", "cp936"}:
        return "gb18030"
    if normalized == "utf8":
        return "utf-8"
    try:
        return codecs.lookup(normalized).name
    except LookupError:
        return None


def decode_html(body: bytes, content_type: str) -> str:
    candidates: list[str] = []
    header_match = _HEADER_CHARSET.search(content_type)
    if header_match:
        candidates.append(header_match.group(1))
    prefix = body[:4096].decode("ascii", errors="ignore")
    meta_match = _META_CHARSET.search(prefix)
    if meta_match:
        candidates.append(meta_match.group(1))
    candidates.extend(("utf-8", "gb18030"))

    attempted: set[str] = set()
    for candidate in candidates:
        encoding = _normalized_charset(candidate)
        if encoding is None or encoding in attempted:
            continue
        attempted.add(encoding)
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ContentAcquisitionError(
        "encoding_unsupported",
        "publisher HTML could not be decoded with an allowed charset",
        retryable=False,
    )
