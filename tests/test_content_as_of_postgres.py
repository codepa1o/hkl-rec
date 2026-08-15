from __future__ import annotations

import os

import pytest

from backend.app.config import get_settings
from backend.app.repositories.connection import connect, parse_database_url
from backend.app.repositories.content_dao import load_answer_event_counts_as_of
from backend.app.repositories.postgres import PostgresRuntimeRepository

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not os.environ.get("NEWSREC_DATABASE_URL", "").strip(),
        reason="NEWSREC_DATABASE_URL not set",
    ),
]


def test_as_of_popularity_excludes_future_impressions():
    settings = get_settings()
    connection = connect(parse_database_url(settings.database_url))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT answer_id, event_ts
                FROM user_event
                WHERE derived_from_raw IS TRUE
                  AND event_type = 'feed_impression'
                  AND answer_id IS NOT NULL
                ORDER BY event_ts ASC, event_id ASC
                LIMIT 1
                """
            )
            event = cursor.fetchone()
        answer_id = int(event["answer_id"])
        event_ts = int(event["event_ts"])
        before = load_answer_event_counts_as_of(
            connection,
            [answer_id],
            as_of_ts=event_ts,
        )
        after = load_answer_event_counts_as_of(
            connection,
            [answer_id],
            as_of_ts=event_ts + 1,
        )
    finally:
        connection.close()

    assert before.get(answer_id, {}).get("impression_count", 0) == 0
    assert int(after[answer_id]["impression_count"]) >= 1


def test_as_of_feed_excludes_future_created_answers():
    settings = get_settings()
    repository = PostgresRuntimeRepository(settings)
    response = repository.get_feed(
        user_id=settings.default_demo_user_id,
        page_size=50,
        debug=True,
        experiment_arm="manual_plus_als",
        include_sponsored=False,
        as_of_ts=1,
    )
    answer_ids = [item.answer_id for item in response.items]
    connection = connect(parse_database_url(settings.database_url))
    try:
        if answer_ids:
            placeholders = ",".join(["%s"] * len(answer_ids))
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS future_count
                    FROM answer
                    WHERE answer_id IN ({placeholders})
                      AND create_ts IS NOT NULL
                      AND create_ts > 1
                    """,
                    tuple(answer_ids),
                )
                future_count = int(cursor.fetchone()["future_count"])
        else:
            future_count = 0
    finally:
        connection.close()
        repository.close()
    assert future_count == 0
