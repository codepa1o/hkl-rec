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


def test_search_suggestions_returns_submit_ready_query_keys(postgres_client, postgres_demo_user):
    r = postgres_client.get("/search/suggestions", params={"limit": 12})
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["items"], list)
    assert len(body["items"]) > 0
    for item in body["items"]:
        assert isinstance(item["query_key"], str) and item["query_key"].strip()
        assert isinstance(item["label"], str) and item["label"]
        assert item["topic_count"] >= 1

    # 第一个建议项的 query_key 必须可由 POST /search 直接使用。
    query_key = body["items"][0]["query_key"]
    search = postgres_client.post(
        "/search",
        json={
            "user_id": postgres_demo_user,
            "query_key": query_key,
            "page_size": 5,
            "debug": True,
        },
    )
    assert search.status_code == 200, search.text
    assert all(
        "lexical_match" not in source["source"]
        for source in search.json()["debug"]["result_sources"]
    )
