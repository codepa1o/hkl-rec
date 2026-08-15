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


def test_personas_returns_three_demo_personas(mysql_client, mysql_demo_user):
    r = mysql_client.get("/personas", params={"limit": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    user_ids = [item["user_id"] for item in body["items"]]
    assert mysql_demo_user in user_ids
    assert len(user_ids) >= 3
    for item in body["items"]:
        assert isinstance(item["display_name"], str) and item["display_name"]
        assert isinstance(item["behavior_score"], (int, float))
        assert isinstance(item["top_topics"], list)


def test_personas_respects_limit(mysql_client, mysql_demo_user):
    r = mysql_client.get("/personas", params={"limit": 2})
    assert r.status_code == 200
    assert len(r.json()["items"]) <= 2
