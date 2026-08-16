from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.app.config import get_settings
from backend.app.repositories.connection import connect, parse_database_url
from backend.app.repositories.sponsored_dao import (
    SponsoredCandidate,
    reserve_sponsored_delivery,
)

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not os.environ.get("NEWSREC_DATABASE_URL", "").strip(),
        reason="NEWSREC_DATABASE_URL not set",
    ),
]


def test_feed_blends_two_sponsored_items_and_tracks_delivery(
    postgres_client,
    postgres_demo_user,
):
    response = postgres_client.get(
        "/feed",
        params={"user_id": postgres_demo_user, "page_size": 10, "debug": "true"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    sponsored_items = [
        (index, item)
        for index, item in enumerate(body["items"], start=1)
        if item["content_type"] == "sponsored"
    ]
    assert [position for position, _ in sponsored_items] == [3, 8]
    assert len(body["debug"]["sponsored_candidates"]) == 2

    first = sponsored_items[0][1]
    delivery_id = first["sponsored"]["delivery_id"]
    impression = postgres_client.post(
        "/event/track",
        json={
            "event_id": f"test-sponsored-impression-{delivery_id}",
            "user_id": postgres_demo_user,
            "event_type": "feed_impression",
            "surface": "feed",
            "news_id": first["news_id"],
            "request_id": body["request_id"],
            "sponsored_delivery_id": delivery_id,
        },
    )
    assert impression.status_code == 200, impression.text

    click = postgres_client.post(
        "/event/track",
        json={
            "event_id": f"test-sponsored-click-{delivery_id}",
            "user_id": postgres_demo_user,
            "event_type": "recommendation_click",
            "surface": "feed",
            "news_id": first["news_id"],
            "request_id": body["request_id"],
            "sponsored_delivery_id": delivery_id,
        },
    )
    assert click.status_code == 200, click.text

    settings = get_settings()
    connection = connect(parse_database_url(settings.database_url))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  sd.expected_spend_micros,
                  sd.confirmed_impression_ts,
                  sd.clicked_ts,
                  scr.bid_micros,
                  scr.predicted_ctr
                FROM sponsored_delivery sd
                JOIN sponsored_creative scr ON scr.creative_id = sd.creative_id
                WHERE sd.delivery_id = %s
                """,
                (delivery_id,),
            )
            row = cursor.fetchone()
        assert int(row["expected_spend_micros"]) == round(
            int(row["bid_micros"]) * float(row["predicted_ctr"])
        )
        assert row["confirmed_impression_ts"] is not None
        assert row["clicked_ts"] is not None
    finally:
        connection.close()


def test_organic_evaluation_feed_excludes_sponsored(postgres_client, postgres_demo_user):
    response = postgres_client.get(
        "/feed",
        params={
            "user_id": postgres_demo_user,
            "page_size": 10,
            "include_sponsored": "false",
            "experiment_arm": "manual",
        },
    )
    assert response.status_code == 200, response.text
    assert all(item["content_type"] == "organic" for item in response.json()["items"])


def test_duplicate_feed_request_reuses_sponsored_deliveries(
    postgres_client,
    postgres_demo_user,
):
    request_id = f"feed-retry-{postgres_demo_user}"
    params = {
        "user_id": postgres_demo_user,
        "page_size": 10,
        "debug": "true",
        "request_id": request_id,
    }

    first = postgres_client.get("/feed", params=params)
    second = postgres_client.get("/feed", params=params)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_deliveries = [
        item["sponsored"]["delivery_id"]
        for item in first.json()["items"]
        if item["content_type"] == "sponsored"
    ]
    second_deliveries = [
        item["sponsored"]["delivery_id"]
        for item in second.json()["items"]
        if item["content_type"] == "sponsored"
    ]
    assert first_deliveries
    assert second_deliveries == first_deliveries

    settings = get_settings()
    connection = connect(parse_database_url(settings.database_url))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS delivery_count
                FROM sponsored_delivery
                WHERE request_id = %s AND user_id = %s
                """,
                (request_id, postgres_demo_user),
            )
            delivery_count = int(cursor.fetchone()["delivery_count"])
    finally:
        connection.close()
    assert delivery_count == len(first_deliveries)


def test_feed_request_id_rejects_different_page_shape(postgres_client, postgres_demo_user):
    request_id = f"feed-shape-conflict-{postgres_demo_user}"
    first = postgres_client.get(
        "/feed",
        params={
            "user_id": postgres_demo_user,
            "page_size": 10,
            "request_id": request_id,
        },
    )
    conflict = postgres_client.get(
        "/feed",
        params={
            "user_id": postgres_demo_user,
            "page_size": 3,
            "request_id": request_id,
        },
    )

    assert first.status_code == 200, first.text
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "idempotency_conflict"


def test_non_sponsored_feed_request_binds_page_shape(postgres_client, postgres_demo_user):
    request_id = f"organic-feed-shape-{postgres_demo_user}"
    first = postgres_client.get(
        "/feed",
        params={
            "user_id": postgres_demo_user,
            "page_size": 3,
            "include_sponsored": "false",
            "request_id": request_id,
        },
    )
    conflict = postgres_client.get(
        "/feed",
        params={
            "user_id": postgres_demo_user,
            "page_size": 5,
            "include_sponsored": "false",
            "request_id": request_id,
        },
    )

    assert first.status_code == 200, first.text
    assert conflict.status_code == 409


def test_feed_request_id_binds_debug_shape(postgres_client, postgres_demo_user):
    request_id = f"feed-debug-shape-{postgres_demo_user}"
    first = postgres_client.get(
        "/feed",
        params={
            "user_id": postgres_demo_user,
            "page_size": 3,
            "debug": "false",
            "include_sponsored": "false",
            "request_id": request_id,
        },
    )
    conflict = postgres_client.get(
        "/feed",
        params={
            "user_id": postgres_demo_user,
            "page_size": 3,
            "debug": "true",
            "include_sponsored": "false",
            "request_id": request_id,
        },
    )

    assert first.status_code == 200, first.text
    assert conflict.status_code == 409


def test_concurrent_reservations_respect_budget_and_frequency(postgres_demo_user):
    settings = get_settings()
    config = parse_database_url(settings.database_url)
    campaign_id = 99001
    creative_id = 199001
    now_ts = int(time.time())
    lookup = connect(config)
    try:
        with lookup.cursor() as cursor:
            cursor.execute(
                """
                SELECT mapping.news_id, mapping.topic_id
                FROM mind_news_topic AS mapping
                ORDER BY mapping.news_id, mapping.source_rank
                LIMIT 1
                """
            )
            content = cursor.fetchone()
    finally:
        lookup.close()
    news_id = str(content["news_id"])
    topic_id = int(content["topic_id"])
    candidate = SponsoredCandidate(
        campaign_id=campaign_id,
        campaign_name="Concurrency Test",
        creative_id=creative_id,
        news_id=news_id,
        bid_micros=1000,
        predicted_ctr=0.1,
        quality_score=1.0,
        target_topic_ids=(topic_id,),
    )
    setup = connect(config)
    try:
        with setup.transaction(), setup.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sponsored_campaign (
                  campaign_id,
                  campaign_name,
                  status,
                  start_ts,
                  end_ts,
                  daily_budget_micros,
                  pacing_mode,
                  frequency_cap_per_user_per_day
                )
                VALUES (%s, 'Concurrency Test', 'active', 0, 4102444800, 100, 'asap', 1)
                """,
                (campaign_id,),
            )
            cursor.execute(
                "INSERT INTO sponsored_campaign_topic (campaign_id, topic_id) VALUES (%s, %s)",
                (campaign_id, topic_id),
            )
            cursor.execute(
                """
                INSERT INTO sponsored_creative (
                  creative_id,
                  campaign_id,
                  news_id,
                  status,
                  bid_micros,
                  predicted_ctr,
                  quality_score
                )
                VALUES (%s, %s, %s, 'active', 1000, 0.1, 1.0)
                """,
                (creative_id, campaign_id, news_id),
            )
    finally:
        setup.close()

    def reserve(index: int) -> bool:
        connection = connect(config)
        try:
            with connection.transaction():
                delivery = reserve_sponsored_delivery(
                    connection,
                    candidate=candidate,
                    user_id=postgres_demo_user,
                    request_id=f"concurrent-sponsored-{index}",
                    slot_position=3,
                    now_ts=now_ts,
                    pacing_headroom_seconds=3600,
                )
            return delivery is not None
        finally:
            connection.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reserve, [1, 2]))
        assert sorted(results) == [False, True]
    finally:
        cleanup = connect(config)
        try:
            with cleanup.transaction(), cleanup.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM sponsored_delivery WHERE campaign_id = %s",
                    (campaign_id,),
                )
                cursor.execute(
                    "DELETE FROM sponsored_user_daily_frequency WHERE campaign_id = %s",
                    (campaign_id,),
                )
                cursor.execute(
                    "DELETE FROM sponsored_campaign_daily_state WHERE campaign_id = %s",
                    (campaign_id,),
                )
                cursor.execute(
                    "DELETE FROM sponsored_creative WHERE campaign_id = %s",
                    (campaign_id,),
                )
                cursor.execute(
                    "DELETE FROM sponsored_campaign_topic WHERE campaign_id = %s",
                    (campaign_id,),
                )
                cursor.execute(
                    "DELETE FROM sponsored_campaign WHERE campaign_id = %s",
                    (campaign_id,),
                )
        finally:
            cleanup.close()
