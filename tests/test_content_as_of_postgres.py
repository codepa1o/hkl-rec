from __future__ import annotations

import os

import pytest

from backend.app.config import get_settings
from backend.app.repositories.connection import connect, parse_database_url
from backend.app.repositories.content_dao import load_news_event_counts_as_of
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
        event_ts = 1_900_000_000
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT news_id
                FROM mind_news
                ORDER BY news_id
                LIMIT 1
                """
            )
            news_id = str(cursor.fetchone()["news_id"])
            cursor.execute(
                """
                DELETE FROM user_event
                WHERE external_event_id = 'as-of-popularity-fixture'
                """
            )
            cursor.execute(
                """
                INSERT INTO user_event (
                    external_event_id, user_id, event_type, news_id, surface,
                    derived_from_raw, source_confidence, event_ts
                ) VALUES (
                    'as-of-popularity-fixture', %s, 'feed_impression', %s,
                    'test', TRUE, 'confirmed', %s
                )
                """,
                (settings.default_demo_user_id, news_id, event_ts),
            )
        before = load_news_event_counts_as_of(
            connection,
            [news_id],
            as_of_ts=event_ts,
        )
        after = load_news_event_counts_as_of(
            connection,
            [news_id],
            as_of_ts=event_ts + 1,
        )
    finally:
        connection.close()

    assert int(after[news_id]["impression_count"]) >= (
        int(before.get(news_id, {}).get("impression_count", 0)) + 1
    )


def test_as_of_feed_excludes_future_news():
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
    news_ids = [item.news_id for item in response.items]
    connection = connect(parse_database_url(settings.database_url))
    try:
        if news_ids:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS future_count
                    FROM mind_news_stats
                    WHERE news_id = ANY(%s)
                      AND first_seen_ts IS NOT NULL
                      AND first_seen_ts > 1
                    """,
                    (news_ids,),
                )
                future_count = int(cursor.fetchone()["future_count"])
        else:
            future_count = 0
    finally:
        connection.close()
        repository.close()
    assert future_count == 0
