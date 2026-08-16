from __future__ import annotations

import os
import time

import pytest

from backend.app.config import Settings
from backend.app.errors import IdempotencyConflictError
from backend.app.events.consumer import ProfileEventApplier
from backend.app.events.outbox import OutboxPublisherWorker, enqueue_outbox_message
from backend.app.events.schema import UserEventMessage
from backend.app.repositories.connection import connect, parse_database_url
from backend.app.repositories.postgres import PostgresRuntimeRepository
from backend.app.schemas.event_track import EventTrackRequest

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not os.environ.get("NEWSREC_DATABASE_URL", "").strip(),
        reason="NEWSREC_DATABASE_URL not set",
    ),
]


def _settings(event_mode: str) -> Settings:
    return Settings(
        database_url=os.environ["NEWSREC_DATABASE_URL"],
        event_mode=event_mode,  # type: ignore[arg-type]
        outbox_poll_interval_seconds=0.01,
    )


def _first_news_id(postgres_client, user_id: int) -> str:
    feed = postgres_client.get("/feed", params={"user_id": user_id, "page_size": 1}).json()
    return str(feed["items"][0]["news_id"])


def _fetch_count(connection, sql: str, params: tuple[object, ...]) -> int:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    return int(row["row_count"])


def test_dual_write_stages_raw_event_in_same_database(postgres_client, postgres_demo_user):
    settings = _settings("kafka_dual_write")
    repository = PostgresRuntimeRepository(settings)
    news_id = _first_news_id(postgres_client, postgres_demo_user)
    event_id = f"dual-outbox-{time.time_ns()}"

    response = repository.record_tracked_event(
        EventTrackRequest(
            event_id=event_id,
            user_id=postgres_demo_user,
            event_type="feed_impression",
            surface="feed",
            news_id=news_id,
            request_id="dual-outbox-request",
        )
    )
    assert response.ok is True

    connection = connect(parse_database_url(settings.database_url))
    try:
        assert (
            _fetch_count(
                connection,
                """
                SELECT COUNT(*) AS row_count
                FROM event_outbox
                WHERE event_id = %s AND topic = %s
                """,
                (event_id, settings.kafka_raw_events_topic),
            )
            == 1
        )
    finally:
        connection.close()


def test_kafka_async_ack_requires_durable_raw_outbox(postgres_client, postgres_demo_user):
    settings = _settings("kafka_async")
    repository = PostgresRuntimeRepository(settings)
    news_id = _first_news_id(postgres_client, postgres_demo_user)
    event_id = f"async-outbox-{time.time_ns()}"
    before = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()

    response = repository.record_tracked_event(
        EventTrackRequest(
            event_id=event_id,
            user_id=postgres_demo_user,
            event_type="recommendation_click",
            surface="feed",
            news_id=news_id,
            request_id="async-outbox-request",
        )
    )
    assert response.ok is True
    assert response.profile_updated is False

    connection = connect(parse_database_url(settings.database_url))
    try:
        assert (
            _fetch_count(
                connection,
                """
                SELECT COUNT(*) AS row_count
                FROM event_outbox
                WHERE event_id = %s AND topic = %s AND status = 'pending'
                """,
                (event_id, settings.kafka_raw_events_topic),
            )
            == 1
        )
        assert (
            _fetch_count(
                connection,
                """
                SELECT COUNT(*) AS row_count
                FROM user_event
                WHERE external_event_id = %s
                """,
                (event_id,),
            )
            == 0
        )
    finally:
        connection.close()
    after = postgres_client.get("/debug/profile", params={"user_id": postgres_demo_user}).json()
    assert float(after["behavior_score"]) == float(before["behavior_score"])


