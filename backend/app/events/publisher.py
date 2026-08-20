from __future__ import annotations

import importlib
from typing import Any, Protocol, cast

from backend.app.config import Settings
from backend.app.events.schema import (
    DlqEventMessage,
    TrainingInteractionMessage,
    UserEventMessage,
)


class EventPublishError(RuntimeError):
    pass


class EventPublisher(Protocol):
    def publish_payload(self, topic: str, key: str, value: bytes) -> None: ...

    def publish_user_event(self, event: UserEventMessage) -> None: ...

    def publish_training_interaction(self, message: TrainingInteractionMessage) -> None: ...

    def publish_dlq_event(self, message: DlqEventMessage) -> None: ...

    def flush(self) -> None: ...


class NoopEventPublisher:
    def publish_payload(self, topic: str, key: str, value: bytes) -> None:
        return None

    def publish_user_event(self, event: UserEventMessage) -> None:
        return None

    def publish_training_interaction(self, message: TrainingInteractionMessage) -> None:
        return None

    def publish_dlq_event(self, message: DlqEventMessage) -> None:
        return None

    def flush(self) -> None:
        return None


class KafkaEventPublisher:
    def __init__(self, settings: Settings, *, client_id: str | None = None) -> None:
        confluent_kafka = cast(Any, importlib.import_module("confluent_kafka"))
        producer_cls = confluent_kafka.Producer
        self._producer: Any = producer_cls(
            {
                "bootstrap.servers": settings.kafka_bootstrap_servers,
                "client.id": client_id or settings.kafka_client_id,
                "enable.idempotence": True,
                "acks": "all",
                "linger.ms": settings.kafka_producer_linger_ms,
            }
        )
        self._raw_topic = settings.kafka_raw_events_topic
        self._training_topic = settings.kafka_training_topic
        self._dlq_topic = settings.kafka_dlq_topic
        self._source_partition_keys_enabled = settings.kafka_source_partition_keys_enabled
        self._flush_timeout_seconds = settings.kafka_producer_flush_timeout_seconds
        self._delivery_errors: list[str] = []

    def publish_payload(self, topic: str, key: str, value: bytes) -> None:
        self._produce(topic, key, value)

    def publish_user_event(self, event: UserEventMessage) -> None:
        self._produce(
            self._raw_topic,
            event.publish_partition_key(self._source_partition_keys_enabled),
            event.to_json_bytes(),
        )

    def publish_training_interaction(self, message: TrainingInteractionMessage) -> None:
        self._produce(
            self._training_topic,
            message.publish_partition_key(self._source_partition_keys_enabled),
            message.to_json_bytes(),
        )

    def publish_dlq_event(self, message: DlqEventMessage) -> None:
        self._produce(self._dlq_topic, message.partition_key, message.to_json_bytes())

    def flush(self) -> None:
        remaining = self._producer.flush(self._flush_timeout_seconds)
        if remaining:
            raise EventPublishError(f"Kafka producer flush left {remaining} message(s) undelivered")
        if self._delivery_errors:
            errors = "; ".join(self._delivery_errors)
            self._delivery_errors.clear()
            raise EventPublishError(f"Kafka delivery failed: {errors}")

    def _produce(self, topic: str, key: str, value: bytes) -> None:
        try:
            self._producer.produce(
                topic,
                key=key.encode("utf-8"),
                value=value,
                on_delivery=self._on_delivery,
            )
            self._producer.poll(0)
        except BufferError:
            self._producer.poll(0.1)
            try:
                self._producer.produce(
                    topic,
                    key=key.encode("utf-8"),
                    value=value,
                    on_delivery=self._on_delivery,
                )
            except Exception as exc:
                raise EventPublishError(f"Kafka producer queue is full for {topic}") from exc
        except Exception as exc:
            raise EventPublishError(f"failed to publish Kafka event to {topic}") from exc

    def _on_delivery(self, error: Any, message: Any) -> None:
        if error is not None:
            self._delivery_errors.append(f"{message.topic()}[{message.partition()}]: {error}")


def build_event_publisher(settings: Settings, *, client_id: str | None = None) -> EventPublisher:
    if not settings.kafka_enabled:
        return NoopEventPublisher()
    try:
        return KafkaEventPublisher(settings, client_id=client_id)
    except ModuleNotFoundError as exc:
        raise EventPublishError(
            "Kafka event mode requires the confluent-kafka package to be installed"
        ) from exc
