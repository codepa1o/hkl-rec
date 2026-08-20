from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.errors import IdempotencyConflictError
from backend.app.events.publisher import EventPublisher, build_event_publisher
from backend.app.events.worker_state import update_worker_heartbeat
from backend.app.observability import (
    OUTBOX_FAILURES,
    OUTBOX_PUBLISHED,
    set_outbox_status_counts,
)
from backend.app.repositories.connection import PostgresConnectionPool, parse_database_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutboxMessage:
    outbox_id: int
    event_id: str
    topic: str
    message_key: str
    payload_json: str
    attempt_count: int


def enqueue_outbox_message(
    connection: Any,
    *,
    event_id: str,
    topic: str,
    message_key: str,
    payload_json: str,
    payload_fingerprint: str | None = None,
) -> bool:
    fingerprint = payload_fingerprint or hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO event_outbox (
              event_id,
              topic,
              message_key,
              payload_fingerprint,
              payload_json
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (event_id, topic) DO NOTHING
            """,
            (event_id, topic, message_key, fingerprint, payload_json),
        )
        inserted = int(cursor.rowcount) == 1
        if inserted:
            return True
        cursor.execute(
            """
            SELECT payload_fingerprint
            FROM event_outbox
            WHERE event_id = %s AND topic = %s
            """,
            (event_id, topic),
        )
        existing = cursor.fetchone()
    if existing is None:
        raise RuntimeError(f"outbox row disappeared: {event_id} / {topic}")
    if str(existing["payload_fingerprint"]) != fingerprint:
        raise IdempotencyConflictError(
            f"outbox event_id reused with conflicting payload: {event_id}"
        )
    return False


def outbox_message_exists(connection: Any, *, event_id: str, topic: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 AS present FROM event_outbox WHERE event_id = %s AND topic = %s",
            (event_id, topic),
        )
        return cursor.fetchone() is not None


def recover_stale_claims(connection: Any, stale_after_seconds: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE event_outbox
            SET
              status = 'pending',
              available_at = CURRENT_TIMESTAMP,
              last_error = CONCAT(
                COALESCE(last_error, ''),
                CASE WHEN last_error IS NULL OR last_error = '' THEN '' ELSE '; ' END,
                'recovered stale publishing claim'
              )
            WHERE status = 'publishing'
              AND updated_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 second')
            """,
            (stale_after_seconds,),
        )
        return int(cursor.rowcount)


def claim_outbox_batch(connection: Any, batch_size: int) -> list[OutboxMessage]:
    connection.begin()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  outbox_id,
                  event_id,
                  topic,
                  message_key,
                  payload_json,
                  attempt_count
                FROM event_outbox
                WHERE status = 'pending'
                  AND available_at <= CURRENT_TIMESTAMP
                ORDER BY outbox_id ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                (batch_size,),
            )
            rows = list(cursor.fetchall())
            if rows:
                ids = [int(row["outbox_id"]) for row in rows]
                placeholders = ",".join(["%s"] * len(ids))
                cursor.execute(
                    f"""
                    UPDATE event_outbox
                    SET
                      status = 'publishing',
                      attempt_count = attempt_count + 1
                    WHERE outbox_id IN ({placeholders})
                    """,
                    tuple(ids),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    return [
        OutboxMessage(
            outbox_id=int(row["outbox_id"]),
            event_id=str(row["event_id"]),
            topic=str(row["topic"]),
            message_key=str(row["message_key"]),
            payload_json=(
                json.dumps(row["payload_json"], separators=(",", ":"))
                if isinstance(row["payload_json"], (dict, list))
                else str(row["payload_json"])
            ),
            attempt_count=int(row["attempt_count"]) + 1,
        )
        for row in rows
    ]


def mark_outbox_published(connection: Any, outbox_ids: list[int]) -> None:
    if not outbox_ids:
        return
    placeholders = ",".join(["%s"] * len(outbox_ids))
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE event_outbox
            SET
              status = 'published',
              published_at = CURRENT_TIMESTAMP,
              last_error = NULL
            WHERE outbox_id IN ({placeholders})
            """,
            tuple(outbox_ids),
        )


def mark_outbox_failed(
    connection: Any,
    messages: list[OutboxMessage],
    *,
    error: str,
    max_attempts: int,
) -> None:
    for message in messages:
        is_dead = message.attempt_count >= max_attempts
        delay_seconds = min(300, 2 ** min(message.attempt_count, 8))
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE event_outbox
                SET
                  status = %s,
                  available_at = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                  last_error = %s
                WHERE outbox_id = %s
                """,
                (
                    "dead" if is_dead else "pending",
                    delay_seconds,
                    error[:4000],
                    message.outbox_id,
                ),
            )


