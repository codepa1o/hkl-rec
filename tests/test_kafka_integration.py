from __future__ import annotations

import os
import time
import uuid

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


def test_raw_event_reaches_postgres_and_training_topic(mysql_client, mysql_demo_user):
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
            NewTopic(raw_topic, num_partitions=1, replication_factor=1),
            NewTopic(training_topic, num_partitions=1, replication_factor=1),
            NewTopic(dlq_topic, num_partitions=1, replication_factor=1),
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
    feed = mysql_client.get(
        "/feed",
        params={
            "user_id": mysql_demo_user,
            "page_size": 1,
            "include_sponsored": "false",
        },
    ).json()
    answer_id = int(feed["items"][0]["article_id"])
    event = UserEventMessage(
        event_id=f"kafka-integration-{suffix}",
        event_type="feed_impression",
        user_id=mysql_demo_user,
        article_id=answer_id,
        request_id=f"kafka-request-{suffix}",
        surface="feed",
        event_ts=int(time.time()),
    )

    producer = Producer(
        {
            "bootstrap.servers": bootstrap,
            "enable.idempotence": True,
            "acks": "all",
        }
    )
    producer.produce(
        raw_topic,
        key=event.partition_key.encode(),
        value=event.to_json_bytes(),
    )
    assert producer.flush(20) == 0

    run_profile_consumer(settings, max_messages=1)
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
        message = None
        while time.monotonic() < deadline and message is None:
            candidate = consumer.poll(1.0)
            if candidate is not None and not candidate.error():
                message = candidate
        assert message is not None
        training = TrainingInteractionMessage.model_validate_json(message.value())
        assert training.example_id == event.event_id
        assert training.request_id == event.request_id
        assert training.article_id == answer_id
        assert training.label is None
    finally:
        consumer.close()


def test_invalid_raw_event_reaches_dlq():
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
            NewTopic(raw_topic, num_partitions=1, replication_factor=1),
            NewTopic(training_topic, num_partitions=1, replication_factor=1),
            NewTopic(dlq_topic, num_partitions=1, replication_factor=1),
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
    producer.produce(raw_topic, key=b"invalid", value=b"\xff\xfe")
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
        assert dlq.error_type == "ValueError"
        assert dlq.original_payload_encoding == "base64"
    finally:
        consumer.close()
