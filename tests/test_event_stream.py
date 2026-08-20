from __future__ import annotations

import json
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


def test_v5_live_user_event_serializes_canonical_identity_and_partition_key():
    from backend.app.events.schema import UserEventMessage

    event = UserEventMessage(
        event_id="evt-test",
        event_type="upvote",
        user_id=7001,
        source_space="live",
        article_id="L550e8400e29b41d4a716446655440000",
        surface="home_feed",
        event_ts=1713399900,
    )

    assert event.partition_key == "live:7001"
    payload = event.model_dump(exclude_none=True)
    assert payload["schema_version"] == 5
    assert payload["source_space"] == "live"
    assert payload["article_id"] == "L550e8400e29b41d4a716446655440000"
    assert "news_id" not in payload
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
        source_space="mind",
        article_id="N301",
        news_id="N301",
        request_id="feed-1",
        event_ts=100,
        producer_ts=101,
    )
    retry = first.model_copy(update={"event_ts": 200, "producer_ts": 201})
    changed_article = UserEventMessage(
        event_id="evt-stable",
        event_type="feed_impression",
        user_id=7248,
        source_space="mind",
        article_id="N302",
        news_id="N302",
        request_id="feed-1",
        event_ts=100,
        producer_ts=101,
    )
    changed_source = UserEventMessage(
        event_id="evt-stable",
        event_type="feed_impression",
        user_id=7248,
        source_space="live",
        article_id="L550e8400e29b41d4a716446655440000",
        request_id="feed-1",
        event_ts=100,
        producer_ts=101,
    )

    assert first.idempotency_fingerprint == retry.idempotency_fingerprint
    assert first.idempotency_fingerprint != changed_article.idempotency_fingerprint
    assert first.idempotency_fingerprint != changed_source.idempotency_fingerprint


@pytest.mark.parametrize(
    ("payload", "expected_article_id", "expected_news_id", "expected_fingerprint"),
    [
        (
            {"schema_version": 2, "answer_id": 301},
            "N301",
            None,
            "898864879a2d1059462d880dce7fcddc3f5805e342e25115d59b428a24abf715",
        ),
        (
            {"schema_version": 3, "article_id": 301},
            "N301",
            None,
            "9c03d55c5e1d9324915fb271bc6a53054abf3ca7613d246b93ce302e3e9e70d0",
        ),
        (
            {"schema_version": 4, "news_id": "N301"},
            "N301",
            "N301",
            "9ac4045281fa09659177cf5ca2c39a987b7d05fffbfcf1bcdcbd5030abe09cc6",
        ),
    ],
)
def test_authentic_legacy_event_fixtures_preserve_historical_fingerprints(
    payload: dict[str, object],
    expected_article_id: str,
    expected_news_id: str | None,
    expected_fingerprint: str,
) -> None:
    from backend.app.events.schema import UserEventMessage

    serialized = json.dumps(
        {
            **payload,
            "event_id": f"evt-v{payload['schema_version']}",
            "event_type": "feed_impression",
            "user_id": 7248,
            "request_id": "feed-historical",
            "surface": "feed",
            "event_ts": 100,
            "producer_ts": 101,
            "source": "api",
        }
    )
    event = UserEventMessage.model_validate_json(serialized)

    assert event.source_space == "mind"
    assert event.article_id == expected_article_id
    assert event.news_id == expected_news_id
    assert event.partition_key == "mind:7248"
    assert event.idempotency_fingerprint == expected_fingerprint


