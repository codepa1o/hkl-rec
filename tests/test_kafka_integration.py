from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from backend.app.config import Settings
from backend.app.events.consumer import run_profile_consumer
from backend.app.events.outbox import OutboxPublisherWorker
from backend.app.events.schema import (
    DlqEventMessage,
    TrainingInteractionMessage,
    UserEventMessage,
)

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.kafka,
    pytest.mark.skipif(
        not os.environ.get("NEWSREC_DATABASE_URL", "").strip(),
        reason="NEWSREC_DATABASE_URL not set",
    ),
    pytest.mark.skipif(
        not os.environ.get("NEWSREC_KAFKA_BOOTSTRAP_SERVERS", "").strip(),
        reason="NEWSREC_KAFKA_BOOTSTRAP_SERVERS not set",
    ),
]


@pytest.fixture
def kafka_event_user(postgres_connection: Any) -> Iterator[tuple[int, str]]:
    connection = postgres_connection
    connection.rollback()
    user_id = 8_000_000_000 + (uuid.uuid4().int % 100_000_000)
    news_id = f"N{user_id}"
    seed_key = f"kafka-test-{user_id}"
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO system_profile_seed "
            "(seed_key, source_space, topic_weights_json, recent_clicked_news_json, "
            "recent_queries_json, behavior_score, notes) "
            "VALUES (%s, 'mind', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 0, 'kafka test')",
            (seed_key,),
        )
        cursor.execute(
            "INSERT INTO app_user (user_id, display_name, is_demo_user, source) "
            "VALUES (%s, %s, false, 'kafka_test')",
            (user_id, f"Kafka test {user_id}"),
        )
        cursor.execute(
            "INSERT INTO mind_news "
            "(news_id, category, subcategory, title, abstract, url, "
            "title_entities, abstract_entities) "
            "VALUES (%s, 'test', 'kafka', 'Kafka integration article', '', %s, "
            "'[]'::jsonb, '[]'::jsonb)",
            (news_id, f"https://example.test/{news_id}"),
        )
        cursor.execute(
            "INSERT INTO user_profile "
            "(user_id, source_space, cold_start_seed_key, topic_weights_json, "
            "recent_clicked_news_json, recent_queries_json, behavior_score, notes) "
            "VALUES (%s, 'mind', %s, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 0, "
            "'kafka test')",
            (user_id, seed_key),
        )
    connection.commit()
    try:
        yield user_id, news_id
    finally:
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM user_event WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM event_idempotency WHERE user_id = %s", (user_id,))
            cursor.execute(
                "DELETE FROM event_outbox WHERE payload_json ->> 'user_id' = %s",
                (str(user_id),),
            )
            cursor.execute(
                "DELETE FROM user_profile WHERE user_id = %s AND source_space = 'mind'",
                (user_id,),
            )
            cursor.execute("DELETE FROM mind_news WHERE news_id = %s", (news_id,))
            cursor.execute("DELETE FROM app_user WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM system_profile_seed WHERE seed_key = %s", (seed_key,))
        connection.commit()


