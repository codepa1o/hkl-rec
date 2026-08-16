from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_event_mode_defaults_to_sync_postgres():
    from backend.app.config import Settings

    settings = Settings()

    assert settings.event_mode == "sync_postgres"
    assert settings.kafka_enabled is False


def test_parse_event_mode_rejects_unknown_value():
    from backend.app.config import parse_event_mode

    with pytest.raises(ValueError, match="NEWSREC_EVENT_MODE"):
        parse_event_mode("definitely_not_a_mode")


def test_search_retrieval_defaults_to_hybrid():
    from backend.app.config import Settings

    assert Settings().search_retrieval_mode == "hybrid_v1"


def test_parse_search_retrieval_mode_rejects_unknown_value():
    from backend.app.config import parse_search_retrieval_mode

    with pytest.raises(ValueError):
        parse_search_retrieval_mode("semantic_magic")


def test_user_event_message_serializes_partition_key_and_optional_fields():
    from backend.app.events.schema import UserEventMessage

    event = UserEventMessage(
        event_id="evt-test",
        event_type="upvote",
        user_id=7248,
        news_id="N123",
        surface="home_feed",
        event_ts=1713399900,
    )

    assert event.partition_key == "7248"
    payload = event.model_dump(exclude_none=True)
    assert payload["schema_version"] == 4
    assert payload["event_id"] == "evt-test"
    assert payload["event_type"] == "upvote"
    assert "query_key" not in payload
    assert b'"event_id":"evt-test"' in event.to_json_bytes()


def test_event_fingerprint_ignores_retry_timestamps_but_detects_payload_conflicts():
    from backend.app.events.schema import UserEventMessage

    first = UserEventMessage(
        event_id="evt-stable",
        event_type="feed_impression",
        user_id=7248,
        news_id="N301",
        request_id="feed-1",
        event_ts=100,
        producer_ts=101,
    )
    retry = first.model_copy(update={"event_ts": 200, "producer_ts": 201})
    conflict = first.model_copy(update={"news_id": "N302"})

    assert first.idempotency_fingerprint == retry.idempotency_fingerprint
    assert first.idempotency_fingerprint != conflict.idempotency_fingerprint


def test_schema_v2_event_backlog_is_rejected_after_hard_cutover():
    from pydantic import ValidationError

    from backend.app.events.schema import UserEventMessage

    payload = {
        "schema_version": 2,
        "event_id": "evt-v2",
        "event_type": "feed_impression",
        "user_id": 7248,
        "answer_id": 301,
        "request_id": "feed-v2",
        "surface": "feed",
        "event_ts": 100,
        "producer_ts": 101,
        "source": "api",
    }
    with pytest.raises(ValidationError):
        UserEventMessage.model_validate(payload)


def test_schema_v2_training_message_is_rejected_after_hard_cutover():
    from pydantic import ValidationError

    from backend.app.events.schema import TrainingInteractionMessage

    with pytest.raises(ValidationError):
        TrainingInteractionMessage.model_validate(
            {
                "schema_version": 2,
                "example_id": "example-v2",
                "user_id": 7248,
                "answer_id": 301,
                "event_type": "feed_impression",
                "event_ts": 100,
            }
        )


def test_unknown_future_event_schema_is_rejected() -> None:
    from pydantic import ValidationError

    from backend.app.events.schema import UserEventMessage

    with pytest.raises(ValidationError):
        UserEventMessage(
            schema_version=5,
            event_type="search_query",
            user_id=7248,
            event_ts=100,
        )


def test_dwell_event_requires_bounded_duration():
    from pydantic import ValidationError

    from backend.app.events.schema import UserEventMessage

    with pytest.raises(ValidationError, match="requires dwell_ms"):
        UserEventMessage(
            event_type="dwell",
            user_id=7248,
            news_id="N301",
            event_ts=100,
        )
    with pytest.raises(ValidationError, match="between 0 and 86400000"):
        UserEventMessage(
            event_type="dwell",
            user_id=7248,
            news_id="N301",
            dwell_ms=-1,
            event_ts=100,
        )


def test_default_publisher_is_noop_when_kafka_disabled():
    from backend.app.config import Settings
    from backend.app.events.publisher import build_event_publisher
    from backend.app.events.schema import UserEventMessage

    publisher = build_event_publisher(Settings())
    publisher.publish_user_event(
        UserEventMessage(
            event_id="evt-noop",
            event_type="feed_impression",
            user_id=7248,
            news_id="N123",
            surface="feed",
            event_ts=1713399900,
        )
    )
    publisher.flush()


def test_event_publish_error_maps_to_503():
    from fastapi.testclient import TestClient

    from backend.app.events.publisher import EventPublishError
    from backend.app.main import create_app

    app = create_app()

    @app.get("/_raise_event_publish_error")
    def _raise_event_publish_error():
        raise EventPublishError("broker unavailable")

    response = TestClient(app).get("/_raise_event_publish_error")

    assert response.status_code == 503
    assert response.json()["error_code"] == "event_publish_failed"


def test_kafka_publisher_does_not_flush_per_message(monkeypatch):
    from backend.app.config import Settings
    from backend.app.events.publisher import KafkaEventPublisher
    from backend.app.events.schema import UserEventMessage

    class FakeMessage:
        def topic(self):
            return "newsrec.events.raw"

        def partition(self):
            return 0

    class FakeProducer:
        instance = None

        def __init__(self, config):
            self.config = config
            self.flush_calls = 0
            self.callbacks = []
            FakeProducer.instance = self

        def produce(self, topic, *, key, value, on_delivery):
            self.callbacks.append(on_delivery)

        def poll(self, timeout):
            return 0

        def flush(self, timeout):
            self.flush_calls += 1
            for callback in self.callbacks:
                callback(None, FakeMessage())
            self.callbacks.clear()
            return 0

    monkeypatch.setattr(
        "backend.app.events.publisher.importlib.import_module",
        lambda _name: SimpleNamespace(Producer=FakeProducer),
    )
    publisher = KafkaEventPublisher(Settings(event_mode="kafka_async"))
    publisher.publish_user_event(
        UserEventMessage(
            event_id="evt-batched",
            event_type="feed_impression",
            user_id=7248,
            news_id="N301",
            event_ts=1713399900,
        )
    )

    assert FakeProducer.instance.flush_calls == 0
    assert FakeProducer.instance.config["enable.idempotence"] is True
    publisher.flush()
    assert FakeProducer.instance.flush_calls == 1
