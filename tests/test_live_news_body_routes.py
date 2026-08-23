from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.config import Settings
from backend.app.live_news.allowlist import load_allowlist
from backend.app.news_spaces.live import LiveNewsSpaceRepository
from backend.app.schemas.article import ArticleCardResponse

ARTICLE_ID = "L0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)


class Cursor:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _sql: str, _params: tuple[Any, ...]) -> None:
        return None

    def fetchone(self) -> dict[str, Any]:
        return self.row


class Connection:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def cursor(self) -> Cursor:
        return Cursor(self.row)

    def close(self) -> None:
        return None


class Pool:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def connect(self) -> Connection:
        return Connection(self.row)


def _row(**changes: Any) -> dict[str, Any]:
    value = {
        "article_id": ARTICLE_ID,
        "title": "Live body fixture",
        "summary": "Stored GDELT description",
        "canonical_url": "https://example.com/story",
        "source_domain": "example.com",
        "publisher": "Example",
        "language": "en",
        "published_at": NOW,
        "discovered_at": NOW,
        "image_url": None,
        "status": "active",
        "body_text": None,
        "body_status": "metadata_only",
        "body_source": None,
        "content_rights": "link_only",
        "body_document": None,
        "body_document_version": None,
        "body_structure_status": "missing",
    }
    value.update(changes)
    return value


def _repository(tmp_path: Path, row: dict[str, Any]) -> LiveNewsSpaceRepository:
    config = tmp_path / "sources.json"
    config.write_text(
        '{"sources":[{"domain":"example.com","languages":["en"],"quality_weight":0.8}]}',
        encoding="utf-8",
    )
    return LiveNewsSpaceRepository(
        Pool(row),  # type: ignore[arg-type]
        Settings(),
        load_allowlist(config),
    )


def test_full_text_article_returns_available_body(tmp_path: Path) -> None:
    body = "First paragraph.\n\nSecond paragraph."

    article = _repository(
        tmp_path,
        _row(
            body_text=body,
            body_status="available",
            body_source="html",
            content_rights="full_text",
        ),
    ).get_article(ARTICLE_ID)

    assert article.body_text == body
    assert article.body_status == "available"
    assert article.body_source == "html"
    assert article.content_rights == "full_text"


def test_full_text_article_returns_valid_structured_document(tmp_path: Path) -> None:
    document = {
        "schema_version": 1,
        "extraction_version": "structured-1",
        "source": "html",
        "blocks": [
            {"id": "p-1", "type": "paragraph", "text": "First paragraph."},
            {
                "id": "img-2",
                "type": "image",
                "asset_id": "asset-2",
                "source_url": "https://images.example.com/photo.jpg",
                "display_url": "https://images.example.com/photo.jpg",
                "alt": "Photo",
                "caption": "Caption",
                "credit": "Photograph: Example",
                "width": 1200,
                "height": 800,
                "mime_type": "image/jpeg",
                "cache_status": "remote_only",
            },
        ],
    }

    article = _repository(
        tmp_path,
        _row(
            body_text="First paragraph.",
            body_status="available",
            body_source="html",
            content_rights="full_text",
            body_document=document,
            body_document_version="structured-1",
            body_structure_status="available",
        ),
    ).get_article(ARTICLE_ID)

    assert article.body_document is not None
    assert [block.type for block in article.body_document.blocks] == ["paragraph", "image"]
    assert article.body_structure_status == "available"
    assert article.body_document_version == "structured-1"


def test_corrupt_structured_document_falls_back_to_plain_text(tmp_path: Path) -> None:
    article = _repository(
        tmp_path,
        _row(
            body_text="Readable fallback.",
            body_status="available",
            body_source="html",
            content_rights="full_text",
            body_document={"schema_version": 999, "blocks": []},
            body_document_version="unknown",
            body_structure_status="available",
        ),
    ).get_article(ARTICLE_ID)

    assert article.body_document is None
    assert article.body_text == "Readable fallback."


def test_excerpt_only_article_never_returns_more_than_1000_characters(tmp_path: Path) -> None:
    article = _repository(
        tmp_path,
        _row(
            body_text="a" * 1500,
            body_status="available",
            body_source="rss",
            content_rights="excerpt_only",
        ),
    ).get_article(ARTICLE_ID)

    assert article.body_text is not None
    assert len(article.body_text) == 1000


def test_link_only_article_suppresses_stored_body(tmp_path: Path) -> None:
    article = _repository(
        tmp_path,
        _row(
            body_text="internal text",
            body_status="available",
            body_source="html",
            content_rights="link_only",
        ),
    ).get_article(ARTICLE_ID)

    assert article.body_text is None
    assert article.content_rights == "link_only"


def test_pending_article_returns_summary_without_network(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network request")),
    )

    article = _repository(
        tmp_path,
        _row(body_status="pending", content_rights="full_text"),
    ).get_article(ARTICLE_ID)

    assert article.body_text is None
    assert article.abstract == "Stored GDELT description"
    assert article.body_status == "pending"


def test_mind_article_response_defaults_to_metadata_only_body_contract() -> None:
    article = ArticleCardResponse(
        source_space="mind",
        article_id="N1",
        title="MIND article",
        abstract="Abstract",
        url="https://example.com",
        source_domain="example.com",
        category="news",
        subcategory="local",
        categories=[],
        title_entities=[],
        abstract_entities=[],
    )

    assert article.body_text is None
    assert article.body_status == "metadata_only"
    assert article.body_source is None
    assert article.content_rights == "link_only"
