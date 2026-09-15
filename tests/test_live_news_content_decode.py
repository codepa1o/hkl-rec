from __future__ import annotations

import pytest

from backend.app.live_news.content_decode import decode_html
from backend.app.live_news.content_types import ContentAcquisitionError


def test_content_type_utf8_decodes_html() -> None:
    body = "<p>中文正文</p>".encode()

    assert "中文正文" in decode_html(body, "text/html; charset=utf-8")


def test_meta_charset_is_used_when_header_has_no_charset() -> None:
    body = '<meta charset="utf-8"><p>中文正文</p>'.encode()

    assert "中文正文" in decode_html(body, "text/html")


def test_meta_gb2312_uses_gb18030_decoder() -> None:
    body = '<meta charset="gb2312"><p>中文正文</p>'.encode("gb18030")

    assert "中文正文" in decode_html(body, "text/html")


def test_content_type_charset_wins_over_conflicting_meta() -> None:
    body = '<meta charset="gb2312"><p>中文正文</p>'.encode()

    assert "中文正文" in decode_html(body, "text/html; charset=utf-8")


def test_unknown_encoding_fails_closed() -> None:
    with pytest.raises(ContentAcquisitionError) as raised:
        decode_html(b"\x81", "text/html; charset=unknown-x")

    assert raised.value.code == "encoding_unsupported"