def test_raw_event_reaches_postgres_and_training_topic(kafka_event_user):
    from confluent_kafka import Consumer, Producer
    from confluent_kafka.admin import AdminClient, NewTopic

    suffix = uuid.uuid4().hex[:10]
    postgres_demo_user, news_id = kafka_event_user
    raw_topic = f"newsrec.test.raw.{suffix}"
    training_topic = f"newsrec.test.training.{suffix}"
    dlq_topic = f"newsrec.test.dlq.{suffix}"
    bootstrap = os.environ["NEWSREC_KAFKA_BOOTSTRAP_SERVERS"]
    admin = AdminClient({"bootstrap.servers": bootstrap})
    futures = admin.create_topics(
        [
            NewTopic(raw_topic, num_partitions=3, replication_factor=1),
            NewTopic(training_topic, num_partitions=3, replication_factor=1),
            NewTopic(dlq_topic, num_partitions=3, replication_factor=1),
        ]
    )
    for future in futures.values():
        future.result(timeout=20)

    settings = Settings(
        database_url=os.environ["NEWSREC_DATABASE_URL"],
        event_mode="kafka_async",
        kafka_bootstrap_servers=bootstrap,
        kafka_profile_group_id=f"newsrec-test-profile-{suffix}",
        kafka_raw_events_topic=raw_topic,
        kafka_training_topic=training_topic,
        kafka_dlq_topic=dlq_topic,
        outbox_poll_interval_seconds=0.01,
    )
    event = UserEventMessage(
        event_id=f"kafka-integration-{suffix}",
        event_type="feed_impression",
        user_id=postgres_demo_user,
        source_space="mind",
        article_id=news_id,
        news_id=news_id,
        request_id=f"kafka-request-{suffix}",
        surface="feed",
        event_ts=int(time.time()),
    )
    legacy_event_id = f"kafka-legacy-{suffix}"

    producer = Producer(
        {
            "bootstrap.servers": bootstrap,
            "enable.idempotence": True,
            "acks": "all",
        }
    )
    producer.produce(
        raw_topic,
        key=event.publish_partition_key(settings.kafka_source_partition_keys_enabled).encode(),
        value=event.to_json_bytes(),
    )
    producer.produce(
        raw_topic,
        key=event.publish_partition_key(settings.kafka_source_partition_keys_enabled).encode(),
        value=json.dumps(
            {
                "schema_version": 4,
                "event_id": legacy_event_id,
                "event_type": "feed_impression",
                "user_id": postgres_demo_user,
                "news_id": news_id,
                "request_id": f"kafka-legacy-request-{suffix}",
                "surface": "feed",
                "event_ts": int(time.time()),
            }
        ).encode(),
    )
    assert producer.flush(20) == 0

    run_profile_consumer(settings, max_messages=2)
    from backend.app.repositories.connection import connect, parse_database_url

    connection = connect(parse_database_url(settings.database_url))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT external_event_id, source_space, article_id FROM user_event "
                "WHERE external_event_id IN (%s, %s) ORDER BY external_event_id",
                (event.event_id, legacy_event_id),
            )
            stored = {row["external_event_id"]: row for row in cursor.fetchall()}
    finally:
        connection.close()
    expected_identity = {
        "source_space": "mind",
        "article_id": news_id,
    }
    assert {
        key: {field: row[field] for field in expected_identity} for key, row in stored.items()
    } == {
        event.event_id: expected_identity,
        legacy_event_id: expected_identity,
    }

    worker = OutboxPublisherWorker(settings)
    try:
        assert worker.run_once() >= 1
    finally:
        worker.close()

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"newsrec-test-training-{suffix}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([training_topic])
    try:
        deadline = time.monotonic() + 20
        messages = []
        while time.monotonic() < deadline and len(messages) < 2:
            candidate = consumer.poll(1.0)
            if candidate is not None and not candidate.error():
                messages.append(candidate)
        assert len(messages) == 2
        training_by_id = {
            training.example_id: (message, training)
            for message in messages
            for training in [TrainingInteractionMessage.model_validate_json(message.value())]
        }
        assert set(training_by_id) == {event.event_id, legacy_event_id}
        for message, training in training_by_id.values():
            assert message.key().decode() == str(postgres_demo_user)
            assert training.schema_version == 5
            assert training.source_space == "mind"
            assert training.article_id == news_id
            assert training.label is None
        assert training_by_id[event.event_id][1].request_id == event.request_id
    finally:
        consumer.close()


@pytest.mark.parametrize("invalid_kind", ["cross_space", "null_schema_version"])
def test_invalid_raw_event_reaches_dlq(invalid_kind: str):
    from confluent_kafka import Consumer, Producer
    from confluent_kafka.admin import AdminClient, NewTopic

    suffix = uuid.uuid4().hex[:10]
    raw_topic = f"newsrec.test.raw.{suffix}"
    training_topic = f"newsrec.test.training.{suffix}"
    dlq_topic = f"newsrec.test.dlq.{suffix}"
    bootstrap = os.environ["NEWSREC_KAFKA_BOOTSTRAP_SERVERS"]
    admin = AdminClient({"bootstrap.servers": bootstrap})
    futures = admin.create_topics(
        [
            NewTopic(raw_topic, num_partitions=3, replication_factor=1),
            NewTopic(training_topic, num_partitions=3, replication_factor=1),
            NewTopic(dlq_topic, num_partitions=3, replication_factor=1),
        ]
    )
    for future in futures.values():
        future.result(timeout=20)

    settings = Settings(
        database_url=os.environ["NEWSREC_DATABASE_URL"],
        event_mode="kafka_async",
        kafka_bootstrap_servers=bootstrap,
        kafka_profile_group_id=f"newsrec-test-profile-{suffix}",
        kafka_raw_events_topic=raw_topic,
        kafka_training_topic=training_topic,
        kafka_dlq_topic=dlq_topic,
    )
    producer = Producer({"bootstrap.servers": bootstrap})
    invalid_payload = (
        {
            "schema_version": 5,
            "event_id": f"invalid-cross-space-{suffix}",
            "event_type": "feed_impression",
            "user_id": 7,
            "source_space": "live",
            "article_id": "N12",
            "event_ts": int(time.time()),
        }
        if invalid_kind == "cross_space"
        else {
            "schema_version": None,
            "event_id": f"invalid-null-version-{suffix}",
            "event_type": "feed_impression",
            "user_id": 7,
            "source_space": "mind",
            "article_id": "N12",
            "event_ts": int(time.time()),
        }
    )
    producer.produce(
        raw_topic,
        key=(b"live:7" if invalid_kind == "cross_space" else b"7"),
        value=json.dumps(invalid_payload).encode(),
    )
    assert producer.flush(20) == 0

    run_profile_consumer(settings, max_messages=1)

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"newsrec-test-dlq-{suffix}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([dlq_topic])
    try:
        deadline = time.monotonic() + 20
        message = None
        while time.monotonic() < deadline and message is None:
            candidate = consumer.poll(1.0)
            if candidate is not None and not candidate.error():
                message = candidate
        assert message is not None
        dlq = DlqEventMessage.model_validate_json(message.value())
        assert dlq.original_topic == raw_topic
        assert dlq.error_type == "ValidationError"
        assert dlq.original_payload_encoding == "utf-8"
    finally:
        consumer.close()
