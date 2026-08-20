from __future__ import annotations

import base64
import importlib
import logging
import time
from typing import Any, Literal, cast

from pydantic import ValidationError

from backend.app.config import Settings, get_settings
from backend.app.errors import IdempotencyConflictError
from backend.app.events.outbox import enqueue_outbox_message, outbox_message_exists
from backend.app.events.publisher import build_event_publisher
from backend.app.events.schema import (
    DlqEventMessage,
    TrainingInteractionMessage,
    UserEventMessage,
)
from backend.app.events.worker_state import update_worker_heartbeat
from backend.app.observability import (
    CONSUMER_EVENTS,
    CONSUMER_LAG,
    CONSUMER_RETRIES,
    PROFILE_V2_LATE_EVENTS,
    PROFILE_V2_PROJECTION_DURATION,
    PROFILE_V2_PROJECTION_UPDATES,
)
from backend.app.profiles.signals import topic_strengths_for_event
from backend.app.repositories._utils import json_text
from backend.app.repositories.connection import PostgresConnectionPool, parse_database_url
from backend.app.repositories.content_dao import load_news_topic_ids, load_query_topics
from backend.app.repositories.event_dao import (
    append_recent_query,
    apply_click_profile_update,
    claim_event_id,
    confirm_recent_query,
    record_click_event,
    record_log_only_event,
    record_search_query,
)
from backend.app.repositories.profile_dao import fetch_profile_row
from backend.app.repositories.profile_v2_dao import (
    apply_profile_v2_event_with_outcome,
    profile_event_is_before_reset,
    profile_signal_config,
)
from backend.app.repositories.sponsored_dao import (
    confirm_sponsored_impression,
    load_sponsored_attribution,
    record_sponsored_click,
)

logger = logging.getLogger(__name__)

LOG_ONLY_EVENTS = {
    "feed_impression",
    "detail_view",
    "dwell",
    "downvote",
    "share",
    "outbound_click",
}