@pytest.mark.parametrize(
    ("payload", "identity_key", "identity_value", "expected_fingerprint"),
    [
        (
            {"schema_version": 2, "answer_id": 301},
            "answer_id",
            301,
            "898864879a2d1059462d880dce7fcddc3f5805e342e25115d59b428a24abf715",
        ),
        (
            {"schema_version": 3, "article_id": 301},
            "article_id",
            301,
            "9c03d55c5e1d9324915fb271bc6a53054abf3ca7613d246b93ce302e3e9e70d0",
        ),
        (
            {"schema_version": 4, "news_id": "N301"},
            "news_id",
            "N301",
            "9ac4045281fa09659177cf5ca2c39a987b7d05fffbfcf1bcdcbd5030abe09cc6",
        ),
    ],
)
def test_authentic_legacy_wire_roundtrip_preserves_identity_and_fingerprint(
    payload: dict[str, object],
    identity_key: str,
    identity_value: object,
    expected_fingerprint: str,
) -> None:
    from backend.app.events.schema import UserEventMessage

    event = UserEventMessage.model_validate(
        {
            **payload,
            "event_id": f"evt-v{payload['schema_version']}",
            "event_type": "feed_impression",
            "user_id": 7248,
            "request_id": "feed-historical",
            "surface": "feed",
            "event_ts": 100,
            "producer_ts": 101,
            "source": "api",
        }
    )
    wire = json.loads(event.to_json_bytes())

    assert wire[identity_key] == identity_value
    assert "source_space" not in wire
    assert set(wire).isdisjoint(
        {key for key in {"answer_id", "article_id", "news_id"} if key != identity_key}
    )
    roundtrip = UserEventMessage.model_validate_json(event.to_json_bytes())
    assert roundtrip.article_id == "N301"
    assert roundtrip.idempotency_fingerprint == event.idempotency_fingerprint
    assert roundtrip.idempotency_fingerprint == expected_fingerprint


@pytest.mark.parametrize(
    ("authoritative", "injected", "expected_fingerprint"),
    [
        (
            {"schema_version": 2, "answer_id": 301},
            {"article_id": 999, "news_id": "N999", "source_space": "live"},
            "898864879a2d1059462d880dce7fcddc3f5805e342e25115d59b428a24abf715",
        ),
        (
            {"schema_version": 3, "article_id": 301},
            {"answer_id": 999, "news_id": "N999", "source_space": "live"},
            "9c03d55c5e1d9324915fb271bc6a53054abf3ca7613d246b93ce302e3e9e70d0",
        ),
        (
            {"schema_version": 4, "news_id": "N301"},
            {
                "answer_id": 999,
                "article_id": "L550e8400e29b41d4a716446655440000",
                "source_space": "live",
            },
            "9ac4045281fa09659177cf5ca2c39a987b7d05fffbfcf1bcdcbd5030abe09cc6",
        ),
    ],
)
def test_legacy_identity_rejects_later_version_field_injection(
    authoritative: dict[str, object],
    injected: dict[str, object],
    expected_fingerprint: str,
) -> None:
    from backend.app.events.schema import UserEventMessage

    event = UserEventMessage.model_validate(
        {
            **authoritative,
            **injected,
            "event_id": f"evt-v{authoritative['schema_version']}",
            "event_type": "feed_impression",
            "user_id": 7248,
            "request_id": "feed-historical",
            "surface": "feed",
            "event_ts": 100,
            "producer_ts": 101,
            "source": "api",
        }
    )

    assert event.source_space == "mind"
    assert event.article_id == "N301"
    assert event.idempotency_fingerprint == expected_fingerprint


@pytest.mark.parametrize("schema_version", [None, [], {}])
def test_malformed_schema_version_is_a_validation_error(schema_version: object) -> None:
    from pydantic import ValidationError

    from backend.app.events.schema import UserEventMessage

    with pytest.raises((ValidationError, ValueError)):
        UserEventMessage.model_validate(
            {
                "schema_version": schema_version,
                "event_type": "feed_impression",
                "user_id": 7248,
                "news_id": "N301",
                "event_ts": 100,
            }
        )


def _legacy_v4_article_event_without_news_id() -> dict[str, object]:
    return {
        "schema_version": 4,
        "event_type": "feed_impression",
        "user_id": 7248,
        "event_ts": 100,
    }


def test_v5_requires_source_space_but_v4_migrates_it() -> None:
    from pydantic import ValidationError

    from backend.app.events.schema import UserEventMessage

    with pytest.raises(ValidationError):
        UserEventMessage(
            schema_version=5,
            event_type="search_query",
            user_id=7248,
            event_ts=100,
        )
    migrated = UserEventMessage.model_validate(
        {
            "schema_version": 4,
            "event_type": "feed_impression",
            "user_id": 7248,
            "news_id": "N301",
            "event_ts": 100,
        }
    )
    assert migrated.source_space == "mind"
    assert migrated.article_id == "N301"


