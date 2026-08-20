from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Literal

from backend.app.live_news.content_types import ContentAcquisitionError

MIN_BODY_CHARACTERS = 300
MAX_BODY_CHARACTERS = 200_000


def _clean_controls(value: str) -> str:
    result: list[str] = []
    for character in value:
        if character in {"\n", "\t"} or not unicodedata.category(character).startswith("C"):
            result.append(character)
    return "".join(result)


def normalize_body(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = _clean_controls(normalized).replace("\t", " ")
    paragraphs = re.split(r"\n\s*\n+", normalized)
    cleaned = [
        re.sub(r"\s+", " ", paragraph).strip() for paragraph in paragraphs if paragraph.strip()
    ]
    return "\n\n".join(cleaned)


def body_hash(value: str) -> str:
    return hashlib.sha256(normalize_body(value).encode("utf-8")).hexdigest()


def _language_is_compatible(value: str, language: Literal["zh", "en"]) -> bool:
    cjk_count = sum("\u3400" <= character <= "\u9fff" for character in value)
    latin_count = sum(character.isascii() and character.isalpha() for character in value)
    if language == "zh":
        return cjk_count >= 20
    return latin_count >= 50 and cjk_count <= max(20, latin_count // 2)


def validate_body(value: str, *, language: Literal["zh", "en"]) -> str:
    normalized = normalize_body(value)
    if len(normalized) < MIN_BODY_CHARACTERS:
        raise ContentAcquisitionError(
            "extraction_too_short",
            f"body contains {len(normalized)} characters",
            retryable=False,
        )
    if len(normalized) > MAX_BODY_CHARACTERS:
        raise ContentAcquisitionError(
            "extraction_too_long",
            f"body contains {len(normalized)} characters",
            retryable=False,
        )
    if not _language_is_compatible(normalized, language):
        raise ContentAcquisitionError(
            "language_mismatch",
            f"body is incompatible with language {language}",
            retryable=False,
        )
    return normalized
