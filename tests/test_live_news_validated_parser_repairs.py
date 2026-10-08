"""Minimal reproductions of the 2026-09-16 real-page comparison failures."""

import json
from dataclasses import replace

import pytest

from backend.app.live_news.bbc_html import BBC_VERSION
from backend.app.live_news.content_fetch import FetchResponse
from backend.app.live_news.content_policy import ContentPolicy
from backend.app.live_news.content_providers import GuardianContentProvider, HtmlContentProvider
from backend.app.live_news.content_types import ContentAcquisitionError, ContentRequest
from backend.app.live_news.guardian_html import GuardianHtmlProvider
from backend.app.live_news.html_adapters import XINHUA_ADAPTER

BBC_URL = "https://www.bbc.com/news/articles/test123"
GUARDIAN_URL = "https://www.theguardian.com/world/2026/sep/16/test-story"
TITLE = "A detailed report about the city transport project"
FIRST = "The report explains the transport project and its effects on local residents. " * 5
SECOND = (
    "Officials discussed the timetable, public responses and the next steps in the project. " * 5
)


class PageFetcher:
    def __init__(self, page, final_url=None):
        self.page = page
        self.final_url = final_url

    def get(self, url, **kwargs):
        robots = url.endswith("/robots.txt")
        return FetchResponse(
            url if robots else self.final_url or url,
            200,
            "text/plain" if robots else "text/html; charset=utf-8",
            b"User-agent: *\nAllow: /" if robots else self.page.encode(),
            None,
        )


def bbc_request():
    return ContentRequest(
        "L" + "a" * 32,
        BBC_URL,
        "bbc.com",
        "en",
        ContentPolicy(
            "html",
            "full_text",
            access_scope="local_research",
            adapter="bbc",
            target_extraction_version=BBC_VERSION,
            images={"display": "remote_url", "allowed_domains": ["ichef.bbci.co.uk"]},
        ),
        lead_image_url="https://ichef.bbci.co.uk/hero.jpg",
        title=TITLE,
    )


def bbc_page(body, *, heading=TITLE, page_title=TITLE):
    return f'<html><head><title>{page_title}</title><link rel="canonical" href="{BBC_URL}"></head><body><main id="bbc-main"><article><div data-component="headline-block"><h1>{heading}</h1></div>{body}</article></main></body></html>'


def test_bbc_exact_document_title_accepts_updated_h1_on_same_canonical():
    page = bbc_page(
        f'<div data-component="text-block"><p>{FIRST}</p><p>{SECOND}</p></div>',
        heading="How public transport is changing in the city",
    )
    result = HtmlContentProvider(PageFetcher(page), local_research_allowed=True).acquire(
        bbc_request()
    )
    assert FIRST.strip() in result.body_text


def test_bbc_rendered_layout_preserves_image_caption_and_order_excludes_cards():
    page = bbc_page(f"""<div data-component="image-block"><figure data-testid="hero-image"><img src="https://ichef.bbci.co.uk/hero.jpg"></figure></div>
      <div data-component="layout-block"><div><p>{FIRST}</p>
      <figure><div data-testid="image"><img src="https://ichef.bbci.co.uk/body.jpg"></div><figcaption>Field report image</figcaption></figure>
      <div data-component="advertisement-block"><p>Advertising paragraph</p></div>
      <h2>Background</h2><p>{SECOND}</p>
      <div data-testid="links-grid"><p>Related article promotion</p><img src="https://ichef.bbci.co.uk/promo.jpg"></div>
      <div data-component="unknown-widget"><p>Unrecognized widget</p></div></div></div>""")
    doc = (
        HtmlContentProvider(PageFetcher(page), local_research_allowed=True)
        .acquire(bbc_request())
        .body_document
    )
    assert [b.type for b in doc.blocks] == ["paragraph", "image", "heading", "paragraph"]
    assert doc.blocks[1].caption == "Field report image"
    assert doc.blocks[1].source_url == "https://ichef.bbci.co.uk/body.jpg"


@pytest.mark.parametrize("change", ["different_title", "canonical", "unknown_layout"])
def test_bbc_identity_and_unknown_template_remain_rejected(change):
    page = bbc_page(f'<div data-component="layout-block"><p>{FIRST}</p><p>{SECOND}</p></div>')
    if change == "different_title":
        page = page.replace(TITLE, "An unrelated report on wildlife")
    if change == "canonical":
        page = page.replace(f'href="{BBC_URL}"', 'href="https://www.bbc.com/news/articles/other"')
    if change == "unknown_layout":
        page = page.replace("layout-block", "unrecognized-block")
    with pytest.raises(ContentAcquisitionError):
        HtmlContentProvider(PageFetcher(page), local_research_allowed=True).acquire(bbc_request())


