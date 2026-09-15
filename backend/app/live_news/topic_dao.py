from __future__ import annotations

from typing import Any

from backend.app.live_news.topic_classifier import (
    GENERAL_TOPIC,
    TopicAssignment,
    input_hash,
    load_taxonomy,
)


def seed_topics(connection: Any) -> None:
    with connection.cursor() as cur:
        for topic in load_taxonomy()["topics"]:
            cur.execute(
                "SELECT source_space,topic_key FROM topic WHERE topic_id=%s", (topic["topic_id"],)
            )
            existing = cur.fetchone()
            if existing and (
                existing["source_space"] != "live" or existing["topic_key"] != topic["key"]
            ):
                raise ValueError(f"Topic ID collision: {topic['topic_id']}")
            cur.execute(
                """INSERT INTO topic(topic_id,source_space,topic_key,display_name,source)
                VALUES(%s,'live',%s,%s,'live-topics-1') ON CONFLICT(topic_id) DO NOTHING""",
                (topic["topic_id"], topic["key"], topic["name"]),
            )


def load_live_topic_ids(connection: Any, article_id: str) -> list[int]:
    with connection.cursor() as cur:
        cur.execute(
            """SELECT mapping.topic_id FROM live_news_topic mapping
            JOIN topic ON topic.topic_id=mapping.topic_id AND topic.source_space='live'
            JOIN live_topic_enrichment_job job ON job.article_id=mapping.article_id
            WHERE mapping.article_id=%s AND job.status='completed'
              AND mapping.topic_id<>%s ORDER BY rank""",
            (article_id, GENERAL_TOPIC),
        )
        return [int(row["topic_id"]) for row in cur.fetchall()]


def claim_jobs(connection: Any, worker_id: str, limit: int) -> list[dict[str, Any]]:
    with connection.cursor() as cur:
        cur.execute("""UPDATE live_topic_enrichment_job SET status='pending',worker_id=NULL
            WHERE status='fetching' AND claimed_at < CURRENT_TIMESTAMP-INTERVAL '10 minutes'""")
        cur.execute(
            """WITH due AS (
            SELECT article_id FROM live_topic_enrichment_job
            WHERE status='pending' AND next_attempt_at<=CURRENT_TIMESTAMP
            ORDER BY EXISTS(SELECT 1 FROM user_event e WHERE e.source_space='live'
                AND e.article_id=live_topic_enrichment_job.article_id
                AND e.event_type IN ('recommendation_click','search_result_click','upvote','downvote','dwell')) DESC,
                next_attempt_at,article_id LIMIT %s FOR UPDATE SKIP LOCKED
          ) UPDATE live_topic_enrichment_job job SET status='fetching',worker_id=%s,
            claimed_at=CURRENT_TIMESTAMP,attempt_count=attempt_count+1,updated_at=CURRENT_TIMESTAMP
          FROM due WHERE job.article_id=due.article_id
          RETURNING job.article_id,job.generation,job.attempt_count""",
            (limit, worker_id),
        )
        jobs = [dict(row) for row in cur.fetchall()]
        for job in jobs:
            cur.execute(
                "SELECT title,summary FROM live_news WHERE article_id=%s", (job["article_id"],)
            )
            job.update(cur.fetchone())
        return jobs


def complete_job(
    connection: Any,
    job: dict[str, Any],
    worker_id: str,
    assignments: list[TopicAssignment],
    version: str,
) -> bool:
    with connection.cursor() as cur:
        # Same lock order as metadata ingestion: news first, then its job.
        cur.execute(
            "SELECT title,summary FROM live_news WHERE article_id=%s FOR UPDATE",
            (job["article_id"],),
        )
        current = cur.fetchone()
        fingerprint = input_hash(job["title"], job["summary"])
        if not current or input_hash(current["title"], current["summary"]) != fingerprint:
            return False
        cur.execute(
            """UPDATE live_topic_enrichment_job SET status='completed',updated_at=CURRENT_TIMESTAMP,
            worker_id=NULL,claimed_at=NULL,last_error_code=NULL
            WHERE article_id=%s AND generation=%s AND worker_id=%s AND status='fetching'""",
            (job["article_id"], job["generation"], worker_id),
        )
        if cur.rowcount != 1:
            return False
        cur.execute("DELETE FROM live_news_topic WHERE article_id=%s", (job["article_id"],))
        for rank, assignment in enumerate(assignments):
            cur.execute(
                """INSERT INTO live_news_topic(article_id,topic_id,rank,final_score,
                semantic_score,lexical_score,classifier_version,input_content_hash)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    job["article_id"],
                    assignment.topic_id,
                    rank,
                    assignment.score,
                    assignment.semantic_score,
                    assignment.lexical_score,
                    version,
                    fingerprint,
                ),
            )
        cur.execute(
            """UPDATE live_news SET topic_status='available',topic_classifier_version=%s,
            topic_input_hash=%s,topic_classified_at=CURRENT_TIMESTAMP WHERE article_id=%s""",
            (version, fingerprint, job["article_id"]),
        )
        cur.execute(
            """INSERT INTO live_profile_rebuild_job(user_id)
            SELECT DISTINCT user_id FROM user_event WHERE source_space='live' AND article_id=%s
            AND event_type IN ('recommendation_click','search_result_click','upvote','downvote','dwell')
            ON CONFLICT(user_id) DO UPDATE SET generation=live_profile_rebuild_job.generation+1,
                updated_at=CURRENT_TIMESTAMP""",
            (job["article_id"],),
        )
        return True


def fail_job(connection: Any, job: dict[str, Any], worker_id: str, code: str) -> None:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT article_id FROM live_news WHERE article_id=%s FOR UPDATE", (job["article_id"],)
        )
        cur.execute(
            """UPDATE live_topic_enrichment_job SET status=%s,worker_id=NULL,claimed_at=NULL,
            next_attempt_at=CURRENT_TIMESTAMP+INTERVAL '60 seconds',last_error_code=%s
            WHERE article_id=%s AND generation=%s AND worker_id=%s AND status='fetching'""",
            (
                "failed" if job["attempt_count"] >= 5 else "pending",
                code[:64],
                job["article_id"],
                job["generation"],
                worker_id,
            ),
        )
        if cur.rowcount == 1 and job["attempt_count"] >= 5:
            cur.execute(
                "UPDATE live_news SET topic_status='failed' WHERE article_id=%s",
                (job["article_id"],),
            )
            cur.execute(
                """INSERT INTO live_profile_rebuild_job(user_id)
                SELECT DISTINCT user_id FROM user_event WHERE source_space='live' AND article_id=%s
                AND event_type IN ('recommendation_click','search_result_click','upvote','downvote','dwell')
                ON CONFLICT(user_id) DO UPDATE SET generation=live_profile_rebuild_job.generation+1,
                    updated_at=CURRENT_TIMESTAMP""",
                (job["article_id"],),
            )