def test_legacy_identity_ignores_injected_v5_space_and_article_fields() -> None:
    from backend.app.events.schema import UserEventMessage

    payload = {
        "schema_version": 4,
        "event_type": "feed_impression",
        "user_id": 7,
        "news_id": "N301",
        "source_space": "live",
        "event_ts": 100,
    }
    first = UserEventMessage.model_validate(
        {**payload, "article_id": "L550e8400e29b41d4a716446655440000"}
    )
    second = UserEventMessage.model_validate({**payload, "article_id": "N999"})

    assert first.source_space == second.source_space == "mind"
    assert first.article_id == second.article_id == "N301"
    assert first.idempotency_fingerprint == second.idempotency_fingerprint


def test_legacy_article_event_rejects_injected_article_without_news_id() -> None:
    from pydantic import ValidationError

    from backend.app.events.schema import UserEventMessage

    with pytest.raises(ValidationError, match="requires article_id"):
        UserEventMessage.model_validate(
            {
                **_legacy_v4_article_event_without_news_id(),
                "user_id": 7,
                "source_space": "live",
                "article_id": "L550e8400e29b41d4a716446655440000",
                "event_ts": 100,
            }
        )


def test_v5_mind_requires_canonical_article_even_with_legacy_alias() -> None:
    from pydantic import ValidationError

    from backend.app.events.schema import UserEventMessage

    with pytest.raises(ValidationError, match="requires canonical article_id"):
        UserEventMessage(
            event_type="feed_impression",
            user_id=7,
            source_space="mind",
            news_id="N301",
            event_ts=100,
        )
    with pytest.raises(ValidationError, match="requires canonical article_id"):
        UserEventMessage(
            event_type="search_query",
            user_id=7,
            source_space="mind",
            news_id="N301",
            query_key="ai",
            event_ts=100,
        )
    accepted = UserEventMessage(
        event_type="feed_impression",
        user_id=7,
        source_space="mind",
        article_id="N301",
        news_id="N301",
        event_ts=100,
    )
    assert accepted.article_id == accepted.news_id == "N301"
    with pytest.raises(ValidationError, match="must match"):
        UserEventMessage(
            event_type="feed_impression",
            user_id=7,
            source_space="mind",
            article_id="N301",
            news_id="N302",
            event_ts=100,
        )


@pytest.mark.parametrize(
    ("source_space", "article_id", "news_id"),
    [
        ("mind", "L550e8400e29b41d4a716446655440000", None),
        ("live", "N301", None),
        ("live", "L550e8400e29b41d4a716446655440000", "N301"),
    ],
)
def test_v5_rejects_cross_space_article_identity(
    source_space: str,
    article_id: str,
    news_id: str | None,
) -> None:
    from pydantic import ValidationError

    from backend.app.events.schema import UserEventMessage

    with pytest.raises(ValidationError):
        UserEventMessage(
            event_type="feed_impression",
            user_id=7248,
            source_space=source_space,
            article_id=article_id,
            news_id=news_id,
            event_ts=100,
        )


def test_article_events_require_article_id_but_search_query_may_omit_it() -> None:
    from pydantic import ValidationError

    from backend.app.events.schema import UserEventMessage

    with pytest.raises(ValidationError, match="requires article_id"):
        UserEventMessage(
            event_type="outbound_click",
            user_id=7248,
            source_space="mind",
            event_ts=100,
        )
    event = UserEventMessage(
        event_type="search_query",
        user_id=7248,
        source_space="live",
        query_key="ai",
        event_ts=100,
    )
    assert event.article_id is None


