from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.live_news.content_document import (
    HeadingBlock,
    ImageBlock,
    ParagraphBlock,
    QuoteBlock,
    StructuredBodyDocument,
)


def test_structured_document_round_trips_discriminated_blocks() -> None:
    document = StructuredBodyDocument(
        extraction_version="structured-1",
        source="guardian_api",
        blocks=[
            ParagraphBlock(id="p-001", text="First paragraph."),
            HeadingBlock(id="h-002", level=2, text="Inside the building"),
            QuoteBlock(id="q-003", text="A radical building.", attribution="Architect"),
            ImageBlock(
                id="img-004",
                asset_id="asset-004",
                source_url="https://i.guim.co.uk/photo.jpg",
                display_url="https://i.guim.co.uk/photo.jpg",
                alt="Trading floor",
                caption="The main trading floor",
                credit="Photograph: Example",
                width=1200,
                height=800,
                mime_type="image/jpeg",
                cache_status="remote_only",
            ),
        ],
    )

    restored = StructuredBodyDocument.model_validate(document.model_dump(mode="json"))

    assert restored.schema_version == 1
    assert [block.type for block in restored.blocks] == [
        "paragraph",
        "heading",
        "quote",
        "image",
    ]
    assert isinstance(restored.blocks[-1], ImageBlock)
    assert restored.blocks[-1].caption == "The main trading floor"


def test_structured_document_rejects_unknown_fields_and_invalid_image_urls() -> None:
    with pytest.raises(ValidationError):
        ParagraphBlock.model_validate(
            {"id": "p-1", "type": "paragraph", "text": "Text", "html": "<b>Text</b>"}
        )

    with pytest.raises(ValidationError):
        ImageBlock(
            id="img-1",
            asset_id="asset-1",
            source_url="javascript:alert(1)",
            display_url=None,
            alt=None,
            caption=None,
            credit=None,
            width=None,
            height=None,
            mime_type=None,
            cache_status="omitted",
        )


def test_structured_document_limits_heading_levels_and_empty_documents() -> None:
    with pytest.raises(ValidationError):
        HeadingBlock(id="h-1", level=1, text="Top-level heading")

    with pytest.raises(ValidationError):
        StructuredBodyDocument(
            extraction_version="structured-1",
            source="html",
            blocks=[],
        )
