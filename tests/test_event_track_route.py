from __future__ import annotations

import os

import pytest

from backend.app.config import Settings

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not os.environ.get("NEWSREC_DATABASE_URL", "").strip(),
        reason="NEWSREC_DATABASE_URL not set; run scripts/init_local.ps1 -SmokeTest first.",
    ),
]


def _first_feed_news_id(client, user_id: int) -> str:
    feed = client.get("/feed", params={"user_id": user_id, "page_size": 1}).json()
    return str(feed["items"][0]["news_id"])


def test_event_track_log_only_event_acks_without_profile_change(
    postgres_client, postgres_demo_user
):
    before = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    base_score = float(before["behavior_score"])
    news_id = _first_feed_news_id(postgres_client, postgres_demo_user)

    r = postgres_client.post(
        "/event/track",
        json={
            "user_id": postgres_demo_user,
            "event_type": "feed_impression",
            "surface": "home_feed",
            "news_id": news_id,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["event_type"] == "feed_impression"
    assert body["profile_updated"] is False
    assert body["behavior_score"] is None

    after = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    assert float(after["behavior_score"]) == pytest.approx(base_score, abs=1e-6)


def test_event_track_impression_event_id_is_idempotent(postgres_client, postgres_demo_user):
    from backend.app.config import get_settings
    from backend.app.repositories.connection import connect, parse_database_url

    news_id = _first_feed_news_id(postgres_client, postgres_demo_user)
    event_id = f"test-impression-{postgres_demo_user}-{news_id}"
    payload = {
        "event_id": event_id,
        "user_id": postgres_demo_user,
        "event_type": "feed_impression",
        "surface": "home_feed",
        "news_id": news_id,
        "request_id": "test-request",
    }

    first = postgres_client.post("/event/track", json=payload)
    second = postgres_client.post("/event/track", json=payload)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    settings = get_settings()
    connection = connect(parse_database_url(settings.database_url))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS event_count, MIN(source_space) AS source_space, "
                "MIN(article_id) AS article_id "
                "FROM user_event WHERE external_event_id = %s",
                (event_id,),
            )
            row = cursor.fetchone()
    finally:
        connection.close()
    assert int(row["event_count"]) == 1
    assert row["source_space"] == "mind"
    assert row["article_id"] == news_id


def test_event_track_upvote_mutates_behavior_score(postgres_client, postgres_demo_user):
    settings = Settings()
    before = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    base_score = float(before["behavior_score"])
    news_id = _first_feed_news_id(postgres_client, postgres_demo_user)

    r = postgres_client.post(
        "/event/track",
        json={
            "user_id": postgres_demo_user,
            "event_type": "upvote",
            "surface": "home_feed",
            "news_id": news_id,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["event_type"] == "upvote"
    assert body["profile_updated"] is True
    assert body["behavior_score"] is not None
    assert body["behavior_score"] == pytest.approx(
        base_score + settings.recommendation_click_behavior_delta, abs=1e-3
    )

    after = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    assert after["recent_clicked_news"][0]["news_id"] == news_id
    expected_title = postgres_client.get(f"/articles/{news_id}").json()["title"]
    assert after["recent_clicked_news"][0]["title"] == expected_title


def test_recommendation_click_route_uses_news_id(postgres_client, postgres_demo_user):
    news_id = _first_feed_news_id(postgres_client, postgres_demo_user)
    r = postgres_client.post(
        "/event/recommendation_click",
        json={"user_id": postgres_demo_user, "news_id": news_id, "debug": True},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_event_track_feed_impression_requires_news_id(postgres_client, postgres_demo_user):
    response = postgres_client.post(
        "/event/track",
        json={
            "user_id": postgres_demo_user,
            "event_type": "feed_impression",
            "surface": "home_feed",
        },
    )
    assert response.status_code == 422


def test_event_track_replay_timestamp_requires_debug(unwired_client):
    response = unwired_client.post(
        "/event/track",
        json={
            "user_id": 7248,
            "event_type": "feed_impression",
            "surface": "feed",
            "news_id": "N1",
            "replay_event_ts": 100,
        },
    )

    assert response.status_code == 422


def test_live_event_rejects_mind_sponsored_identity_before_repository(
    unwired_client,
) -> None:
    response = unwired_client.post(
        "/event/track",
        json={
            "user_id": 7248,
            "source_space": "live",
            "event_type": "recommendation_click",
            "surface": "feed",
            "article_id": "L550e8400e29b41d4a716446655440000",
            "sponsored_delivery_id": "delivery-mind-only",
        },
    )

    assert response.status_code == 422


def test_event_track_duplicate_upvote_is_idempotent(postgres_client, postgres_demo_user):
    settings = Settings()
    before = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    news_id = _first_feed_news_id(postgres_client, postgres_demo_user)
    payload = {
        "event_id": f"duplicate-upvote-{postgres_demo_user}-{news_id}",
        "user_id": postgres_demo_user,
        "event_type": "upvote",
        "surface": "feed",
        "news_id": news_id,
    }

    first = postgres_client.post("/event/track", json=payload)
    second = postgres_client.post("/event/track", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    after = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    assert float(after["behavior_score"]) - float(before["behavior_score"]) == pytest.approx(
        settings.recommendation_click_behavior_delta,
        abs=1e-3,
    )


def test_event_track_persists_dwell_duration(postgres_client, postgres_demo_user):
    from backend.app.config import get_settings
    from backend.app.repositories.connection import connect, parse_database_url

    news_id = _first_feed_news_id(postgres_client, postgres_demo_user)
    event_id = f"dwell-{postgres_demo_user}-{news_id}"
    response = postgres_client.post(
        "/event/track",
        json={
            "event_id": event_id,
            "user_id": postgres_demo_user,
            "event_type": "dwell",
            "surface": "feed",
            "news_id": news_id,
            "dwell_ms": 4321,
        },
    )
    assert response.status_code == 200, response.text

    settings = get_settings()
    connection = connect(parse_database_url(settings.database_url))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT dwell_ms FROM user_event WHERE external_event_id = %s",
                (event_id,),
            )
            row = cursor.fetchone()
    finally:
        connection.close()
    assert int(row["dwell_ms"]) == 4321


def test_event_id_conflicting_payload_returns_409(postgres_client, postgres_demo_user):
    first_news = _first_feed_news_id(postgres_client, postgres_demo_user)
    feed = postgres_client.get(
        "/feed",
        params={
            "user_id": postgres_demo_user,
            "page_size": 2,
            "include_sponsored": "false",
        },
    ).json()
    second_news = next(
        str(item["news_id"]) for item in feed["items"] if str(item["news_id"]) != first_news
    )
    event_id = f"conflicting-event-{postgres_demo_user}"

    first = postgres_client.post(
        "/event/track",
        json={
            "event_id": event_id,
            "user_id": postgres_demo_user,
            "event_type": "feed_impression",
            "surface": "feed",
            "news_id": first_news,
        },
    )
    conflict = postgres_client.post(
        "/event/track",
        json={
            "event_id": event_id,
            "user_id": postgres_demo_user,
            "event_type": "feed_impression",
            "surface": "feed",
            "news_id": second_news,
        },
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "idempotency_conflict"
