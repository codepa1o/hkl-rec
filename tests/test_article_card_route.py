from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not os.environ.get("NEWSREC_DATABASE_URL", "").strip(),
        reason="NEWSREC_DATABASE_URL not set; run scripts/init_local.ps1 -SmokeTest first.",
    ),
]


def test_article_card_returns_payload_for_feed_article(postgres_client, postgres_demo_user):
    feed = postgres_client.get(
        "/feed", params={"user_id": postgres_demo_user, "page_size": 1}
    ).json()
    news_id = feed["items"][0]["news_id"]

    r = postgres_client.get(f"/articles/{news_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["news_id"] == news_id
    assert isinstance(body["title"], str) and body["title"]
    assert isinstance(body["abstract"], str)
    assert isinstance(body["source_domain"], str) and body["source_domain"]
    assert isinstance(body["categories"], list)
    assert isinstance(body["title_entities"], list)
    assert isinstance(body["abstract_entities"], list)


def test_article_card_returns_404_for_unknown_article(postgres_client, postgres_demo_user):
    r = postgres_client.get("/articles/N999999999")
    assert r.status_code == 404