class ProfileEventApplier:
    def __init__(
        self,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if not self._settings.database_url.strip():
            raise ValueError("NEWSREC_DATABASE_URL is required for the profile consumer")
        self._connection_config = parse_database_url(self._settings.database_url)
        self._connection_pool = PostgresConnectionPool(
            self._connection_config,
            connect_timeout=self._settings.postgres_connect_timeout_seconds,
            min_size=self._settings.postgres_pool_min_size,
            max_connections=self._settings.postgres_pool_max_connections,
        )

    def apply_event(self, event: UserEventMessage) -> bool:
        connection = self._connection_pool.connect()
        try:
            connection.begin()
            claimed = claim_event_id(connection, event, source_space=event.source_space)
            if claimed:
                project_profile = not profile_event_is_before_reset(
                    connection,
                    user_id=event.user_id,
                    event_ts=event.event_ts,
                    source_space=event.source_space,
                )
                if not project_profile and self._settings.profile_v2_enabled:
                    PROFILE_V2_LATE_EVENTS.labels(reason="pre_reset").inc()
                if event.event_type == "search_query":
                    self._apply_search_query(
                        connection,
                        event,
                        project_profile=project_profile,
                    )
                elif event.event_type == "recommendation_click":
                    self._apply_recommendation_click(
                        connection,
                        event,
                        project_profile=project_profile,
                    )
                elif event.event_type == "search_result_click":
                    self._apply_search_result_click(
                        connection,
                        event,
                        project_profile=project_profile,
                    )
                elif event.event_type == "upvote":
                    self._apply_upvote(
                        connection,
                        event,
                        project_profile=project_profile,
                    )
                elif event.event_type in LOG_ONLY_EVENTS:
                    self._apply_log_only(
                        connection,
                        event,
                        project_profile=project_profile,
                    )
                else:
                    raise ValueError(f"unsupported event_type: {event.event_type}")

            training = self._training_message(event)
            training_exists = (
                training is not None
                and not claimed
                and outbox_message_exists(
                    connection,
                    event_id=training.example_id,
                    topic=self._settings.kafka_training_topic,
                )
            )
            if training is not None and not training_exists:
                enqueue_outbox_message(
                    connection,
                    event_id=training.example_id,
                    topic=self._settings.kafka_training_topic,
                    message_key=training.publish_partition_key(
                        self._settings.kafka_source_partition_keys_enabled
                    ),
                    payload_json=training.model_dump_json(exclude_none=True),
                )
            connection.commit()
            return bool(claimed)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update_heartbeat(
        self,
        *,
        made_progress: bool,
        lag_messages: int,
        last_error: str | None = None,
    ) -> None:
        connection = self._connection_pool.connect()
        try:
            update_worker_heartbeat(
                connection,
                worker_name="profile-consumer",
                made_progress=made_progress,
                lag_messages=lag_messages,
                last_error=last_error,
            )
        finally:
            connection.close()

    def _apply_search_query(
        self,
        connection: Any,
        event: UserEventMessage,
        *,
        project_profile: bool = True,
    ) -> None:
        if not event.query_key:
            raise ValueError("search_query event requires query_key")
        record_search_query(
            connection=connection,
            user_id=event.user_id,
            query_key=event.query_key,
            event_ts=event.event_ts,
            external_event_id=event.event_id,
            source_space=event.source_space,
        )
        if not project_profile:
            return
        profile_row = fetch_profile_row(
            connection,
            event.user_id,
            event.source_space,
            for_update=True,
        )
        append_recent_query(
            connection=connection,
            profile_row=profile_row,
            query_key=event.query_key,
            event_ts=event.event_ts,
            behavior_delta=self._settings.search_query_behavior_delta,
            source_space=event.source_space,
        )

    def _apply_recommendation_click(
        self,
        connection: Any,
        event: UserEventMessage,
        *,
        project_profile: bool = True,
    ) -> None:
        if event.article_id is None:
            raise ValueError("recommendation_click event requires article_id")
        self._apply_news_click(
            connection=connection,
            event=event,
            event_type="recommendation_click",
            surface=event.surface or "feed",
            behavior_delta=self._settings.recommendation_click_behavior_delta,
            topic_delta=self._settings.recommendation_click_topic_delta,
            project_profile=project_profile,
        )

    def _apply_upvote(
        self,
        connection: Any,
        event: UserEventMessage,
        *,
        project_profile: bool = True,
    ) -> None:
        if event.article_id is None:
            raise ValueError("upvote event requires article_id")
        self._apply_news_click(
            connection=connection,
            event=event,
            event_type="upvote",
            surface=event.surface or "home_feed",
            behavior_delta=self._settings.recommendation_click_behavior_delta,
            topic_delta=self._settings.recommendation_click_topic_delta,
            project_profile=project_profile,
        )

    def _apply_search_result_click(
        self,
        connection: Any,
        event: UserEventMessage,
        *,
        project_profile: bool = True,
    ) -> None:
        if event.article_id is None or not event.query_key:
            raise ValueError("search_result_click event requires article_id and query_key")
        profile_row = (
            fetch_profile_row(
                connection,
                event.user_id,
                event.source_space,
                for_update=True,
            )
            if project_profile
            else None
        )
        sponsored_attribution = (
            load_sponsored_attribution(
                connection,
                delivery_id=event.sponsored_delivery_id,
                user_id=event.user_id,
                news_id=event.article_id,
                for_update=True,
            )
            if event.source_space == "mind" and event.sponsored_delivery_id
            else None
        )
        query_topics = (
            load_query_topics(connection, event.query_key) if event.source_space == "mind" else []
        )
        news_topic_ids = (
            load_news_topic_ids(connection, event.article_id)
            if event.source_space == "mind"
            else []
        )
        query_topic_ids = {topic.topic_id for topic in query_topics}
        news_topic_set = set(news_topic_ids)
        overlap_topic_ids = query_topic_ids & news_topic_set
        topic_deltas = {
            topic_id: self._settings.search_result_click_topic_delta
            for topic_id in query_topic_ids | news_topic_set
        }
        for topic_id in overlap_topic_ids:
            topic_deltas[topic_id] = self._settings.search_result_overlap_topic_delta

        record_click_event(
            connection=connection,
            user_id=event.user_id,
            event_type="search_result_click",
            news_id=event.article_id,
            query_key=event.query_key,
            request_id=event.request_id,
            surface=event.surface or "search",
            event_ts=event.event_ts,
            topic_ids=sorted(query_topic_ids | news_topic_set),
            external_event_id=event.event_id,
            sponsored_delivery_id=event.sponsored_delivery_id,
            campaign_id=event.campaign_id,
            creative_id=event.creative_id,
            dwell_ms=event.dwell_ms,
            source_space=event.source_space,
            article_id=event.article_id,
        )
        if profile_row is not None:
            confirm_recent_query(
                connection,
                profile_row,
                query_key=event.query_key,
                event_ts=event.event_ts,
                source_space=event.source_space,
            )
        if sponsored_attribution is not None:
            record_sponsored_click(
                connection,
                attribution=sponsored_attribution,
                event_ts=event.event_ts,
            )
        if profile_row is not None:
            apply_click_profile_update(
                connection=connection,
                profile_row=profile_row,
                news_id=event.article_id,
                event_ts=event.event_ts,
                topic_deltas=topic_deltas,
                behavior_delta=self._settings.search_result_click_behavior_delta,
                decay_factor=self._settings.profile_topic_decay,
                source_space=event.source_space,
            )
            self._project_profile_v2(
                connection,
                event,
                topic_strengths_for_event(
                    event.event_type,
                    article_topic_ids=news_topic_set,
                    query_topic_ids=query_topic_ids,
                    dwell_ms=event.dwell_ms,
                ),
            )

    def _apply_news_click(
        self,
        *,
        connection: Any,
        event: UserEventMessage,
        event_type: str,
        surface: str,
        behavior_delta: float,
        topic_delta: float,
        project_profile: bool,
    ) -> None:
        if event.article_id is None:
            raise ValueError(f"{event_type} event requires article_id")
        profile_row = (
            fetch_profile_row(
                connection,
                event.user_id,
                event.source_space,
                for_update=True,
            )
            if project_profile
            else None
        )
        sponsored_attribution = (
            load_sponsored_attribution(
                connection,
                delivery_id=event.sponsored_delivery_id,
                user_id=event.user_id,
                news_id=event.article_id,
                for_update=True,
            )
            if event.source_space == "mind" and event.sponsored_delivery_id
            else None
        )
        news_topic_ids = (
            load_news_topic_ids(connection, event.article_id)
            if event.source_space == "mind"
            else []
        )
        topic_deltas = {topic_id: topic_delta for topic_id in news_topic_ids}
        record_click_event(
            connection=connection,
            user_id=event.user_id,
            event_type=event_type,
            news_id=event.article_id,
            query_key=event.query_key,
            request_id=event.request_id,
            surface=surface,
            event_ts=event.event_ts,
            topic_ids=news_topic_ids,
            external_event_id=event.event_id,
            sponsored_delivery_id=event.sponsored_delivery_id,
            campaign_id=event.campaign_id,
            creative_id=event.creative_id,
            dwell_ms=event.dwell_ms,
            source_space=event.source_space,
            article_id=event.article_id,
        )
        if sponsored_attribution is not None:
            record_sponsored_click(
                connection,
                attribution=sponsored_attribution,
                event_ts=event.event_ts,
            )
        if profile_row is not None:
            apply_click_profile_update(
                connection=connection,
                profile_row=profile_row,
                news_id=event.article_id,
                event_ts=event.event_ts,
                topic_deltas=topic_deltas,
                behavior_delta=behavior_delta,
                decay_factor=self._settings.profile_topic_decay,
                source_space=event.source_space,
            )
            self._project_profile_v2(
                connection,
                event,
                topic_strengths_for_event(
                    event.event_type,
                    article_topic_ids=news_topic_ids,
                    dwell_ms=event.dwell_ms,
                ),
            )

    def _apply_log_only(
        self,
        connection: Any,
        event: UserEventMessage,
        *,
        project_profile: bool = True,
    ) -> None:
        sponsored_attribution = (
            load_sponsored_attribution(
                connection,
                delivery_id=event.sponsored_delivery_id,
                user_id=event.user_id,
                news_id=event.article_id,
                for_update=True,
            )
            if event.source_space == "mind"
            and event.sponsored_delivery_id
            and event.article_id is not None
            else None
        )
        inserted = record_log_only_event(
            connection=connection,
            user_id=event.user_id,
            event_type=event.event_type,
            surface=event.surface or "home_feed",
            news_id=event.article_id,
            query_key=event.query_key,
            request_id=event.request_id,
            event_ts=event.event_ts,
            debug_payload_json=json_text(event.debug) if event.debug else None,
            external_event_id=event.event_id,
            sponsored_delivery_id=event.sponsored_delivery_id,
            campaign_id=event.campaign_id,
            creative_id=event.creative_id,
            dwell_ms=event.dwell_ms,
            source_space=event.source_space,
            article_id=event.article_id,
        )
        if inserted and event.event_type == "feed_impression" and sponsored_attribution is not None:
            confirm_sponsored_impression(
                connection,
                attribution=sponsored_attribution,
                event_ts=event.event_ts,
            )
        if (
            inserted
            and project_profile
            and event.article_id is not None
            and event.event_type in {"dwell", "downvote"}
        ):
            news_topic_ids = (
                load_news_topic_ids(connection, event.article_id)
                if event.source_space == "mind"
                else []
            )
            self._project_profile_v2(
                connection,
                event,
                topic_strengths_for_event(
                    event.event_type,
                    article_topic_ids=news_topic_ids,
                    dwell_ms=event.dwell_ms,
                ),
            )

    def _project_profile_v2(
        self,
        connection: Any,
        event: UserEventMessage,
        topic_strengths: dict[int, float],
    ) -> bool:
        if not self._settings.profile_v2_enabled:
            return False
        started_at = time.perf_counter()
        try:
            outcome = apply_profile_v2_event_with_outcome(
                connection,
                user_id=event.user_id,
                source_space=event.source_space,
                event_type=event.event_type,
                event_ts=event.event_ts,
                topic_strengths=topic_strengths,
                config=profile_signal_config(self._settings),
            )
        finally:
            PROFILE_V2_PROJECTION_DURATION.observe(time.perf_counter() - started_at)
        if outcome.updated:
            PROFILE_V2_PROJECTION_UPDATES.labels(event_type=event.event_type).inc()
        if outcome.reason in {"pre_reset", "out_of_order"}:
            PROFILE_V2_LATE_EVENTS.labels(reason=outcome.reason).inc()
        elif outcome.late_topic_count:
            PROFILE_V2_LATE_EVENTS.labels(reason="out_of_order").inc()
        return outcome.updated

    def _training_message(self, event: UserEventMessage) -> TrainingInteractionMessage | None:
        label_by_type = {
            "recommendation_click": 1.0,
            "search_result_click": 1.0,
            "upvote": 1.0,
            "downvote": 0.0,
            "feed_impression": None,
        }
        if event.event_type not in label_by_type or event.article_id is None:
            return None
        return TrainingInteractionMessage(
            example_id=event.event_id,
            user_id=event.user_id,
            source_space=event.source_space,
            article_id=event.article_id,
            query_key=event.query_key,
            request_id=event.request_id,
            surface=event.surface,
            sponsored_delivery_id=event.sponsored_delivery_id,
            campaign_id=event.campaign_id,
            creative_id=event.creative_id,
            label=label_by_type[event.event_type],
            event_type=event.event_type,
            event_ts=event.event_ts,
        )


def run_profile_consumer(
    settings: Settings | None = None,
    *,
    max_messages: int | None = None,
) -> None:
    active_settings = settings or get_settings()
    confluent_kafka = cast(Any, importlib.import_module("confluent_kafka"))
    consumer_cls = confluent_kafka.Consumer
    consumer = consumer_cls(
        {
            "bootstrap.servers": active_settings.kafka_bootstrap_servers,
            "group.id": active_settings.kafka_profile_group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    publisher = build_event_publisher(
        active_settings,
        client_id=f"{active_settings.kafka_client_id}-profile-consumer",
    )
    applier = ProfileEventApplier(active_settings)
    consumer.subscribe([active_settings.kafka_raw_events_topic])
    logger.info("profile consumer subscribed to %s", active_settings.kafka_raw_events_topic)
    processed_messages = 0
    current_lag = 0
    partition_lags: dict[tuple[str, int], int] = {}
    try:
        while max_messages is None or processed_messages < max_messages:
            message = consumer.poll(1.0)
            if message is None:
                try:
                    assignments = consumer.assignment()
                    positions = consumer.position(assignments)
                    for position in positions:
                        _, high_watermark = consumer.get_watermark_offsets(
                            position,
                            cached=False,
                        )
                        position_offset = int(position.offset)
                        if position_offset < 0:
                            position_offset = int(high_watermark)
                        lag = max(0, int(high_watermark) - position_offset)
                        key = (str(position.topic), int(position.partition))
                        partition_lags[key] = lag
                        CONSUMER_LAG.labels(
                            topic=key[0],
                            partition=str(key[1]),
                        ).set(lag)
                    current_lag = max(partition_lags.values(), default=0)
                except Exception:
                    logger.debug("unable to refresh consumer lag metric", exc_info=True)
                applier.update_heartbeat(
                    made_progress=False,
                    lag_messages=current_lag,
                )
                continue
            if message.error():
                raise RuntimeError(message.error())

            try:
                topic_partition = confluent_kafka.TopicPartition(
                    message.topic(),
                    message.partition(),
                )
                _, high_watermark = consumer.get_watermark_offsets(
                    topic_partition,
                    cached=False,
                )
                message_lag = max(
                    0,
                    int(high_watermark) - int(message.offset()) - 1,
                )
                partition_key = (str(message.topic()), int(message.partition()))
                partition_lags[partition_key] = message_lag
                current_lag = max(partition_lags.values(), default=0)
                CONSUMER_LAG.labels(
                    topic=message.topic(),
                    partition=str(message.partition()),
                ).set(message_lag)
            except Exception:
                logger.debug("unable to update consumer lag metric", exc_info=True)

            raw_payload = ""
            raw_payload_encoding: Literal["utf-8", "base64"] = "utf-8"
            try:
                raw_value = message.value()
                if raw_value is None:
                    raise ValueError("Kafka tombstone payload is not a valid user event")
                try:
                    raw_payload = raw_value.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raw_payload = base64.b64encode(raw_value).decode("ascii")
                    raw_payload_encoding = "base64"
                    raise ValueError("Kafka payload is not valid UTF-8") from exc
                event = UserEventMessage.model_validate_json(raw_payload)
            except (ValidationError, ValueError, TypeError) as exc:
                publisher.publish_dlq_event(
                    DlqEventMessage(
                        original_topic=message.topic(),
                        original_partition=message.partition(),
                        original_offset=message.offset(),
                        original_payload=raw_payload,
                        original_payload_encoding=raw_payload_encoding,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                )
                publisher.flush()
                CONSUMER_EVENTS.labels(
                    outcome="dlq",
                    event_type="invalid",
                ).inc()
                consumer.commit(message=message, asynchronous=False)
                applier.update_heartbeat(
                    made_progress=True,
                    lag_messages=current_lag,
                )
                processed_messages += 1
                continue

            retry_count = 0
            while True:
                try:
                    applied = applier.apply_event(event)
                    CONSUMER_EVENTS.labels(
                        outcome="applied" if applied else "duplicate",
                        event_type=event.event_type,
                    ).inc()
                    consumer.commit(message=message, asynchronous=False)
                    applier.update_heartbeat(
                        made_progress=True,
                        lag_messages=current_lag,
                    )
                    break
                except IdempotencyConflictError as exc:
                    publisher.publish_dlq_event(
                        DlqEventMessage(
                            original_topic=message.topic(),
                            original_partition=message.partition(),
                            original_offset=message.offset(),
                            original_payload=raw_payload,
                            original_payload_encoding=raw_payload_encoding,
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                        )
                    )
                    publisher.flush()
                    CONSUMER_EVENTS.labels(
                        outcome="dlq",
                        event_type=event.event_type,
                    ).inc()
                    consumer.commit(message=message, asynchronous=False)
                    applier.update_heartbeat(
                        made_progress=True,
                        lag_messages=current_lag,
                    )
                    break
                except Exception as exc:
                    retry_count += 1
                    CONSUMER_RETRIES.inc()
                    if retry_count > active_settings.kafka_consumer_max_retries:
                        applier.update_heartbeat(
                            made_progress=False,
                            lag_messages=current_lag,
                            last_error=f"{type(exc).__name__}: {exc}",
                        )
                        logger.exception(
                            "profile consumer exhausted retries topic=%s partition=%s offset=%s",
                            message.topic(),
                            message.partition(),
                            message.offset(),
                        )
                        raise
                    delay = active_settings.kafka_consumer_retry_backoff_seconds * retry_count
                    logger.warning(
                        "profile consumer transient failure retry=%s delay=%.2fs error=%s",
                        retry_count,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
            processed_messages += 1
    finally:
        consumer.close()
        publisher.flush()