def test_kafka_async_rejects_conflicting_duplicate_event_id(
    postgres_client,
    postgres_demo_user,
):
    settings = _settings("kafka_async")
    repository = PostgresRuntimeRepository(settings)
    feed = postgres_client.get(
        "/feed",
        params={
            "user_id": postgres_demo_user,
            "page_size": 2,
            "include_sponsored": "false",
        },
    ).json()
    first_news = str(feed["items"][0]["news_id"])
    second_news = str(feed["items"][1]["news_id"])
    event_id = f"async-conflict-{time.time_ns()}"

    repository.record_tracked_event(
        EventTrackRequest(
            event_id=event_id,
            user_id=postgres_demo_user,
            event_type="feed_impression",
            surface="feed",
            news_id=first_news,
            request_id="async-conflict-request",
        )
    )

    with pytest.raises(IdempotencyConflictError):
        repository.record_tracked_event(
            EventTrackRequest(
                event_id=event_id,
                user_id=postgres_demo_user,
                event_type="feed_impression",
                surface="feed",
                news_id=second_news,
                request_id="async-conflict-request",
            )
        )


def test_duplicate_consumer_event_backfills_one_training_outbox(
    postgres_client,
    postgres_demo_user,
):
    settings = _settings("kafka_async")
    news_id = _first_news_id(postgres_client, postgres_demo_user)
    event = UserEventMessage(
        event_id=f"consumer-outbox-{time.time_ns()}",
        event_type="feed_impression",
        user_id=postgres_demo_user,
        news_id=news_id,
        request_id="consumer-outbox-request",
        surface="feed",
        event_ts=int(time.time()),
    )
    applier = ProfileEventApplier(settings)

    assert applier.apply_event(event) is True
    assert applier.apply_event(event) is False

    connection = connect(parse_database_url(settings.database_url))
    try:
        assert (
            _fetch_count(
                connection,
                """
                SELECT COUNT(*) AS row_count
                FROM event_outbox
                WHERE event_id = %s AND topic = %s
                """,
                (event.event_id, settings.kafka_training_topic),
            )
            == 1
        )
    finally:
        connection.close()


def test_consumer_persists_dwell_duration(postgres_client, postgres_demo_user):
    settings = _settings("kafka_async")
    news_id = _first_news_id(postgres_client, postgres_demo_user)
    event = UserEventMessage(
        event_id=f"consumer-dwell-{time.time_ns()}",
        event_type="dwell",
        user_id=postgres_demo_user,
        news_id=news_id,
        request_id="consumer-dwell-request",
        surface="feed",
        dwell_ms=4321,
        event_ts=int(time.time()),
    )

    assert ProfileEventApplier(settings).apply_event(event) is True

    connection = connect(parse_database_url(settings.database_url))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT dwell_ms FROM user_event WHERE external_event_id = %s",
                (event.event_id,),
            )
            row = cursor.fetchone()
    finally:
        connection.close()
    assert int(row["dwell_ms"]) == 4321


def test_failed_outbox_batch_remains_retryable(postgres_client):
    settings = _settings("kafka_async")
    event_id = f"retry-outbox-{time.time_ns()}"
    connection = connect(parse_database_url(settings.database_url))
    try:
        with connection.transaction():
            enqueue_outbox_message(
                connection,
                event_id=event_id,
                topic=settings.kafka_training_topic,
                message_key="7248",
                payload_json='{"example_id":"retry"}',
            )
    finally:
        connection.close()

    class FailingPublisher:
        def publish_payload(self, topic: str, key: str, value: bytes) -> None:
            return None

        def flush(self) -> None:
            raise RuntimeError("injected publish failure")

    worker = OutboxPublisherWorker(settings, publisher=FailingPublisher())
    assert worker.run_once() == 0

    connection = connect(parse_database_url(settings.database_url))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, attempt_count, last_error
                FROM event_outbox
                WHERE event_id = %s AND topic = %s
                """,
                (event_id, settings.kafka_training_topic),
            )
            row = cursor.fetchone()
        assert row["status"] == "pending"
        assert int(row["attempt_count"]) == 1
        assert "injected publish failure" in str(row["last_error"])
    finally:
        connection.close()
