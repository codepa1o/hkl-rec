from __future__ import annotations

import pytest

from backend.app.live_news.content_document import ImageBlock, ListBlock
from backend.app.live_news.content_parser import (
    derive_body_text,
    document_hash,
    parse_structured_document,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.xinhuanet.com:bad/a.png",
        "https://www.xinhuanet.com:8888/a.png",
        "https://user@www.xinhuanet.com/a.png",
    ],
)
def test_bad_image_url_does_not_discard_the_article(url):
    doc = parse_structured_document(
        f'<article><p>before<img src="{url}">after</p></article>',
        article_id="test",
        source="html",
        base_url="https://www.xinhuanet.com/story",
        allowed_image_domains=frozenset({"xinhuanet.com"}),
    )
    assert all(b.type == "paragraph" for b in doc.blocks)
    assert "before" in derive_body_text(doc) and "after" in derive_body_text(doc)


@pytest.mark.parametrize(
    "markup",
    [
        '<img src="https://www.xinhuanet.com/a.png">',
        '<p><img data-src="https://www.xinhuanet.com/a.png"></p>',
        '<p><span><img src="https://www.xinhuanet.com/a.png"></span></p>',
    ],
)
def test_parser_keeps_bare_and_nested_images(markup):
    doc = parse_structured_document(
        f"<article>{markup}<p>正文</p></article>",
        article_id="test-image",
        source="html",
        base_url="https://www.xinhuanet.com/story",
        allowed_image_domains=frozenset({"xinhuanet.com"}),
    )
    assert [b.type for b in doc.blocks] == ["image", "paragraph"]


def test_parser_keeps_mixed_paragraph_text_tails_and_multiple_images():
    doc = parse_structured_document(
        '<article><p>前文<span>加粗<img src="https://www.xinhuanet.com/a.png">后文</span>'
        '<picture><source srcset="https://www.xinhuanet.com/b.png 2x">'
        '<img src="https://www.xinhuanet.com/small.png"></picture>末尾</p></article>',
        article_id="test-image",
        source="html",
        base_url="https://www.xinhuanet.com/story",
        allowed_image_domains=frozenset({"xinhuanet.com"}),
    )
    assert [b.type for b in doc.blocks] == ["paragraph", "image", "paragraph", "image", "paragraph"]
    assert [b.text for b in doc.blocks if b.type == "paragraph"] == ["前文加粗", "后文", "末尾"]
    assert doc.blocks[3].source_url.endswith("/b.png")


def test_parser_limits_images_without_losing_surrounding_text():
    doc = parse_structured_document(
        '<article><p>before<img src="https://www.xinhuanet.com/a.png">'
        'between<img src="https://www.xinhuanet.com/b.png">after</p></article>',
        article_id="test",
        source="html",
        base_url="https://www.xinhuanet.com/story",
        allowed_image_domains=frozenset({"xinhuanet.com"}),
        max_images=1,
    )
    assert sum(b.type == "image" for b in doc.blocks) == 1
    assert all(word in derive_body_text(doc) for word in ["before", "between", "after"])


HTML = """
<html><body>
  <nav><p>Navigation should disappear.</p></nav>
  <article>
    <p>First paragraph about the building.</p>
    <p>Second paragraph remains separate.</p>
    <blockquote><p>The Adam Room was moved.</p><cite>Historian</cite></blockquote>
    <p>Text before the trading floor image.</p>
    <figure>
      <picture>
        <source srcset="https://i.guim.co.uk/trading-640.jpg 640w, https://i.guim.co.uk/trading-1280.jpg 1280w">
        <img src="https://i.guim.co.uk/trading.jpg" alt="Main trading floor" width="1280" height="800">
      </picture>
      <figcaption>Main trading floor. <span class="credit">Photograph: Example</span></figcaption>
    </figure>
    <h2>Inside-out architecture</h2>
    <p>Text between the two photographs.</p>
    <figure>
      <img data-src="https://i.guim.co.uk/adam-room.jpg" alt="Adam Room">
      <figcaption>The Adam Room</figcaption>
    </figure>
    <ol><li>First feature</li><li>Second feature</li></ol>
    <aside><p>Related stories should disappear.</p></aside>
  </article>
</body></html>
"""


def test_parser_preserves_text_image_and_quote_order() -> None:
    document = parse_structured_document(
        HTML,
        article_id="L8c9744585e25ce284d0afe62c422577e",
        source="guardian_api",
        base_url="https://www.theguardian.com/example",
        allowed_image_domains=frozenset({"i.guim.co.uk"}),
    )

    assert [block.type for block in document.blocks] == [
        "paragraph",
        "paragraph",
        "quote",
        "paragraph",
        "image",
        "heading",
        "paragraph",
        "image",
        "list",
    ]
    first_image = document.blocks[4]
    assert isinstance(first_image, ImageBlock)
    assert first_image.source_url == "https://i.guim.co.uk/trading-1280.jpg"
    assert first_image.alt == "Main trading floor"
    assert first_image.caption == "Main trading floor. Photograph: Example"
    assert first_image.credit == "Photograph: Example"
    assert (first_image.width, first_image.height) == (1280, 800)
    assert isinstance(document.blocks[-1], ListBlock)
    assert document.blocks[-1].ordered is True
    assert document.blocks[-1].items == ["First feature", "Second feature"]


def test_parser_removes_noise_and_derives_searchable_plain_text() -> None:
    document = parse_structured_document(
        HTML,
        article_id="L8c9744585e25ce284d0afe62c422577e",
        source="html",
        base_url="https://www.theguardian.com/example",
        allowed_image_domains=frozenset({"i.guim.co.uk"}),
    )

    body_text = derive_body_text(document)

    assert "First paragraph" in body_text
    assert "Second paragraph" in body_text
    assert "Main trading floor" in body_text
    assert "Navigation" not in body_text
    assert "Related stories" not in body_text
    assert body_text.count("\n\n") >= 6


def test_parser_is_deterministic_and_drops_unsafe_images() -> None:
    unsafe = HTML.replace(
        "https://i.guim.co.uk/adam-room.jpg",
        "https://tracking.invalid/adam-room.jpg",
    )
    first = parse_structured_document(
        unsafe,
        article_id="L8c9744585e25ce284d0afe62c422577e",
        source="html",
        base_url="https://www.theguardian.com/example",
        allowed_image_domains=frozenset({"i.guim.co.uk"}),
    )
    second = parse_structured_document(
        unsafe,
        article_id="L8c9744585e25ce284d0afe62c422577e",
        source="html",
        base_url="https://www.theguardian.com/example",
        allowed_image_domains=frozenset({"i.guim.co.uk"}),
    )

    assert first == second
    assert document_hash(first) == document_hash(second)
    assert sum(block.type == "image" for block in first.blocks) == 1


def test_same_image_url_gets_article_scoped_asset_ids() -> None:
    first = parse_structured_document(
        HTML,
        article_id="L11111111111111111111111111111111",
        source="html",
        base_url="https://www.theguardian.com/first",
        allowed_image_domains=frozenset({"i.guim.co.uk"}),
    )
    second = parse_structured_document(
        HTML,
        article_id="L22222222222222222222222222222222",
        source="html",
        base_url="https://www.theguardian.com/second",
        allowed_image_domains=frozenset({"i.guim.co.uk"}),
    )

    first_ids = [block.asset_id for block in first.blocks if isinstance(block, ImageBlock)]
    second_ids = [block.asset_id for block in second.blocks if isinstance(block, ImageBlock)]
    assert first_ids
    assert second_ids
    assert set(first_ids).isdisjoint(second_ids)
