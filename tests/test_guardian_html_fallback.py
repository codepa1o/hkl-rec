import pytest

from backend.app.live_news.content_fetch import FetchResponse
from backend.app.live_news.content_policy import ContentPolicy
from backend.app.live_news.content_providers import GuardianContentProvider
from backend.app.live_news.content_types import ContentAcquisitionError, ContentRequest

URL = "https://www.theguardian.com/us-news/2026/sep/15/example"
TITLE = "A court decision about international students"
PARAGRAPH = (
    "This is a verified article paragraph describing a court decision about international students. "
    * 8
)
HTML = f'''<html><head><link rel="canonical" href="{URL}"></head><body><article>
<h1>{TITLE}</h1><div class="article-body-commercial-selector">
<p>{PARAGRAPH}</p><h2>Background</h2><p>{PARAGRAPH}</p>
<figure><img src="https://i.guim.co.uk/inline.jpg"><figcaption>Picture credit</figcaption></figure>
<ul><li>Actual article point</li></ul><table><tr><td>Unsupported table</td></tr></table></div>
<footer><span>Explore more on these topics</span><ul><li><a href="/us-news/topic">Topic</a></li></ul></footer>
</article></body></html>'''


class Fetcher:
    def __init__(self, html=HTML, robots="User-agent: *\nAllow: /", api_code="api_tier_restricted"):
        self.html, self.robots, self.api_code = html, robots, api_code
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if "content.guardianapis.com" in url:
            raise ContentAcquisitionError(
                self.api_code,
                "API unavailable",
                retryable=self.api_code in {"http_429", "network_error"},
            )
        body = self.robots if url.endswith("/robots.txt") else self.html
        return FetchResponse(
            url,
            200,
            "text/plain" if url.endswith("/robots.txt") else "text/html",
            body.encode(),
            None,
        )


def request():
    return ContentRequest(
        article_id="L" + "d" * 32,
        canonical_url=URL,
        expected_domain="theguardian.com",
        language="en",
        title=TITLE,
        policy=ContentPolicy(
            "guardian_api",
            "full_text",
            html_fallback_enabled=True,
            images={"display": "remote_url", "allowed_domains": ["i.guim.co.uk"]},
        ),
    )


def provider(fetcher):
    from backend.app.live_news.guardian_html import GuardianHtmlProvider

    return GuardianContentProvider(
        fetcher,
        "test-key",
        html_fallback=GuardianHtmlProvider(fetcher, local_research_allowed=True),
    )


def test_tier_restriction_uses_scoped_html_and_retains_structure():
    result = provider(Fetcher()).acquire(request())
    assert result.source == "html"
    assert result.access_scope == "local_research"
    assert result.body_document.fallback_reason == "api_tier_restricted"
    assert [b.type for b in result.body_document.blocks] == [
        "paragraph",
        "heading",
        "paragraph",
        "image",
        "list",
    ]
    assert "Actual article point" in result.body_text
    assert "Explore more" not in result.body_text
    assert result.body_document.publisher_tags[0].name == "Topic"
    assert result.body_document.warnings


def test_visible_byline_overrides_generic_structured_metadata():
    html = HTML.replace(
        "</head>",
        '<script type="application/ld+json">{"@type":"NewsArticle","author":{"name":"Guardian staff reporter"}}</script></head>',
    )
    html = html.replace("<h1>", '<address data-component="meta-byline">Reuters</address><h1>')
    assert provider(Fetcher(html)).acquire(request()).body_document.byline == "Reuters"


def test_empty_html_becomes_a_handled_acquisition_error():
    with pytest.raises(ContentAcquisitionError) as e:
        provider(Fetcher("")).acquire(request())
    assert e.value.code == "unsupported_template"


def test_empty_api_body_can_fall_back_but_source_opt_out_cannot():
    import json
    from dataclasses import replace

    class EmptyApi(Fetcher):
        def get(self, url, **kwargs):
            if "content.guardianapis.com" in url:
                value = {"response": {"content": {"webUrl": URL, "fields": {}}}}
                return FetchResponse(url, 200, "application/json", json.dumps(value).encode(), None)
            return super().get(url, **kwargs)

    result = provider(EmptyApi()).acquire(request())
    assert result.body_document.fallback_reason == "api_body_unavailable"
    disabled = replace(request(), policy=ContentPolicy("guardian_api", "full_text"))
    fetcher = Fetcher()
    with pytest.raises(ContentAcquisitionError) as e:
        provider(fetcher).acquire(disabled)
    assert e.value.code == "api_tier_restricted"
    assert len(fetcher.calls) == 1


@pytest.mark.parametrize(
    "code",
    ["authentication_required", "network_error", "http_429", "http_500", "article_not_found"],
)
def test_other_api_failures_do_not_trigger_html(code):
    fetcher = Fetcher(api_code=code)
    with pytest.raises(ContentAcquisitionError) as e:
        provider(fetcher).acquire(request())
    assert e.value.code == code
    assert len(fetcher.calls) == 1


@pytest.mark.parametrize(
    "change,expected",
    [
        ("robots", "publisher_blocked"),
        ("canonical", "publisher_url_mismatch"),
        ("title", "extraction_quality_failed"),
        ("container", "unsupported_template"),
        ("paywall", "paywall_or_login"),
        ("disabled", "local_research_disabled"),
    ],
)
def test_html_guardrails(change, expected):
    from backend.app.live_news.guardian_html import GuardianHtmlProvider

    html = HTML
    if change == "canonical":
        html = html.replace(f'href="{URL}"', 'href="https://www.theguardian.com/another-article"')
    if change == "title":
        html = html.replace(TITLE, "Something entirely unrelated")
    if change == "container":
        html = html.replace("article-body-commercial-selector", "unknown-template")
    if change == "paywall":
        html = html.replace(
            "</head>",
            '<script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":false}</script></head>',
        )
    fetcher = Fetcher(
        html,
        robots="User-agent: *\nDisallow: /" if change == "robots" else "User-agent: *\nAllow: /",
    )
    with pytest.raises(ContentAcquisitionError) as e:
        GuardianHtmlProvider(fetcher, local_research_allowed=change != "disabled").acquire(
            request()
        )
    assert e.value.code == expected