def guardian_request():
    return ContentRequest(
        "L" + "b" * 32,
        GUARDIAN_URL,
        "theguardian.com",
        "en",
        ContentPolicy(
            "guardian_api",
            "full_text",
            images={"display": "remote_url", "allowed_domains": ["i.guim.co.uk"]},
        ),
        title=TITLE,
    )


def guardian_page(body):
    return f'<html><head><link rel="canonical" href="{GUARDIAN_URL}"></head><body><article><h1>{TITLE}</h1><div class="article-body-commercial-selector">{body}</div></article></body></html>'


def test_guardian_list_only_article_passes_prose_quality_check():
    page = guardian_page(f"<ul><li>{FIRST}</li><li>{SECOND}</li><li>{FIRST}</li></ul>")
    result = GuardianHtmlProvider(PageFetcher(page), local_research_allowed=True).acquire(
        guardian_request()
    )
    assert [b.type for b in result.body_document.blocks] == ["list"]
    assert len(result.body_document.blocks[0].items) == 3


def test_guardian_caption_clones_and_scroll_hints_are_not_body():
    page = guardian_page(f"""<p>{FIRST}</p><div class="horizontal">
      <figure><img src="https://i.guim.co.uk/photo.jpg"><figcaption>Unique caption</figcaption></figure>
      <div class="sticky-captions"><div class="caption"><p>Unique caption</p><p class="caption-measurer" aria-hidden="true">Unique caption</p></div></div>
      <div class="scroll-tooltip"><p>Keep scrolling</p></div></div><p>{SECOND}</p>""")
    result = GuardianHtmlProvider(PageFetcher(page), local_research_allowed=True).acquire(
        guardian_request()
    )
    assert [b.type for b in result.body_document.blocks] == ["paragraph", "image", "paragraph"]
    assert result.body_text.count("Unique caption") == 1
    assert "Keep scrolling" not in result.body_text


def test_guardian_real_repeated_text_and_unmatched_caption_are_preserved():
    page = guardian_page(
        f'<p>{FIRST}</p><p>{FIRST}</p><div class="horizontal"><div class="sticky-captions"><p>Unmatched visible caption</p></div></div>'
    )
    result = GuardianHtmlProvider(PageFetcher(page), local_research_allowed=True).acquire(
        guardian_request()
    )
    assert result.body_text.count(FIRST.strip()) == 2
    assert "Unmatched visible caption" in result.body_text


def test_guardian_long_image_caption_cannot_make_empty_story_pass():
    page = guardian_page(
        f'<ul><li>Home</li><li>News</li><li>Contact</li></ul><figure><img src="https://i.guim.co.uk/photo.jpg"><figcaption>{FIRST}{SECOND}</figcaption></figure>'
    )
    with pytest.raises(ContentAcquisitionError):
        GuardianHtmlProvider(PageFetcher(page), local_research_allowed=True).acquire(
            guardian_request()
        )


def test_guardian_numbered_puzzle_instructions_are_not_accepted_as_news_prose():
    url = GUARDIAN_URL.replace("test-story", "sudoku-7454-medium")
    page = guardian_page(
        f"<p>{FIRST}</p><ul><li>{SECOND}</li><li>Print the puzzle.</li></ul>"
    ).replace(GUARDIAN_URL, url)
    with pytest.raises(ContentAcquisitionError, match="unsupported_template"):
        GuardianHtmlProvider(PageFetcher(page), local_research_allowed=True).acquire(
            replace(guardian_request(), canonical_url=url)
        )


def test_guardian_supplemental_image_failure_is_visible_without_exposing_error_detail():
    class Fetcher:
        def get(self, url, **kwargs):
            if "content.guardianapis.com" in url:
                payload = {
                    "response": {
                        "content": {
                            "webUrl": GUARDIAN_URL,
                            "fields": {"body": f"<p>{FIRST}</p><p>{SECOND}</p>"},
                        }
                    }
                }
                return FetchResponse(
                    url, 200, "application/json", json.dumps(payload).encode(), None
                )
            raise ContentAcquisitionError("network_error", "secret-provider-query", retryable=True)

    result = GuardianContentProvider(Fetcher(), "test-key").acquire(guardian_request())
    assert result.body_document.warnings
    assert "图片" in result.body_document.warnings[0]
    assert "secret-provider-query" not in " ".join(result.body_document.warnings)
    assert [b.type for b in result.body_document.blocks] == ["paragraph", "paragraph"]


