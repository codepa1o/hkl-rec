from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not os.environ.get("NEWSREC_DATABASE_URL", "").strip(),
        reason="NEWSREC_DATABASE_URL not set; run scripts/init_local.ps1 -SmokeTest first.",
    ),
]


def test_healthz_reports_postgresql_backend(mysql_client, mysql_demo_user):
    r = mysql_client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["repository_backend"] == "postgresql"
    assert body["database_configured"] is True
    assert body["dependencies"]["postgresql"]["status"] == "ok"


def test_feed_returns_items_with_cold_start_mix(mysql_client, mysql_demo_user):
    settings = Settings()
    r = mysql_client.get(
        "/feed",
        params={"user_id": mysql_demo_user, "page_size": 3, "debug": "true"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == mysql_demo_user
    assert 0 < len(body["items"]) <= 3
    mix = body["debug"]["cold_start_mix"]
    assert settings.cold_start_alpha_floor <= mix["alpha"] <= settings.cold_start_alpha_ceiling
    assert mix["default_seed_key"] == settings.cold_start_default_seed_key
    assert mix["default_topic_count"] > 0


def test_recommendation_click_increases_behavior_score(mysql_client, mysql_demo_user):
    settings = Settings()
    before = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    base = float(before["behavior_score"])

    feed = mysql_client.get("/feed", params={"user_id": mysql_demo_user, "page_size": 1}).json()
    answer_id = feed["items"][0]["article_id"]

    ack = mysql_client.post(
        "/event/recommendation_click",
        json={"user_id": mysql_demo_user, "article_id": answer_id, "debug": True},
    )
    assert ack.status_code == 200
    assert ack.json()["ok"] is True

    after = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    delta = float(after["behavior_score"]) - base
    assert delta == pytest.approx(settings.recommendation_click_behavior_delta, abs=1e-3)
    assert after["recent_clicked_articles"][0]["article_id"] == answer_id


def test_search_then_feed_shows_recall_candidates(mysql_client, mysql_demo_user):
    feed_before = mysql_client.get(
        "/feed",
        params={"user_id": mysql_demo_user, "page_size": 1},
    ).json()
    article = feed_before["items"][0]
    query_text = article["headline"]
    search_resp = mysql_client.post(
        "/search",
        json={
            "user_id": mysql_demo_user,
            "query_text": query_text,
            "page_size": 5,
            "debug": True,
        },
    )
    assert search_resp.status_code == 200
    assert len(search_resp.json()["items"]) > 0
    assert article["article_id"] in {item["article_id"] for item in search_resp.json()["items"]}
    assert search_resp.json()["debug"]["result_sources"]

    feed_resp = mysql_client.get(
        "/feed",
        params={"user_id": mysql_demo_user, "page_size": 10, "debug": "true"},
    )
    assert feed_resp.status_code == 200
    debug_payload = feed_resp.json()["debug"]
    sources = {c["source"] for c in debug_payload["recall_candidates"]}
    assert any("recent_query_topic" in source for source in sources)
    profile = mysql_client.get(
        "/debug/profile",
        params={"user_id": mysql_demo_user},
    ).json()
    assert profile["recent_queries"][0]["query_key"] == search_resp.json()["query_key"]


def test_rejected_hybrid_query_does_not_mutate_profile(mysql_client, mysql_demo_user):
    before = mysql_client.get(
        "/debug/profile",
        params={"user_id": mysql_demo_user},
    ).json()

    response = mysql_client.post(
        "/search",
        json={
            "user_id": mysql_demo_user,
            "query_text": "kubernetes ingress controller tls termination",
            "page_size": 10,
        },
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "unresolved_query"
    after = mysql_client.get(
        "/debug/profile",
        params={"user_id": mysql_demo_user},
    ).json()
    assert after["behavior_score"] == before["behavior_score"]
    assert after["recent_queries"] == before["recent_queries"]


def test_duplicate_search_event_updates_profile_once(mysql_client, mysql_demo_user):
    settings = Settings()
    before = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    payload = {
        "event_id": f"duplicate-search-{mysql_demo_user}",
        "user_id": mysql_demo_user,
        "query_key": "248 12125",
        "page_size": 5,
    }

    first = mysql_client.post("/search", json=payload)
    second = mysql_client.post("/search", json=payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["request_id"] == payload["event_id"]
    assert second.json()["request_id"] == payload["event_id"]
    after = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    assert float(after["behavior_score"]) - float(before["behavior_score"]) == pytest.approx(
        settings.search_query_behavior_delta,
        abs=1e-3,
    )


def test_concurrent_clicks_do_not_lose_profile_updates(mysql_client, mysql_demo_user):
    from backend.app.main import create_app

    settings = Settings()
    before = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    base_score = float(before["behavior_score"])
    feed = mysql_client.get(
        "/feed",
        params={"user_id": mysql_demo_user, "page_size": 2},
    ).json()
    answer_ids = [int(item["article_id"]) for item in feed["items"]]
    assert len(answer_ids) == 2

    barrier = Barrier(2)

    def click(answer_id: int) -> int:
        barrier.wait(timeout=10)
        with TestClient(create_app()) as client:
            response = client.post(
                "/event/recommendation_click",
                json={"user_id": mysql_demo_user, "article_id": answer_id},
            )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(click, answer_ids))

    assert statuses == [200, 200]
    after = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    expected_delta = 2 * settings.recommendation_click_behavior_delta
    assert float(after["behavior_score"]) - base_score == pytest.approx(expected_delta, abs=1e-3)
    recent_ids = {int(row["article_id"]) for row in after["recent_clicked_articles"]}
    assert set(answer_ids).issubset(recent_ids)


def test_concurrent_duplicate_click_is_one_idempotent_update(
    mysql_client,
    mysql_demo_user,
):
    from backend.app.main import create_app

    settings = Settings()
    before = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    base_score = float(before["behavior_score"])
    answer_id = int(
        mysql_client.get(
            "/feed",
            params={
                "user_id": mysql_demo_user,
                "page_size": 1,
                "include_sponsored": "false",
            },
        ).json()["items"][0]["article_id"]
    )
    event_id = f"duplicate-click-{mysql_demo_user}-{answer_id}"
    barrier = Barrier(2)

    def click(_index: int) -> int:
        barrier.wait(timeout=10)
        with TestClient(create_app()) as client:
            response = client.post(
                "/event/track",
                json={
                    "event_id": event_id,
                    "user_id": mysql_demo_user,
                    "event_type": "recommendation_click",
                    "surface": "feed",
                    "article_id": answer_id,
                    "request_id": "duplicate-click-request",
                },
            )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(click, [1, 2]))

    assert statuses == [200, 200]
    after = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    assert float(after["behavior_score"]) - base_score == pytest.approx(
        settings.recommendation_click_behavior_delta,
        abs=1e-3,
    )