@pytest.mark.parametrize("event_type", ["search_query", "search_result_click"])
def test_query_events_require_query_key_during_message_validation(event_type: str) -> None:
    from pydantic import ValidationError

    from backend.app.events.schema import UserEventMessage

    values: dict[str, object] = {
        "event_type": event_type,
        "user_id": 7,
        "source_space": "mind",
        "event_ts": 100,
    }
    if event_type == "search_query":
        values["query_text"] = "artificial intelligence"
    else:
        values["article_id"] = "N301"
    with pytest.raises(ValidationError, match="requires query_key"):
        UserEventMessage.model_validate(values)


def test_training_interaction_v5_carries_space_article_and_partition_key() -> None:
    from backend.app.events.schema import TrainingInteractionMessage

    message = TrainingInteractionMessage(
        example_id="evt-training",
        user_id=7001,
        source_space="live",
        article_id="L550e8400e29b41d4a716446655440000",
        event_type="feed_impression",
        event_ts=100,
    )

    assert message.schema_version == 5
    assert message.partition_key == "live:7001"
    assert message.model_dump(exclude_none=True)["article_id"].startswith("L")


@pytest.mark.parametrize(
    "sponsored_fields",
    [
        {"sponsored_delivery_id": "delivery-live"},
        {"campaign_id": 10},
        {"creative_id": 20},
    ],
)
def test_live_raw_events_reject_mind_sponsored_identity(
    sponsored_fields: dict[str, object],
) -> None:
    from pydantic import ValidationError

    from backend.app.events.schema import UserEventMessage

    with pytest.raises(ValidationError, match="Sponsored identity is only supported"):
        UserEventMessage(
            event_type="recommendation_click",
            user_id=7,
            source_space="live",
            article_id="L550e8400e29b41d4a716446655440000",
            event_ts=100,
            **sponsored_fields,
        )


def test_live_training_interactions_reject_mind_sponsored_identity() -> None:
    from pydantic import ValidationError

    from backend.app.events.schema import TrainingInteractionMessage

    with pytest.raises(ValidationError, match="Sponsored identity is only supported"):
        TrainingInteractionMessage(
            example_id="evt-live-sponsored",
            user_id=7,
            source_space="live",
            article_id="L550e8400e29b41d4a716446655440000",
            sponsored_delivery_id="delivery-live",
            campaign_id=10,
            creative_id=20,
            event_type="recommendation_click",
            event_ts=100,
        )


def test_live_api_event_models_reject_mind_sponsored_delivery() -> None:
    from pydantic import ValidationError

    from backend.app.schemas.event import RecommendationClickRequest, SearchResultClickRequest
    from backend.app.schemas.event_track import EventTrackRequest

    live_article_id = "L550e8400e29b41d4a716446655440000"
    constructors = (
        lambda: RecommendationClickRequest(
            user_id=7,
            source_space="live",
            article_id=live_article_id,
            sponsored_delivery_id="delivery-live",
        ),
        lambda: SearchResultClickRequest(
            user_id=7,
            source_space="live",
            article_id=live_article_id,
            query_key="ai",
            sponsored_delivery_id="delivery-live",
        ),
        lambda: EventTrackRequest(
            user_id=7,
            source_space="live",
            article_id=live_article_id,
            event_type="recommendation_click",
            surface="feed",
            sponsored_delivery_id="delivery-live",
        ),
    )
    for construct in constructors:
        with pytest.raises(ValidationError, match="Sponsored identity is only supported"):
            construct()


def test_publish_partition_key_supports_safe_mind_rollout_boundary() -> None:
    from backend.app.events.schema import TrainingInteractionMessage, UserEventMessage

    mind = UserEventMessage(
        event_type="feed_impression",
        user_id=7001,
        source_space="mind",
        article_id="N301",
        event_ts=100,
    )
    live = UserEventMessage(
        event_type="feed_impression",
        user_id=7001,
        source_space="live",
        article_id="L550e8400e29b41d4a716446655440000",
        event_ts=100,
    )
    training = TrainingInteractionMessage(
        example_id="evt-training-key",
        user_id=7001,
        source_space="mind",
        article_id="N301",
        event_type="feed_impression",
        event_ts=100,
    )

    assert mind.partition_key == "mind:7001"
    assert mind.publish_partition_key(False) == "7001"
    assert mind.publish_partition_key(True) == "mind:7001"
    assert live.publish_partition_key(False) == "live:7001"
    assert live.publish_partition_key(True) == "live:7001"
    assert training.publish_partition_key(False) == "7001"
    assert training.publish_partition_key(True) == "mind:7001"


