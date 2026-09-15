import uuid
from dataclasses import replace

import pytest

from backend.app.config import get_settings
from backend.app.live_news.topic_classifier import GENERAL_TOPIC, TopicAssignment
from backend.app.live_news.topic_dao import complete_job, fail_job, load_live_topic_ids, seed_topics
from backend.app.repositories.postgres import PostgresRuntimeRepository
from backend.app.repositories.profile_dao import ensure_profile_row
from backend.app.schemas.event import RecommendationClickRequest
from scripts.run_live_topic_worker import catch_up_profiles

pytestmark = pytest.mark.postgres


def claim_fixture(connection, article_id):
    with connection.cursor() as cur:
        seed_topics(connection)
        cur.execute(
            """UPDATE live_topic_enrichment_job SET status='fetching',
            worker_id='fixture',attempt_count=attempt_count+1,claimed_at=CURRENT_TIMESTAMP
            WHERE article_id=%s RETURNING article_id,generation,attempt_count""",
            (article_id,),
        )
        job = dict(cur.fetchone())
        cur.execute("SELECT title,summary FROM live_news WHERE article_id=%s", (article_id,))
        job.update(cur.fetchone())
    return job


def test_late_topics_replay_idempotently_and_reset_stays_reset(
    postgres_connection, seeded_live_articles
):
    connection = postgres_connection
    user_id = seeded_live_articles.user_id
    for space in ("mind", "live"):
        ensure_profile_row(connection, user_id, space)
    connection.commit()
    settings = replace(
        get_settings(), live_news_enabled=True, event_mode="sync_postgres", profile_v2_enabled=True
    )
    repository = PostgresRuntimeRepository(settings)
    try:
        mind_before = repository.get_profile(user_id, "mind")
        feed = repository.get_feed(
            user_id=user_id, page_size=10, debug=False, source_space="live", language="all"
        )
        article_id = next(
            item.article_id
            for item in feed.items
            if item.article_id in seeded_live_articles.article_ids
        )
        request = RecommendationClickRequest(
            user_id=user_id,
            source_space="live",
            article_id=article_id,
            request_id=feed.request_id,
            event_id=str(uuid.uuid4()),
        )
        repository.record_recommendation_click(request)
        assert repository.get_profile(user_id, "live").evidence_count == 0
        job = claim_fixture(connection, article_id)
        assert complete_job(
            connection, job, "fixture", [TopicAssignment(1000004, 0.9, 0.9, 0.9)], "fixture-v1"
        )
        connection.commit()
        assert catch_up_profiles(connection, settings) >= 1
        assert repository.get_profile(user_id, "live").evidence_count == 1
        assert repository.get_profile(user_id, "live").long_term.interests[0].topic_id == 1000004
        repository.record_recommendation_click(request)
        catch_up_profiles(connection, settings)
        assert repository.get_profile(user_id, "live").evidence_count == 1
        # A new accepted event takes effect synchronously, before worker catch-up.
        request2 = request.model_copy(update={"event_id": str(uuid.uuid4())})
        repository.record_recommendation_click(request2)
        assert repository.get_profile(user_id, "live").evidence_count == 2
        catch_up_profiles(connection, settings)
        assert repository.get_profile(user_id, "live").evidence_count == 2
        assert repository.get_profile(user_id, "mind") == mind_before
        # Historical nonempty event snapshots must not retain obsolete topics.
        for topic_id in (1000012, GENERAL_TOPIC):
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE live_news SET title=title || ' revised' WHERE article_id=%s",
                    (article_id,),
                )
            assert load_live_topic_ids(connection, article_id) == []
            replacement = claim_fixture(connection, article_id)
            assert complete_job(
                connection,
                replacement,
                "fixture",
                [TopicAssignment(topic_id, 0.9, 0.9, 0.9)],
                "fixture-v1",
            )
            connection.commit()
            catch_up_profiles(connection, settings)
            updated = repository.get_profile(user_id, "live")
            if topic_id == GENERAL_TOPIC:
                assert updated.evidence_count == 0
                assert updated.long_term.interests == []
            else:
                assert updated.evidence_count == 2
                assert [t.topic_id for t in updated.long_term.interests] == [topic_id]
        repository.reset_profile(user_id, "live")
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO live_profile_rebuild_job(user_id) VALUES(%s) ON CONFLICT DO NOTHING",
                (user_id,),
            )
        connection.commit()
        catch_up_profiles(connection, settings)
        assert repository.get_profile(user_id, "live").evidence_count == 0
        assert repository.get_profile(user_id, "mind") == mind_before
    finally:
        repository.close()


def test_generation_rejects_stale_result_and_general_is_not_interest(
    postgres_connection, seeded_live_articles
):
    connection = postgres_connection
    article_id = seeded_live_articles.article_ids[0]
    job = claim_fixture(connection, article_id)
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE live_news SET title=title || ' changed' WHERE article_id=%s", (article_id,)
        )
    assert not complete_job(
        connection, job, "fixture", [TopicAssignment(1000004, 0.9, 0.9, 0.9)], "fixture-v1"
    )
    newer = claim_fixture(connection, article_id)
    assert newer["generation"] == job["generation"] + 1
    assert not complete_job(
        connection, newer, "wrong-worker", [TopicAssignment(GENERAL_TOPIC, 0, 0, 0)], "fixture-v1"
    )
    assert complete_job(
        connection, newer, "fixture", [TopicAssignment(GENERAL_TOPIC, 0, 0, 0)], "fixture-v1"
    )
    assert load_live_topic_ids(connection, article_id) == []
    connection.commit()


def test_retries_are_bounded(postgres_connection, seeded_live_articles):
    connection = postgres_connection
    article_id = seeded_live_articles.article_ids[0]
    for attempt in range(1, 6):
        job = claim_fixture(connection, article_id)
        fail_job(connection, job, "fixture", "model_error")
        with connection.cursor() as cur:
            cur.execute(
                "SELECT status,attempt_count FROM live_topic_enrichment_job WHERE article_id=%s",
                (article_id,),
            )
            row = cur.fetchone()
        assert row["attempt_count"] == attempt
        assert row["status"] == ("failed" if attempt == 5 else "pending")
    connection.commit()


def test_optional_feed_gate_excludes_only_unclassified(postgres_connection, seeded_live_articles):
    from types import SimpleNamespace

    from backend.app.news_spaces.live import LiveNewsSpaceRepository

    connection = postgres_connection
    first, second = seeded_live_articles.article_ids
    job = claim_fixture(connection, first)
    assert complete_job(
        connection, job, "fixture", [TopicAssignment(GENERAL_TOPIC, 0, 0, 0)], "fixture-v1"
    )
    repository = object.__new__(LiveNewsSpaceRepository)
    repository._allowlist = SimpleNamespace(match=lambda domain: None)
    repository._settings = replace(get_settings(), live_topics_required=True)
    gated = {
        c.article_id
        for c in repository._load_candidates(connection, language="all", excluded=set())
    }
    assert first in gated and second not in gated
    repository._settings = replace(get_settings(), live_topics_required=False)
    ungated = {
        c.article_id
        for c in repository._load_candidates(connection, language="all", excluded=set())
    }
    assert {first, second} <= ungated
    connection.commit()
