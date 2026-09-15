"""Run deterministic, offline Live topic enrichment and profile catch-up."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
import uuid
from pathlib import Path
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import get_settings
from backend.app.events.worker_state import update_worker_heartbeat
from backend.app.live_news.topic_classifier import TopicClassifier
from backend.app.live_news.topic_dao import claim_jobs, complete_job, fail_job, seed_topics
from backend.app.repositories.connection import connect, parse_database_url
from scripts.rebuild_profile_v2 import RebuildTargetNotFoundError, rebuild_profiles


def catch_up_profiles(connection, settings):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT user_id,generation FROM live_profile_rebuild_job ORDER BY updated_at LIMIT 10"
        )
        targets = cur.fetchall()
    connection.commit()
    completed = 0
    for target in targets:
        try:
            report = rebuild_profiles(
                connection,
                settings=settings,
                user_id=target["user_id"],
                source_space="live",
                all_users=False,
                dry_run=False,
            )
        except RebuildTargetNotFoundError:
            connection.rollback()
            # Retain the job: the API may still be initializing this profile.
            with connection.transaction(), connection.cursor() as cur:
                cur.execute(
                    "UPDATE live_profile_rebuild_job SET updated_at=CURRENT_TIMESTAMP WHERE user_id=%s",
                    (target["user_id"],),
                )
            continue
        if report.failed_targets:
            print(
                json.dumps(
                    {
                        "profile_rebuild_failed": target["user_id"],
                        "errors": [t.error_type for t in report.failed_targets],
                    }
                ),
                flush=True,
            )
            with connection.transaction(), connection.cursor() as cur:
                cur.execute(
                    "UPDATE live_profile_rebuild_job SET updated_at=CURRENT_TIMESTAMP WHERE user_id=%s",
                    (target["user_id"],),
                )
            continue
        with connection.transaction(), connection.cursor() as cur:
            cur.execute(
                "DELETE FROM live_profile_rebuild_job WHERE user_id=%s AND generation=%s",
                (target["user_id"], target["generation"]),
            )
        completed += 1
    return completed


def run_batch(connection, classifier, settings, worker_id, batch_size):
    started = time.perf_counter()
    with connection.transaction():
        jobs = claim_jobs(connection, worker_id, batch_size)
    completed = 0
    if jobs:
        try:
            outputs = classifier.classify_many([(j["title"], j["summary"]) for j in jobs])
        except Exception as exc:
            with connection.transaction():
                for job in jobs:
                    fail_job(connection, job, worker_id, type(exc).__name__)
            raise
        for job, assignments in zip(jobs, outputs, strict=True):
            try:
                with connection.transaction():
                    completed += complete_job(
                        connection, job, worker_id, assignments, classifier.version
                    )
            except Exception as exc:
                with connection.transaction():
                    fail_job(connection, job, worker_id, type(exc).__name__)
                print(
                    json.dumps(
                        {
                            "classification_write_failed": job["article_id"],
                            "error": type(exc).__name__,
                        }
                    ),
                    flush=True,
                )
    profiles = catch_up_profiles(connection, settings)
    with connection.transaction(), connection.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS count FROM live_topic_enrichment_job WHERE status='pending'"
        )
        pending = cur.fetchone()["count"]
        cur.execute(
            "SELECT COUNT(*) AS count FROM live_topic_enrichment_job WHERE status='fetching'"
        )
        fetching = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) AS count FROM live_topic_enrichment_job WHERE status='failed'")
        failed = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) AS count FROM live_profile_rebuild_job")
        profile_pending = cur.fetchone()["count"]
        update_worker_heartbeat(
            connection,
            worker_name="live-topic-worker",
            made_progress=bool(completed or profiles),
            lag_messages=pending + fetching + profile_pending,
            last_error=f"{failed} failed topic jobs" if failed else None,
        )
    return {
        "classified": completed,
        "claimed": len(jobs),
        "profiles_rebuilt": profiles,
        "pending": pending,
        "fetching": fetching,
        "failed": failed,
        "profile_pending": profile_pending,
        "seconds": round(time.perf_counter() - started, 3),
        "version": classifier.version,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--drain", action="store_true", help="Process pending batches until empty, then exit."
    )
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--model-dir", type=Path, default=ROOT / "build/live_topic_model")
    parser.add_argument("--poll-seconds", type=int, default=5)
    args = parser.parse_args()
    if args.batch_size < 1 or args.poll_seconds < 1:
        parser.error("batch size and poll seconds must be positive")
    settings = get_settings()
    classifier = TopicClassifier(model_dir=args.model_dir)
    connection = None
    worker_id = str(uuid.uuid4())
    stop = Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        while not stop.is_set():
            try:
                if connection is None:
                    connection = connect(parse_database_url(settings.database_url))
                    with connection.transaction(), connection.cursor() as cur:
                        seed_topics(connection)
                        cur.execute(
                            "SELECT DISTINCT topic_classifier_version FROM live_news WHERE topic_classifier_version IS NOT NULL"
                        )
                        versions = {r["topic_classifier_version"] for r in cur.fetchall()}
                        if versions - {classifier.version}:
                            raise ValueError(
                                "Classifier version changed: explicit catalog reclassification required"
                            )
                report = run_batch(connection, classifier, settings, worker_id, args.batch_size)
                print(json.dumps(report), flush=True)
                if args.once or (
                    args.drain
                    and report["pending"] == 0
                    and report["fetching"] == 0
                    and report["profile_pending"] == 0
                ):
                    if report["failed"]:
                        raise RuntimeError(f"{report['failed']} topic jobs exhausted retries")
                    break
                if not report["claimed"]:
                    stop.wait(args.poll_seconds)
            except Exception as exc:
                if connection is not None:
                    connection.close()
                    connection = None
                print(
                    json.dumps(
                        {"error": type(exc).__name__, "retry_in_seconds": args.poll_seconds}
                    ),
                    flush=True,
                )
                if args.once or args.drain or isinstance(exc, ValueError):
                    raise
                stop.wait(args.poll_seconds)
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
