import json
import os

import pytest

from backend.app.live_news.content_fetch import FetchResponse
from backend.app.live_news.content_parser import derive_body_text, parse_structured_document
from backend.app.live_news.content_policy import ContentPolicy
from backend.app.live_news.content_providers import GuardianContentProvider
from backend.app.live_news.content_types import ContentRequest

URL = "https://www.theguardian.com/commentisfree/2026/sep/15/example"
FIRST = " ".join(["This is the authoritative first paragraph about the ceremony."] * 10)
SECOND = " ".join(["The second paragraph reports the responses and the background."] * 10)


class Responses:
    def __init__(self, *bodies):
        self.bodies = iter(bodies)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        body = next(self.bodies)
        return FetchResponse(
            url, 200, "application/json" if body.startswith(b"{") else "text/html", body, None
        )


def test_guardian_enrichment_does_not_replace_api_text_or_import_footer():
    api = {
        "response": {
            "content": {
                "webUrl": URL,
                "fields": {
                    "body": f"<p>{FIRST}</p><p>{SECOND}</p><ul><li>Actual reporting item</li></ul>"
                },
                "tags": [
                    {
                        "webTitle": "Public affairs",
                        "webUrl": "https://www.theguardian.com/world/public-affairs",
                        "type": "keyword",
                    }
                ],
            }
        }
    }
    page = f'<html><article><p>{FIRST}</p><figure><img src="https://i.guim.co.uk/inline.jpg"></figure><p>{SECOND}</p><p>Unrelated subscription promotion.</p><footer><span>Explore more on these topics</span><ul><li>Public affairs</li></ul></footer></article></html>'
    fetcher = Responses(json.dumps(api).encode(), page.encode())
    request = ContentRequest(
        article_id="L" + "a" * 32,
        canonical_url=URL,
        expected_domain="theguardian.com",
        language="en",
        policy=ContentPolicy(
            "guardian_api",
            "full_text",
            images={"display": "remote_url", "allowed_domains": ["i.guim.co.uk"]},
        ),
    )
    result = GuardianContentProvider(fetcher, "test-key").acquire(request)
    assert "Unrelated subscription" not in result.body_text
    assert "Public affairs" not in result.body_text
    assert "Actual reporting item" in result.body_text
    assert [b.type for b in result.body_document.blocks] == [
        "paragraph",
        "image",
        "paragraph",
        "list",
    ]
    assert result.body_document.publisher_tags[0].name == "Public affairs"
    assert "show-tags=all" in fetcher.urls[0]
    assert result.body_document.extraction_version == "guardian-structured-3"


def test_structural_footer_is_not_body_but_real_lists_are_kept():
    doc = parse_structured_document(
        "<html><article><p>Body.</p><ul><li>Opinion is discussed within the article.</li></ul><footer><ul><li>Footer topic</li></ul></footer></article></html>",
        article_id="L" + "b" * 32,
        source="guardian_api",
        base_url=URL,
        allowed_image_domains=frozenset(),
    )
    assert "Footer topic" not in derive_body_text(doc)
    assert "Opinion is discussed" in derive_body_text(doc)


def test_api_tags_are_separate_deduplicated_and_reject_unsafe_links():
    api = {
        "response": {
            "content": {
                "webUrl": URL,
                "fields": {"body": f"<p>{FIRST}</p>"},
                "tags": [
                    {
                        "webTitle": "Topic",
                        "webUrl": "https://www.theguardian.com/world/topic",
                        "type": "keyword",
                    },
                    {
                        "webTitle": "Topic",
                        "webUrl": "https://www.theguardian.com/world/topic",
                        "type": "keyword",
                    },
                    {"webTitle": "Unsafe", "webUrl": "javascript:alert(1)", "type": "keyword"},
                    {
                        "webTitle": "Other host",
                        "webUrl": "https://theguardian.com.evil.test/x",
                        "type": "keyword",
                    },
                    {
                        "webTitle": "Author",
                        "webUrl": "https://www.theguardian.com/profile/writer",
                        "type": "contributor",
                    },
                ],
            }
        }
    }
    request = ContentRequest(
        article_id="L" + "c" * 32,
        canonical_url=URL,
        expected_domain="theguardian.com",
        language="en",
        policy=ContentPolicy("guardian_api", "full_text"),
    )
    doc = (
        GuardianContentProvider(Responses(json.dumps(api).encode()), "test-key")
        .acquire(request)
        .body_document
    )
    assert [t.name for t in doc.publisher_tags] == ["Topic"]


@pytest.mark.parametrize("value", [None, "", {}, 42])
def test_missing_or_malformed_tags_do_not_break_body(value):
    from backend.app.live_news.guardian_document import guardian_tags

    assert guardian_tags({"tags": value}) == []


def test_unmatched_page_image_does_not_inject_page_text_or_get_guessed_position():
    from backend.app.live_news.guardian_document import merge_guardian_images

    def parse(value):
        return parse_structured_document(
            value,
            article_id="L" + "e" * 32,
            source="guardian_api",
            base_url=URL,
            allowed_image_domains=frozenset({"i.guim.co.uk"}),
        )

    api = parse(
        "<article><p>Authoritative content.</p><ol><li>Real numbered item.</li></ol></article>"
    )
    page = parse(
        '<article><p>Completely different page.</p><figure><img src="https://i.guim.co.uk/ad.jpg"></figure><p>Other story.</p></article>'
    )
    assert merge_guardian_images(api, page) == api


@pytest.mark.skipif(
    os.environ.get("NEWSREC_TEST_GUARDIAN_REMOTE") != "1",
    reason="explicit real-provider verification only",
)
def test_real_guardian_article_has_tags_outside_the_body():
    from backend.app.config import get_settings
    from backend.app.live_news.content_fetch import SafeFetcher

    settings = get_settings()
    if not settings.guardian_api_key:
        pytest.skip("Guardian API key not configured")
    url = "https://www.theguardian.com/commentisfree/2026/sep/15/zohran-mamdani-9-11-ceremony-petition-islamophobia"
    request = ContentRequest(
        article_id="L2a2203f2a92a7182643c7c53aedd2775",
        canonical_url=url,
        expected_domain="theguardian.com",
        language="en",
        policy=ContentPolicy("guardian_api", "full_text"),
    )
    result = GuardianContentProvider(SafeFetcher(), settings.guardian_api_key).acquire(request)
    assert result.body_document.publisher_tags
    assert result.body_document.extraction_version == "guardian-structured-3"
    tag_names = {t.name.casefold() for t in result.body_document.publisher_tags}
    for block in result.body_document.blocks:
        if block.type == "list":
            assert not all(item.casefold() in tag_names for item in block.items)
    assert "Explore more on these topics" not in result.body_text