def test_event_request_models_normalize_mind_aliases_and_validate_live_ids() -> None:
    from pydantic import ValidationError

    from backend.app.schemas.event import RecommendationClickRequest, SearchResultClickRequest

    legacy = RecommendationClickRequest(user_id=7, news_id="N12")
    assert legacy.source_space == "mind"
    assert legacy.article_id == legacy.news_id == "N12"
    live = SearchResultClickRequest(
        user_id=7,
        source_space="live",
        article_id="L550e8400e29b41d4a716446655440000",
        query_key="ai",
    )
    assert live.news_id is None
    with pytest.raises(ValidationError):
        RecommendationClickRequest(
            user_id=7,
            source_space="live",
            article_id="N12",
        )


@pytest.mark.parametrize("model_kind", ["recommendation", "search", "track"])
def test_api_article_alias_matrix_is_consistent(model_kind: str) -> None:
    from pydantic import ValidationError

    from backend.app.schemas.event import RecommendationClickRequest, SearchResultClickRequest
    from backend.app.schemas.event_track import EventTrackRequest

    def build(**identity: object):
        if model_kind == "recommendation":
            return RecommendationClickRequest(user_id=7, **identity)
        if model_kind == "search":
            return SearchResultClickRequest(user_id=7, query_key="ai", **identity)
        return EventTrackRequest(
            user_id=7,
            event_type="recommendation_click",
            surface="feed",
            **identity,
        )

    legacy = build(news_id="N301")
    assert legacy.source_space == "mind"
    assert legacy.article_id == legacy.news_id == "N301"
    canonical = build(article_id="N301")
    assert canonical.article_id == canonical.news_id == "N301"
    live = build(
        source_space="live",
        article_id="L550e8400e29b41d4a716446655440000",
    )
    assert live.news_id is None
    with pytest.raises(ValidationError, match="must match"):
        build(article_id="N301", news_id="N302")
    with pytest.raises(ValidationError, match="only supported"):
        build(
            source_space="live",
            article_id="L550e8400e29b41d4a716446655440000",
            news_id="N301",
        )


def test_event_track_accepts_outbound_click_as_log_only_contract() -> None:
    from backend.app.schemas.event_track import EventTrackRequest

    event = EventTrackRequest(
        user_id=7,
        event_type="outbound_click",
        surface="detail",
        source_space="live",
        article_id="L550e8400e29b41d4a716446655440000",
    )

    assert event.article_id.startswith("L")
    assert event.news_id is None


def test_postgres_event_factory_requires_canonical_space_identity() -> None:
    from backend.app.repositories.postgres import PostgresRuntimeRepository

    repository = object.__new__(PostgresRuntimeRepository)
    event = repository._event_message(
        event_type="outbound_click",
        user_id=7001,
        source_space="live",
        article_id="L550e8400e29b41d4a716446655440000",
        event_ts=100,
    )

    assert event.source_space == "live"
    assert event.article_id == "L550e8400e29b41d4a716446655440000"


def test_dwell_event_requires_bounded_duration():
    from pydantic import ValidationError

    from backend.app.events.schema import UserEventMessage

    with pytest.raises(ValidationError, match="requires dwell_ms"):
        UserEventMessage(
            event_type="dwell",
            user_id=7248,
            source_space="mind",
            article_id="N301",
            news_id="N301",
            event_ts=100,
        )
    with pytest.raises(ValidationError, match="between 0 and 86400000"):
        UserEventMessage(
            event_type="dwell",
            user_id=7248,
            source_space="mind",
            article_id="N301",
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
            source_space="mind",
            article_id="N123",
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
            source_space="mind",
            article_id="N301",
            news_id="N301",
            event_ts=1713399900,
        )
    )

    assert FakeProducer.instance.flush_calls == 0
    assert FakeProducer.instance.config["enable.idempotence"] is True
    publisher.flush()
    assert FakeProducer.instance.flush_calls == 1


