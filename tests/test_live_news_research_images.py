from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.dependencies import get_app_settings
from backend.app.live_news.content_document import ImageBlock
from backend.app.live_news.content_parser import parse_structured_document
from backend.app.live_news.html_adapters import XINHUA_ADAPTER
from backend.app.routers.articles import router

ARTICLE = "L" + "1" * 32
ASSET = "a" * 32
PATH = f"/articles/live/{ARTICLE}/assets/{ASSET}"
URL = "http://www.fj.xinhuanet.com/a.png"


def test_research_image_contract_keeps_http_only_with_internal_display():
    block = ImageBlock(
        id="img-test",
        asset_id=ASSET,
        source_url=URL,
        display_url=PATH,
        access_scope="local_research",
        cache_status="remote_only",
    )
    assert block.source_url == URL
    for changes in (
        {"access_scope": "public"},
        {"display_url": URL},
        {"display_url": "//evil.test/a"},
        {"display_url": "/api/../secret"},
        {"source_url": "http://user:password@www.fj.xinhuanet.com/a.png"},
    ):
        with pytest.raises(ValidationError):
            ImageBlock.model_validate({**block.model_dump(), **changes})


def test_research_parser_requires_explicit_opt_in_and_preserves_http():
    from lxml import html

    root = XINHUA_ADAPTER.prepare(
        '<div id="detail"><p><img src="a.png"></p><p>正文</p></div>',
        base_url="http://www.fj.xinhuanet.com/story",
        allow_http_images=True,
    )
    assert root.xpath(".//img/@src") == [URL]
    args = dict(
        article_id=ARTICLE,
        source="html",
        base_url=URL,
        allowed_image_domains=frozenset({"xinhuanet.com"}),
    )
    markup = html.tostring(root, encoding="unicode")
    assert [b.type for b in parse_structured_document(markup, **args).blocks] == ["paragraph"]
    doc = parse_structured_document(markup, **args, allow_research_http_images=True)
    assert doc.blocks[0].source_url == URL
    assert doc.blocks[0].display_url.startswith(f"/articles/live/{ARTICLE}/assets/")


@pytest.mark.parametrize(
    "settings",
    [
        Settings(environment="production", local_research_fulltext_enabled=True),
        Settings(environment="development", local_research_fulltext_enabled=False),
    ],
)
def test_asset_route_denies_when_research_gate_closed(settings):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_app_settings] = lambda: settings
    with TestClient(app) as client:
        assert client.get(PATH).status_code == 404


def test_image_bytes_are_identified_independently_of_extension():
    from io import BytesIO

    from PIL import Image

    from backend.app.live_news import research_images

    stream = BytesIO()
    Image.new("RGB", (2, 2)).save(stream, format="PNG")
    assert research_images.image_media_type(stream.getvalue()) == "image/png"
    for body in (b"<html>error</html>", b"<svg></svg>", b"\x89PNG\r\n\x1a\n"):
        with pytest.raises(ValueError):
            research_images.image_media_type(body)


def test_asset_policy_checks_scope_domain_and_current_document():
    from backend.app.live_news import research_images
    from backend.app.live_news.allowlist import load_allowlist

    policy = load_allowlist(Path("config/live_news_sources.json"))
    block = dict(
        id="img-test",
        type="image",
        asset_id=ASSET,
        source_url=URL,
        display_url=PATH,
        access_scope="local_research",
        cache_status="remote_only",
    )
    row = dict(
        article_id=ARTICLE,
        source_domain="www.fj.xinhuanet.com",
        body_access_scope="local_research",
        content_rights="full_text",
        status="active",
        body_structure_status="available",
        body_document_version="zh-xinhua-2",
        body_document=dict(
            schema_version=1, extraction_version="zh-xinhua-2", source="html", blocks=[block]
        ),
        source_url=URL,
        asset_id=ASSET,
        block_id="img-test",
    )
    assert research_images.validate_asset(row, policy).allow_insecure_http
    for changes in (
        {"source_url": "http://evil.test/a.png"},
        {"body_access_scope": "public"},
        {"asset_id": "b" * 32},
        {"content_rights": "link_only"},
        {"status": "inactive"},
        {"block_id": "other"},
        {"body_structure_status": "blocked"},
    ):
        with pytest.raises(LookupError):
            research_images.validate_asset({**row, **changes}, policy)


def test_asset_route_returns_verified_image_and_controlled_failure():
    from backend.app.live_news import research_images
    from backend.app.live_news.content_types import ContentAcquisitionError

    settings = Settings(environment="development", local_research_fulltext_enabled=True)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_app_settings] = lambda: settings
    with patch.object(research_images, "load_research_image", return_value=(b"image", "image/png")):
        with TestClient(app) as client:
            response = client.get(PATH)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "private" in response.headers["cache-control"]
    with patch.object(
        research_images,
        "load_research_image",
        side_effect=ContentAcquisitionError("network_error", "internal detail", retryable=True),
    ):
        with TestClient(app) as client:
            response = client.get(PATH)
        assert response.status_code == 502
        assert "internal detail" not in response.text


def test_image_transport_pins_public_ip_and_preserves_hostname(monkeypatch):
    from urllib.request import Request

    from backend.app.live_news import research_images
    from backend.app.live_news.content_types import ContentAcquisitionError

    calls = []
    monkeypatch.setattr(
        research_images.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 80))]
    )
    transport = research_images.ImageTransport()
    with pytest.raises(ContentAcquisitionError, match="global"):
        transport(Request(URL), timeout=5)
    monkeypatch.setattr(
        research_images.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )
    monkeypatch.setattr(
        research_images.socket,
        "create_connection",
        lambda address, **kwargs: calls.append(address) or (_ for _ in ()).throw(TimeoutError()),
    )
    with pytest.raises(TimeoutError):
        transport(Request(URL), timeout=5)
    assert calls == [("93.184.216.34", 80)]
