from __future__ import annotations

import hashlib

import pytest

from backend.app.live_news.content_normalize import body_hash, normalize_body, validate_body
from backend.app.live_news.content_types import ContentAcquisitionError


def test_normalize_body_preserves_paragraphs_and_removes_controls() -> None:
    value = normalize_body("  First   paragraph.\r\n\r\nSecond\x00 paragraph.  ")

    assert value == "First paragraph.\n\nSecond paragraph."


def test_normalize_body_collapses_excess_blank_lines() -> None:
    value = normalize_body("First.\n\n\n\nSecond.")

    assert value == "First.\n\nSecond."


def test_body_hash_uses_normalized_text() -> None:
    expected = hashlib.sha256(b"First paragraph.").hexdigest()

    assert body_hash(" First   paragraph. ") == expected


def test_validate_body_rejects_too_short() -> None:
    with pytest.raises(ContentAcquisitionError) as raised:
        validate_body("short", language="en")

    assert raised.value.code == "extraction_too_short"
    assert raised.value.retryable is False


def test_validate_body_rejects_wrong_language() -> None:
    english = " ".join(["This article contains only English words and sentences."] * 20)

    with pytest.raises(ContentAcquisitionError) as raised:
        validate_body(english, language="zh")

    assert raised.value.code == "language_mismatch"


def test_validate_body_accepts_chinese_article() -> None:
    chinese = "这是用于测试的中文新闻正文，包含多个完整段落和足够多的文字。" * 20

    assert validate_body(chinese, language="zh") == normalize_body(chinese)