@pytest.mark.parametrize(
    ("source_space", "article_id", "source_keys_enabled", "expected_key"),
    [
        ("mind", "N301", False, b"7248"),
        ("mind", "N301", True, b"mind:7248"),
        ("live", "L550e8400e29b41d4a716446655440000", False, b"live:7248"),
        ("live", "L550e8400e29b41d4a716446655440000", True, b"live:7248"),
    ],
)
def test_kafka_publisher_uses_rollout_partition_key(
    monkeypatch: pytest.MonkeyPatch,
    source_space: str,
    article_id: str,
    source_keys_enabled: bool,
    expected_key: bytes,
) -> None:
    from backend.app.config import Settings
    from backend.app.events.publisher import KafkaEventPublisher
    from backend.app.events.schema import UserEventMessage

    class FakeProducer:
        instance = None

        def __init__(self, config):
            self.keys: list[bytes] = []
            FakeProducer.instance = self

        def produce(self, topic, *, key, value, on_delivery):
            self.keys.append(key)

        def poll(self, timeout):
            return 0

        def flush(self, timeout):
            return 0

    monkeypatch.setattr(
        "backend.app.events.publisher.importlib.import_module",
        lambda _name: SimpleNamespace(Producer=FakeProducer),
    )
    publisher = KafkaEventPublisher(
        Settings(
            event_mode="kafka_async",
            kafka_source_partition_keys_enabled=source_keys_enabled,
        )
    )
    publisher.publish_user_event(
        UserEventMessage(
            event_type="feed_impression",
            user_id=7248,
            source_space=source_space,
            article_id=article_id,
            event_ts=100,
        )
    )

    assert FakeProducer.instance.keys == [expected_key]


def test_valid_event_application_type_error_retries_without_dlq_or_poison_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.config import Settings
    from backend.app.events import consumer as consumer_module
    from backend.app.events.consumer import run_profile_consumer
    from backend.app.events.schema import UserEventMessage

    event = UserEventMessage(
        event_id="evt-transient-type-error",
        event_type="feed_impression",
        user_id=7,
        source_space="mind",
        article_id="N301",
        event_ts=100,
    )

    class FakeMessage:
        def error(self):
            return None

        def topic(self):
            return "newsrec.test.raw.type-error"

        def partition(self):
            return 0

        def offset(self):
            return 0

        def value(self):
            return event.to_json_bytes()

    class FakeConsumer:
        instance = None

        def __init__(self, config):
            self.commit_calls = 0
            self.closed = False
            FakeConsumer.instance = self

        def subscribe(self, topics):
            return None

        def poll(self, timeout):
            return FakeMessage()

        def get_watermark_offsets(self, topic_partition, cached=False):
            return (0, 1)

        def commit(self, **kwargs):
            self.commit_calls += 1

        def close(self):
            self.closed = True

    class FakePublisher:
        def __init__(self) -> None:
            self.dlq_calls = 0
            self.flush_calls = 0

        def publish_dlq_event(self, message):
            self.dlq_calls += 1

        def flush(self):
            self.flush_calls += 1

    class FailingApplier:
        instance = None

        def __init__(self, settings):
            self.apply_calls = 0
            self.heartbeats: list[dict[str, object]] = []
            FailingApplier.instance = self

        def apply_event(self, parsed_event):
            self.apply_calls += 1
            raise TypeError("database adapter type mismatch")

        def update_heartbeat(self, **kwargs):
            self.heartbeats.append(kwargs)

    publisher = FakePublisher()
    monkeypatch.setattr(
        consumer_module.importlib,
        "import_module",
        lambda _name: SimpleNamespace(
            Consumer=FakeConsumer,
            TopicPartition=lambda topic, partition: (topic, partition),
        ),
    )
    monkeypatch.setattr(consumer_module, "build_event_publisher", lambda *args, **kwargs: publisher)
    monkeypatch.setattr(consumer_module, "ProfileEventApplier", FailingApplier)
    monkeypatch.setattr(consumer_module.time, "sleep", lambda _delay: None)

    with pytest.raises(TypeError, match="database adapter"):
        run_profile_consumer(
            Settings(
                event_mode="kafka_async",
                kafka_consumer_max_retries=1,
                kafka_consumer_retry_backoff_seconds=0,
            ),
            max_messages=1,
        )

    assert FailingApplier.instance.apply_calls == 2
    assert publisher.dlq_calls == 0
    assert publisher.flush_calls == 1  # final publisher shutdown only, not a DLQ flush
    assert FakeConsumer.instance.commit_calls == 0
    assert FakeConsumer.instance.closed is True


