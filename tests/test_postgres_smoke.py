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
        reason="NEWSREC_DATABASE_URL not set; initialize PostgreSQL and the MIND catalog first.",
    ),
]


def test_healthz_reports_postgresql_backend(postgres_client, postgres_demo_user):
    r = postgres_client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["repository_backend"] == "postgresql"
    assert body["database_configured"] is True
    assert body["dependencies"]["postgresql"]["status"] == "ok"


def test_feed_returns_items_with_cold_start_mix(postgres_client, postgres_demo_user):
    settings = Settings()
    r = postgres_client.get(
        "/feed",
        params={"user_id": postgres_demo_user, "page_size": 3, "debug": "true"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == postgres_demo_user
    assert 0 < len(body["items"]) <= 3
    mix = body["debug"]["cold_start_mix"]
    assert settings.cold_start_alpha_floor <= mix["alpha"] <= settings.cold_start_alpha_ceiling
    assert mix["default_seed_key"] == settings.cold_start_default_seed_key
    assert mix["default_topic_count"] > 0


def test_feed_cursor_appends_unique_pages(postgres_client, postgres_demo_user):
    first = postgres_client.get(
        "/feed",
        params={
            "user_id": postgres_demo_user,
            "page_size": 20,
            "request_id": f"cursor-page-1-{postgres_demo_user}",
        },
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert len(first_body["items"]) == 20
    assert first_body["has_more"] is True
    assert first_body["next_cursor"]

    second = postgres_client.get(
        "/feed",
        params={
            "user_id": postgres_demo_user,
            "page_size": 20,
            "request_id": f"cursor-page-2-{postgres_demo_user}",
            "cursor": first_body["next_cursor"],
        },
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert len(second_body["items"]) == 20
    assert {item["news_id"] for item in first_body["items"]}.isdisjoint(
        item["news_id"] for item in second_body["items"]
    )


def test_feed_cursor_rejects_incompatible_page_shape(postgres_client, postgres_demo_user):
    first = postgres_client.get(
        "/feed",
        params={
            "user_id": postgres_demo_user,
            "page_size": 20,
            "request_id": f"cursor-shape-1-{postgres_demo_user}",
        },
    )
    assert first.status_code == 200, first.text

    incompatible = postgres_client.get(
        "/feed",
        params={
            "user_id": postgres_demo_user,
            "page_size": 10,
            "request_id": f"cursor-shape-2-{postgres_demo_user}",
            "cursor": first.json()["next_cursor"],
        },
    )
    assert incompatible.status_code == 409


def test_recommendation_click_increases_behavior_score(postgres_client, postgres_demo_user):
    settings = Settings()
    before = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    base = float(before["behavior_score"])

    feed = postgres_client.get(
        "/feed", params={"user_id": postgres_demo_user, "page_size": 1}
    ).json()
    news_id = feed["items"][0]["news_id"]

    ack = postgres_client.post(
        "/event/recommendation_click",
        json={"user_id": postgres_demo_user, "news_id": news_id, "debug": True},
    )
    assert ack.status_code == 200
    assert ack.json()["ok"] is True

    after = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    delta = float(after["behavior_score"]) - base
    assert delta == pytest.approx(settings.recommendation_click_behavior_delta, abs=1e-3)
    assert after["recent_clicked_news"][0]["news_id"] == news_id


def test_search_then_feed_shows_recall_candidates(postgres_client, postgres_demo_user):
    feed_before = postgres_client.get(
        "/feed",
        params={"user_id": postgres_demo_user, "page_size": 1},
    ).json()
    article = feed_before["items"][0]
    query_text = article["title"]
    search_resp = postgres_client.post(
        "/search",
        json={
            "user_id": postgres_demo_user,
            "query_text": query_text,
            "page_size": 5,
            "debug": True,
        },
    )
    assert search_resp.status_code == 200
    assert len(search_resp.json()["items"]) > 0
    assert article["news_id"] in {item["news_id"] for item in search_resp.json()["items"]}
    assert search_resp.json()["debug"]["result_sources"]

    feed_resp = postgres_client.get(
        "/feed",
        params={"user_id": postgres_demo_user, "page_size": 10, "debug": "true"},
    )
    assert feed_resp.status_code == 200
    debug_payload = feed_resp.json()["debug"]
    sources = {c["source"] for c in debug_payload["recall_candidates"]}
    assert any("recent_query_topic" in source for source in sources)
    profile = postgres_client.get(
        "/debug/profile",
        params={"user_id": postgres_demo_user},
    ).json()
    assert profile["recent_queries"][0]["query_key"] == search_resp.json()["query_key"]


def test_rejected_hybrid_query_does_not_mutate_profile(postgres_client, postgres_demo_user):
    before = postgres_client.get(
        "/debug/profile",
        params={"user_id": postgres_demo_user},
    ).json()

    response = postgres_client.post(
        "/search",
        json={
            "user_id": postgres_demo_user,
            "query_text": "kubernetes ingress controller tls termination",
            "page_size": 10,
        },
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "unresolved_query"
    after = postgres_client.get(
        "/debug/profile",
        params={"user_id": postgres_demo_user},
    ).json()
    assert after["behavior_score"] == before["behavior_score"]
    assert after["recent_queries"] == before["recent_queries"]


def test_duplicate_search_event_updates_profile_once(postgres_client, postgres_demo_user):
    settings = Settings()
    before = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    suggestions = postgres_client.get("/search/suggestions", params={"limit": 1}).json()
    query_key = suggestions["items"][0]["query_key"]
    payload = {
        "event_id": f"duplicate-search-{postgres_demo_user}",
        "user_id": postgres_demo_user,
        "query_key": query_key,
        "page_size": 5,
    }

    first = postgres_client.post("/search", json=payload)
    second = postgres_client.post("/search", json=payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["request_id"] == payload["event_id"]
    assert second.json()["request_id"] == payload["event_id"]
    after = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    assert float(after["behavior_score"]) - float(before["behavior_score"]) == pytest.approx(
        settings.search_query_behavior_delta,
        abs=1e-3,
    )


def test_concurrent_clicks_do_not_lose_profile_updates(postgres_client, postgres_demo_user):
    from dataclasses import replace

    from backend.app.config import get_settings
    from backend.app.dependencies import get_app_settings
    from backend.app.main import create_app

    settings = Settings()
    before = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    base_score = float(before["behavior_score"])
    feed = postgres_client.get(
        "/feed",
        params={"user_id": postgres_demo_user, "page_size": 2},
    ).json()
    news_ids = [str(item["news_id"]) for item in feed["items"]]
    assert len(news_ids) == 2

    barrier = Barrier(2)

    def click(news_id: str) -> int:
        barrier.wait(timeout=10)
        app = create_app()
        app.dependency_overrides[get_app_settings] = lambda: replace(
            get_settings(),
            auth_secret_key="",
            allow_unauthenticated_research_api=True,
        )
        with TestClient(app) as client:
            response = client.post(
                "/event/recommendation_click",
                json={"user_id": postgres_demo_user, "news_id": news_id},
            )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(click, news_ids))

    assert statuses == [200, 200]
    after = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    expected_delta = 2 * settings.recommendation_click_behavior_delta
    assert float(after["behavior_score"]) - base_score == pytest.approx(expected_delta, abs=1e-3)
    recent_ids = {str(row["news_id"]) for row in after["recent_clicked_news"]}
    assert set(news_ids).issubset(recent_ids)


def test_concurrent_duplicate_click_is_one_idempotent_update(
    postgres_client,
    postgres_demo_user,
):
    from dataclasses import replace

    from backend.app.config import get_settings
    from backend.app.dependencies import get_app_settings
    from backend.app.main import create_app

    settings = Settings()
    before = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    base_score = float(before["behavior_score"])
    news_id = str(
        postgres_client.get(
            "/feed",
            params={
                "user_id": postgres_demo_user,
                "page_size": 1,
                "include_sponsored": "false",
            },
        ).json()["items"][0]["news_id"]
    )
    event_id = f"duplicate-click-{postgres_demo_user}-{news_id}"
    barrier = Barrier(2)

    def click(_index: int) -> int:
        barrier.wait(timeout=10)
        app = create_app()
        app.dependency_overrides[get_app_settings] = lambda: replace(
            get_settings(),
            auth_secret_key="",
            allow_unauthenticated_research_api=True,
        )
        with TestClient(app) as client:
            response = client.post(
                "/event/track",
                json={
                    "event_id": event_id,
                    "user_id": postgres_demo_user,
                    "event_type": "recommendation_click",
                    "surface": "feed",
                    "news_id": news_id,
                    "request_id": "duplicate-click-request",
                },
            )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(click, [1, 2]))

    assert statuses == [200, 200]
    after = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    assert float(after["behavior_score"]) - base_score == pytest.approx(
        settings.recommendation_click_behavior_delta,
        abs=1e-3,
    )
