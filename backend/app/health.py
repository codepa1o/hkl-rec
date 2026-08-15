from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, cast

from backend.app.config import Settings
from backend.app.events.outbox import outbox_status_counts
from backend.app.events.worker_state import (
    oldest_pending_outbox_age_seconds,
    worker_readiness_rows,
)
from backend.app.repositories.connection import connect, parse_database_url
from backend.app.schemas.common import DependencyHealth, HealthResponse
from backend.app.search_retrieval import (
    SearchArtifactError,
    load_hybrid_search_index,
)


def repository_backend_name(settings: Settings) -> str:
    return "postgresql" if settings.database_configured else "unwired"


def build_liveness(settings: Settings) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        app_version=settings.app_version,
        repository_backend=repository_backend_name(settings),
        database_configured=settings.database_configured,
        event_mode=settings.event_mode,
        dependencies={
            "process": DependencyHealth(status="ok"),
            "postgresql": DependencyHealth(status="disabled"),
            "kafka": DependencyHealth(status="disabled"),
            "outbox": DependencyHealth(status="disabled"),
            "search_index": DependencyHealth(status="disabled"),
        },
        outbox=None,
    )


def check_readiness(settings: Settings) -> HealthResponse:
    dependencies: dict[str, DependencyHealth] = {
        "process": DependencyHealth(status="ok"),
    }
    outbox_counts: dict[str, int] | None = None
    worker_rows: list[dict[str, Any]] = []
    oldest_outbox_age = 0
    ready = True

    if settings.search_retrieval_mode == "hybrid_v1":
        try:
            index = load_hybrid_search_index(
                Path(settings.search_index_dir),
                expected_source_fingerprint=settings.search_source_fingerprint,
            )
            search_metadata = index.metadata()
            dependencies["search_index"] = DependencyHealth(
                status="ok",
                detail=(
                    f"documents={search_metadata.get('document_count')}, "
                    f"model={search_metadata.get('model_id')}"
                ),
            )
        except SearchArtifactError as exc:
            dependencies["search_index"] = DependencyHealth(
                status="error",
                detail=str(exc),
            )
            ready = False
    else:
        dependencies["search_index"] = DependencyHealth(status="disabled")

    if not settings.database_configured:
        dependencies["postgresql"] = DependencyHealth(
            status="error",
            detail="NEWSREC_DATABASE_URL is not configured",
        )
        dependencies["outbox"] = DependencyHealth(
            status="disabled",
            detail="requires PostgreSQL",
        )
        ready = False
    else:
        try:
            config = parse_database_url(settings.database_url)
            connection = connect(
                config,
                connect_timeout=max(1, round(settings.readiness_timeout_seconds)),
            )
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1 AS ready")
                    cursor.fetchone()
                outbox_counts = outbox_status_counts(connection)
                worker_rows = worker_readiness_rows(connection)
                oldest_outbox_age = oldest_pending_outbox_age_seconds(connection)
            finally:
                connection.close()
            dependencies["postgresql"] = DependencyHealth(status="ok")
            dead_rows = outbox_counts.get("dead", 0)
            backlog = outbox_counts.get("pending", 0) + outbox_counts.get("publishing", 0)
            if not settings.kafka_enabled:
                dependencies["outbox"] = DependencyHealth(
                    status="disabled",
                    detail=f"backlog={backlog}; event mode is {settings.event_mode}",
                )
            elif dead_rows > 0:
                dependencies["outbox"] = DependencyHealth(
                    status="error",
                    detail=f"{dead_rows} dead row(s)",
                )
                ready = False
            elif backlog > settings.readiness_outbox_backlog_limit:
                dependencies["outbox"] = DependencyHealth(
                    status="error",
                    detail=(f"backlog {backlog} exceeds {settings.readiness_outbox_backlog_limit}"),
                )
                ready = False
            elif oldest_outbox_age > settings.readiness_outbox_oldest_pending_max_age_seconds:
                dependencies["outbox"] = DependencyHealth(
                    status="error",
                    detail=(
                        f"oldest pending row age {oldest_outbox_age}s exceeds "
                        f"{settings.readiness_outbox_oldest_pending_max_age_seconds}s"
                    ),
                )
                ready = False
            else:
                dependencies["outbox"] = DependencyHealth(
                    status="ok",
                    detail=f"backlog={backlog}, oldest_pending_age={oldest_outbox_age}s",
                )
        except Exception as exc:
            dependencies["postgresql"] = DependencyHealth(
                status="error",
                detail=f"{type(exc).__name__}: {exc}",
            )
            dependencies["outbox"] = DependencyHealth(
                status="error",
                detail="unavailable because PostgreSQL readiness failed",
            )
            ready = False

    if settings.kafka_enabled:
        try:
            admin_module = cast(Any, importlib.import_module("confluent_kafka.admin"))
            admin = admin_module.AdminClient(
                {"bootstrap.servers": settings.kafka_bootstrap_servers}
            )
            metadata = admin.list_topics(timeout=settings.readiness_timeout_seconds)
            required_topics = {
                settings.kafka_raw_events_topic,
                settings.kafka_training_topic,
                settings.kafka_dlq_topic,
            }
            missing_topics = required_topics - set(metadata.topics)
            if missing_topics:
                raise RuntimeError(f"missing Kafka topics: {', '.join(sorted(missing_topics))}")
            dependencies["kafka"] = DependencyHealth(status="ok")
        except Exception as exc:
            dependencies["kafka"] = DependencyHealth(
                status="error",
                detail=f"{type(exc).__name__}: {exc}",
            )
            ready = False

        heartbeats = {str(row["worker_name"]): row for row in worker_rows}
        required_workers = {"profile-consumer", "outbox-publisher"}
        worker_errors: list[str] = []
        for worker_name in sorted(required_workers):
            row = heartbeats.get(worker_name)
            if row is None:
                worker_errors.append(f"{worker_name}: missing heartbeat")
                continue
            age = int(row.get("heartbeat_age_seconds") or 0)
            lag = int(row.get("lag_messages") or 0)
            if age > settings.readiness_worker_heartbeat_max_age_seconds:
                worker_errors.append(f"{worker_name}: heartbeat age {age}s")
            if worker_name == "profile-consumer" and lag > settings.readiness_consumer_lag_limit:
                worker_errors.append(f"{worker_name}: lag {lag}")
            if row.get("last_error"):
                worker_errors.append(f"{worker_name}: {row['last_error']}")
        if worker_errors:
            dependencies["workers"] = DependencyHealth(
                status="error",
                detail="; ".join(worker_errors),
            )
            ready = False
        else:
            dependencies["workers"] = DependencyHealth(status="ok")
    else:
        dependencies["kafka"] = DependencyHealth(status="disabled")
        dependencies["workers"] = DependencyHealth(status="disabled")

    return HealthResponse(
        status="ok" if ready else "error",
        app_name=settings.app_name,
        app_version=settings.app_version,
        repository_backend=repository_backend_name(settings),
        database_configured=settings.database_configured,
        event_mode=settings.event_mode,
        dependencies=dependencies,
        outbox=outbox_counts,
    )