@pytest.mark.parametrize(
    ("error_name", "error_message"),
    [
        ("IdempotencyConflictError", "event_id reused with conflicting payload"),
        ("InvalidSponsoredAttributionError", "unknown sponsored delivery"),
    ],
)
def test_deterministic_event_conflict_is_dlqed_and_committed_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    error_name: str,
    error_message: str,
) -> None:
    from backend.app.config import Settings
    from backend.app.errors import IdempotencyConflictError, InvalidSponsoredAttributionError
    from backend.app.events import consumer as consumer_module
    from backend.app.events.consumer import run_profile_consumer
    from backend.app.events.schema import UserEventMessage

    event = UserEventMessage(
        event_id="evt-conflicting-reuse",
        event_type="feed_impression",
        user_id=7,
        source_space="mind",
        article_id="N301",
        event_ts=100,
    )

    class FakeMessage:
        def error(self):
            return None

        def topic(self):
            return "newsrec.test.raw.conflict"

        def partition(self):
            return 0

        def offset(self):
            return 0

        def value(self):
            return event.to_json_bytes()

    class FakeConsumer:
        instance = None

        def __init__(self, config):
            self.commit_calls = 0
            FakeConsumer.instance = self

        def subscribe(self, topics):
            return None

        def poll(self, timeout):
            return FakeMessage()

        def get_watermark_offsets(self, topic_partition, cached=False):
            return (0, 1)

        def commit(self, **kwargs):
            self.commit_calls += 1

        def close(self):
            return None

    class FakePublisher:
        def __init__(self) -> None:
            self.dlq_errors: list[str] = []
            self.flush_calls = 0

        def publish_dlq_event(self, message):
            self.dlq_errors.append(message.error_type)

        def flush(self):
            self.flush_calls += 1

    class ConflictApplier:
        instance = None

        def __init__(self, settings):
            self.apply_calls = 0
            self.heartbeats: list[dict[str, object]] = []
            ConflictApplier.instance = self

        def apply_event(self, parsed_event):
            self.apply_calls += 1
            error_type = {
                "IdempotencyConflictError": IdempotencyConflictError,
                "InvalidSponsoredAttributionError": InvalidSponsoredAttributionError,
            }[error_name]
            raise error_type(error_message)

        def update_heartbeat(self, **kwargs):
            self.heartbeats.append(kwargs)

    publisher = FakePublisher()
    monkeypatch.setattr(
        consumer_module.importlib,
        "import_module",
        lambda _name: SimpleNamespace(
            Consumer=FakeConsumer,
            TopicPartition=lambda topic, partition: (topic, partition),
        ),
    )
    monkeypatch.setattr(consumer_module, "build_event_publisher", lambda *args, **kwargs: publisher)
    monkeypatch.setattr(consumer_module, "ProfileEventApplier", ConflictApplier)
    monkeypatch.setattr(
        consumer_module.time,
        "sleep",
        lambda _delay: pytest.fail("idempotency conflicts must not retry"),
    )

    run_profile_consumer(Settings(event_mode="kafka_async"), max_messages=1)

    assert ConflictApplier.instance.apply_calls == 1
    assert publisher.dlq_errors == [error_name]
    assert publisher.flush_calls == 2  # conflict DLQ + final shutdown
    assert FakeConsumer.instance.commit_calls == 1