def test_guardian_transient_image_page_failure_has_one_bounded_retry():
    class Fetcher:
        page_calls = 0

        def get(self, url, **kwargs):
            if "content.guardianapis.com" in url:
                payload = {
                    "response": {
                        "content": {
                            "webUrl": GUARDIAN_URL,
                            "fields": {"body": f"<p>{FIRST}</p><p>{SECOND}</p>"},
                        }
                    }
                }
                return FetchResponse(
                    url, 200, "application/json", json.dumps(payload).encode(), None
                )
            self.page_calls += 1
            if self.page_calls == 1:
                raise ContentAcquisitionError(
                    "network_error", "temporary connection loss", retryable=True
                )
            page = guardian_page(
                f'<p>{FIRST}</p><figure><img src="https://i.guim.co.uk/photo.jpg"><figcaption>Caption</figcaption></figure><p>{SECOND}</p>'
            )
            return FetchResponse(url, 200, "text/html", page.encode(), None)

    fetcher = Fetcher()
    result = GuardianContentProvider(fetcher, "test-key").acquire(guardian_request())
    assert fetcher.page_calls == 2
    assert [b.type for b in result.body_document.blocks] == ["paragraph", "image", "paragraph"]
    assert result.body_document.warnings == []


ZH_TITLE = "本地公共交通服务发布新方案"
ZH_PARAGRAPH = "本市发布公共交通服务改进方案，相关部门介绍了线路调整和配套设施建设情况，市民可以通过公开渠道提出意见。"


def xinhua_request():
    return ContentRequest(
        "L" + "c" * 32,
        "https://www.ha.xinhuanet.com/20260916/test/c.html",
        "xinhuanet.com",
        "zh",
        ContentPolicy(
            "html",
            "full_text",
            access_scope="local_research",
            adapter="xinhuanet",
            target_extraction_version=XINHUA_ADAPTER.extraction_version,
        ),
        title=ZH_TITLE,
    )


def xinhua_page(body, *, title=ZH_TITLE, root="detail"):
    return f'<html><head><title>{title}-新华网</title></head><body><h1>{title}</h1><div id="{root}">{body}</div></body></html>'


def test_xinhua_two_substantial_paragraphs_are_not_rejected_by_block_count():
    page = xinhua_page(f"<p>{ZH_PARAGRAPH * 4}</p><p>{ZH_PARAGRAPH * 4}</p>")
    result = HtmlContentProvider(PageFetcher(page), local_research_allowed=True).acquire(
        xinhua_request()
    )
    assert len(result.body_document.blocks) == 2


def test_xinhua_short_news_requires_exact_title_and_explicit_body_container():
    text = ZH_PARAGRAPH * 2
    assert 200 < len(text) * 2 < 300
    result = HtmlContentProvider(
        PageFetcher(xinhua_page(f"<p>{text}</p><p>{text}</p>")), local_research_allowed=True
    ).acquire(xinhua_request())
    assert len(result.body_text) < 300
    assert len(result.body_document.blocks) == 2


def test_xinhua_exact_title_in_publisher_body_markup_is_supported():
    page = xinhua_page(f"<p>{ZH_PARAGRAPH * 2}</p><p>{ZH_PARAGRAPH * 2}</p>")
    page = page.replace("<head>", "<head></head><body><div>Publisher masthead</div>").replace(
        "</head><body>", ""
    )
    assert (
        HtmlContentProvider(PageFetcher(page), local_research_allowed=True)
        .acquire(xinhua_request())
        .body_text
    )


def test_short_xinhua_single_excerpt_needs_more_than_one_substantial_segment():
    page = xinhua_page(f"<p>{ZH_PARAGRAPH * 4}</p>")
    with pytest.raises(ContentAcquisitionError):
        HtmlContentProvider(PageFetcher(page), local_research_allowed=True).acquire(
            xinhua_request()
        )


@pytest.mark.parametrize(
    "case", ["too_short", "title_changed", "no_title", "image_caption_padding"]
)
def test_xinhua_short_story_does_not_relax_general_quality_guards(case):
    body = f"<p>{ZH_PARAGRAPH * 2}</p><p>{ZH_PARAGRAPH * 2}</p>"
    title = ZH_TITLE
    if case == "too_short":
        body = f"<p>{ZH_PARAGRAPH}</p>"
    if case == "title_changed":
        title = ZH_TITLE + "补充内容"
    if case == "no_title":
        title = ""
    if case == "image_caption_padding":
        body = f'<p>本地新闻简讯。</p><figure><img src="https://www.xinhuanet.com/p.jpg"><figcaption>{ZH_PARAGRAPH * 10}</figcaption></figure>'
    with pytest.raises(ContentAcquisitionError):
        HtmlContentProvider(
            PageFetcher(xinhua_page(body, title=title)), local_research_allowed=True
        ).acquire(xinhua_request())
