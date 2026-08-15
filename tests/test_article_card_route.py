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


def test_article_card_returns_payload_for_feed_article(mysql_client, mysql_demo_user):
    feed = mysql_client.get("/feed", params={"user_id": mysql_demo_user, "page_size": 1}).json()
    article_id = feed["items"][0]["article_id"]

    r = mysql_client.get(f"/articles/{article_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["article_id"] == article_id
    assert isinstance(body["headline"], str) and body["headline"]
    assert isinstance(body["abstract"], str)
    assert isinstance(body["source_domain"], str) and body["source_domain"]
    assert isinstance(body["categories"], list)


def test_article_card_returns_404_for_unknown_article(mysql_client, mysql_demo_user):
    r = mysql_client.get("/articles/999999999")
    assert r.status_code == 404
