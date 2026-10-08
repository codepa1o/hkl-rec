import pytest

from backend.app.live_news.content_fetch import FetchResponse
from backend.app.live_news.content_policy import ContentPolicy
from backend.app.live_news.content_providers import HtmlContentProvider
from backend.app.live_news.content_types import ContentAcquisitionError, ContentRequest

URL = "https://www.bbc.com/news/articles/cwg7ky12g14jo"
TITLE = "Turkey arrests dozens in crackdown on LGBTQ+ activists"
TEXT = (
    "A complete article paragraph about the reported events and the background of the story. " * 8
)
HTML = f'''<html><head><link rel="canonical" href="{URL}"><link rel="canonical" href="{URL}"></head>
<body><main id="bbc-main"><article><div data-component="headline-block"><h1>{TITLE}</h1></div>
<div data-component="byline-block"><div data-testid="byline-contributors">Test Reporter</div><time datetime="2026-09-15T14:00:00Z"></time></div>
<div data-component="image-block"><figure data-testid="hero-image"><img src="https://ichef.bbci.co.uk/lead.jpg"></figure></div>
<div data-component="text-block"><p>{TEXT}</p><h2>Background</h2></div>
<div data-component="image-block"><figure><img src="https://ichef.bbci.co.uk/body.jpg"><figcaption>Picture caption</figcaption></figure></div>
<div data-component="text-block"><blockquote>Quoted statement.</blockquote><p>{TEXT}</p><ul><li>Real list item</li></ul></div>
<div data-component="links-block"><p>Unrelated recommended story.</p></div>
<div data-component="tag-list-block"><a href="/news/topics/topic-one">Topic one</a></div>
</article><footer><p>Footer navigation</p></footer></main></body></html>'''


class Fetcher:
    def __init__(self, page=HTML, robots="User-agent: *\nAllow: /"):
        self.page = page
        self.robots = robots
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        is_robots = url.endswith("/robots.txt")
        return FetchResponse(
            url,
            200,
            "text/plain" if is_robots else "text/html",
            (self.robots if is_robots else self.page).encode(),
            None,
        )


def request():
    return ContentRequest(
        article_id="L" + "b" * 32,
        canonical_url=URL,
        expected_domain="bbc.com",
        language="en",
        title=TITLE,
        lead_image_url="https://ichef.bbci.co.uk/lead.jpg",
        policy=ContentPolicy(
            "html",
            "full_text",
            access_scope="local_research",
            adapter="bbc",
            target_extraction_version="bbc-html-2",
            images={"display": "remote_url", "allowed_domains": ["ichef.bbci.co.uk"]},
        ),
    )


def test_bbc_article_module_order_and_noise_separation():
    result = HtmlContentProvider(Fetcher(), local_research_allowed=True).acquire(request())
    doc = result.body_document
    assert result.access_scope == "local_research"
    assert result.extraction_version == "bbc-html-2"
    assert [b.type for b in doc.blocks] == [
        "paragraph",
        "heading",
        "image",
        "quote",
        "paragraph",
        "list",
    ]
    assert doc.byline == "Test Reporter"
    assert doc.publisher_tags[0].name == "Topic one"
    assert (
        "recommended" not in result.body_text
        and "Footer" not in result.body_text
        and "Topic one" not in result.body_text
    )
    assert doc.blocks[2].caption == "Picture caption"


def test_bbc_image_module_keeps_real_image_and_caption_not_placeholder():
    page = HTML.replace(
        '<figure><img src="https://ichef.bbci.co.uk/body.jpg"><figcaption>Picture caption</figcaption></figure>',
        '<div><img src="https://static.files.bbci.co.uk/placeholder.svg"><img src="https://ichef.bbci.co.uk/body.jpg"><figcaption>Picture caption</figcaption></div>',
    )
    doc = (
        HtmlContentProvider(Fetcher(page), local_research_allowed=True)
        .acquire(request())
        .body_document
    )
    images = [b for b in doc.blocks if b.type == "image"]
    assert len(images) == 1
    assert images[0].source_url == "https://ichef.bbci.co.uk/body.jpg"
    assert images[0].caption == "Picture caption"


def test_malformed_topic_link_does_not_abort_valid_article():
    page = HTML.replace(
        'href="/news/topics/topic-one"', 'href="https://www.bbc.com:invalid/news/topics/topic-one"'
    )
    doc = (
        HtmlContentProvider(Fetcher(page), local_research_allowed=True)
        .acquire(request())
        .body_document
    )
    assert doc.publisher_tags == []
    assert doc.blocks


def test_nested_recommendations_do_not_leak_into_body():
    page = HTML.replace(
        "<p>" + TEXT + "</p><h2>",
        "<p>"
        + TEXT
        + '</p><div data-component="links-block"><p>Nested recommendation noise</p></div><h2>',
    )
    result = HtmlContentProvider(Fetcher(page), local_research_allowed=True).acquire(request())
    assert "Nested recommendation noise" not in result.body_text


def test_image_cap_is_respected():
    from dataclasses import replace

    page = HTML.replace(
        '<div data-component="links-block">',
        '<div data-component="image-block"><img src="https://ichef.bbci.co.uk/extra.jpg"></div><div data-component="links-block">',
    )
    req = request()
    req = replace(
        req, policy=replace(req.policy, images=replace(req.policy.images, max_images_per_article=1))
    )
    result = HtmlContentProvider(Fetcher(page), local_research_allowed=True).acquire(req)
    assert sum(b.type == "image" for b in result.body_document.blocks) == 1


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("empty", "unsupported_template"),
        ("title", "extraction_quality_failed"),
        ("canonical", "publisher_url_mismatch"),
        ("robots", "publisher_blocked"),
        ("disabled", "local_research_disabled"),
        ("paywall", "paywall_or_login"),
        ("unknown", "unsupported_template"),
    ],
)
def test_bbc_guards_fail_closed(scenario, code):
    page = HTML
    if scenario == "empty":
        page = ""
    if scenario == "title":
        page = page.replace(TITLE, "Completely different article")
    if scenario == "canonical":
        page = page.replace(f'href="{URL}"', 'href="https://www.bbc.com/news/articles/another"')
    if scenario == "paywall":
        page = page.replace(
            "</head>",
            '<script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":false}</script></head>',
        )
    if scenario == "unknown":
        page = page.replace("data-component=", "data-unknown=")
    fetcher = Fetcher(
        page,
        robots="User-agent: *\nDisallow: /" if scenario == "robots" else "User-agent: *\nAllow: /",
    )
    with pytest.raises(ContentAcquisitionError) as exc:
        HtmlContentProvider(fetcher, local_research_allowed=scenario != "disabled").acquire(
            request()
        )
    assert exc.value.code == code
