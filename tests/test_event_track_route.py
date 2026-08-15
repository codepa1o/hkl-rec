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


def _first_feed_answer_id(client, user_id: int) -> int:
    feed = client.get("/feed", params={"user_id": user_id, "page_size": 1}).json()
    return int(feed["items"][0]["article_id"])


def test_event_track_log_only_event_acks_without_profile_change(mysql_client, mysql_demo_user):
    before = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    base_score = float(before["behavior_score"])
    answer_id = _first_feed_answer_id(mysql_client, mysql_demo_user)

    r = mysql_client.post(
        "/event/track",
        json={
            "user_id": mysql_demo_user,
            "event_type": "feed_impression",
            "surface": "home_feed",
            "article_id": answer_id,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["event_type"] == "feed_impression"
    assert body["profile_updated"] is False
    assert body["behavior_score"] is None

    after = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    assert float(after["behavior_score"]) == pytest.approx(base_score, abs=1e-6)


def test_event_track_impression_event_id_is_idempotent(mysql_client, mysql_demo_user):
    from backend.app.config import get_settings
    from backend.app.repositories.connection import connect, parse_database_url

    answer_id = _first_feed_answer_id(mysql_client, mysql_demo_user)
    event_id = f"test-impression-{mysql_demo_user}-{answer_id}"
    payload = {
        "event_id": event_id,
        "user_id": mysql_demo_user,
        "event_type": "feed_impression",
        "surface": "home_feed",
        "article_id": answer_id,
        "request_id": "test-request",
    }

    first = mysql_client.post("/event/track", json=payload)
    second = mysql_client.post("/event/track", json=payload)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    settings = get_settings()
    connection = connect(parse_database_url(settings.database_url))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS event_count FROM user_event WHERE external_event_id = %s",
                (event_id,),
            )
            row = cursor.fetchone()
    finally:
        connection.close()
    assert int(row["event_count"]) == 1


def test_event_track_upvote_mutates_behavior_score(mysql_client, mysql_demo_user):
    settings = Settings()
    before = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    base_score = float(before["behavior_score"])
    answer_id = _first_feed_answer_id(mysql_client, mysql_demo_user)

    r = mysql_client.post(
        "/event/track",
        json={
            "user_id": mysql_demo_user,
            "event_type": "upvote",
            "surface": "home_feed",
            "article_id": answer_id,
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

    after = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    assert after["recent_clicked_articles"][0]["article_id"] == answer_id


def test_recommendation_click_route_uses_article_id(mysql_client, mysql_demo_user):
    answer_id = _first_feed_answer_id(mysql_client, mysql_demo_user)
    r = mysql_client.post(
        "/event/recommendation_click",
        json={"user_id": mysql_demo_user, "article_id": answer_id, "debug": True},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_event_track_feed_impression_requires_article_id(mysql_client, mysql_demo_user):
    response = mysql_client.post(
        "/event/track",
        json={
            "user_id": mysql_demo_user,
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
            "article_id": 1,
            "replay_event_ts": 100,
        },
    )

    assert response.status_code == 422


def test_event_track_duplicate_upvote_is_idempotent(mysql_client, mysql_demo_user):
    settings = Settings()
    before = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    answer_id = _first_feed_answer_id(mysql_client, mysql_demo_user)
    payload = {
        "event_id": f"duplicate-upvote-{mysql_demo_user}-{answer_id}",
        "user_id": mysql_demo_user,
        "event_type": "upvote",
        "surface": "feed",
        "article_id": answer_id,
    }

    first = mysql_client.post("/event/track", json=payload)
    second = mysql_client.post("/event/track", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    after = mysql_client.get("/debug/profile", params={"user_id": mysql_demo_user}).json()
    assert float(after["behavior_score"]) - float(before["behavior_score"]) == pytest.approx(
        settings.recommendation_click_behavior_delta,
        abs=1e-3,
    )


def test_event_track_persists_dwell_duration(mysql_client, mysql_demo_user):
    from backend.app.config import get_settings
    from backend.app.repositories.connection import connect, parse_database_url

    answer_id = _first_feed_answer_id(mysql_client, mysql_demo_user)
    event_id = f"dwell-{mysql_demo_user}-{answer_id}"
    response = mysql_client.post(
        "/event/track",
        json={
            "event_id": event_id,
            "user_id": mysql_demo_user,
            "event_type": "dwell",
            "surface": "feed",
            "article_id": answer_id,
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


def test_event_id_conflicting_payload_returns_409(mysql_client, mysql_demo_user):
    first_answer = _first_feed_answer_id(mysql_client, mysql_demo_user)
    feed = mysql_client.get(
        "/feed",
        params={
            "user_id": mysql_demo_user,
            "page_size": 2,
            "include_sponsored": "false",
        },
    ).json()
    second_answer = next(
        int(item["article_id"]) for item in feed["items"] if int(item["article_id"]) != first_answer
    )
    event_id = f"conflicting-event-{mysql_demo_user}"

    first = mysql_client.post(
        "/event/track",
        json={
            "event_id": event_id,
            "user_id": mysql_demo_user,
            "event_type": "feed_impression",
            "surface": "feed",
            "article_id": first_answer,
        },
    )
    conflict = mysql_client.post(
        "/event/track",
        json={
            "event_id": event_id,
            "user_id": mysql_demo_user,
            "event_type": "feed_impression",
            "surface": "feed",
            "article_id": second_answer,
        },
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "idempotency_conflict"