def outbox_status_counts(connection: Any) -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT status, COUNT(*) AS row_count
            FROM event_outbox
            GROUP BY status
            """
        )
        rows = cursor.fetchall()
    return {str(row["status"]): int(row["row_count"]) for row in rows}


class OutboxPublisherWorker:
    def __init__(
        self,
        settings: Settings | None = None,
        publisher: EventPublisher | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if not self._settings.database_url.strip():
            raise ValueError("NEWSREC_DATABASE_URL is required for the outbox publisher")
        if not self._settings.kafka_enabled:
            raise ValueError("outbox publisher requires kafka_dual_write or kafka_async mode")
        config = parse_database_url(self._settings.database_url)
        self._connection_pool = PostgresConnectionPool(
            config,
            connect_timeout=self._settings.postgres_connect_timeout_seconds,
            min_size=self._settings.postgres_pool_min_size,
            max_connections=self._settings.postgres_pool_max_connections,
        )
        self._publisher = publisher or build_event_publisher(
            self._settings,
            client_id=f"{self._settings.kafka_client_id}-outbox",
        )

    def run_once(self) -> int:
        connection = self._connection_pool.connect()
        try:
            recover_stale_claims(connection, self._settings.outbox_stale_after_seconds)
            messages = claim_outbox_batch(connection, self._settings.outbox_batch_size)
            set_outbox_status_counts(outbox_status_counts(connection))
            update_worker_heartbeat(
                connection,
                worker_name="outbox-publisher",
                made_progress=False,
            )
        finally:
            connection.close()
        if not messages:
            return 0

        try:
            for message in messages:
                self._publisher.publish_payload(
                    message.topic,
                    message.message_key,
                    message.payload_json.encode("utf-8"),
                )
            self._publisher.flush()
        except Exception as exc:
            failed_connection = self._connection_pool.connect()
            try:
                failed_connection.begin()
                mark_outbox_failed(
                    failed_connection,
                    messages,
                    error=f"{type(exc).__name__}: {exc}",
                    max_attempts=self._settings.outbox_max_attempts,
                )
                failed_connection.commit()
                set_outbox_status_counts(outbox_status_counts(failed_connection))
                update_worker_heartbeat(
                    failed_connection,
                    worker_name="outbox-publisher",
                    made_progress=False,
                    last_error=f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                failed_connection.rollback()
                raise
            finally:
                failed_connection.close()
            logger.warning("outbox batch publish failed: %s", exc)
            OUTBOX_FAILURES.inc()
            return 0

        published_connection = self._connection_pool.connect()
        try:
            published_connection.begin()
            mark_outbox_published(
                published_connection,
                [message.outbox_id for message in messages],
            )
            published_connection.commit()
            set_outbox_status_counts(outbox_status_counts(published_connection))
            update_worker_heartbeat(
                published_connection,
                worker_name="outbox-publisher",
                made_progress=True,
            )
        except Exception:
            published_connection.rollback()
            raise
        finally:
            published_connection.close()
        OUTBOX_PUBLISHED.inc(len(messages))
        return len(messages)

    def run_forever(self) -> None:
        while True:
            published = self.run_once()
            if published == 0:
                time.sleep(self._settings.outbox_poll_interval_seconds)

    def close(self) -> None:
        self._publisher.flush()
        self._connection_pool.close()
