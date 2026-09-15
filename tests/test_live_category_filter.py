from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.config import get_settings
from backend.app.errors import IdempotencyConflictError, UnknownCategoryError
from backend.app.live_news.topic_classifier import TopicAssignment
from backend.app.live_news.topic_dao import complete_job, seed_topics
from backend.app.repositories.postgres import PostgresRuntimeRepository


def claim_fixture(connection, article_id):
    seed_topics(connection)
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE live_topic_enrichment_job SET status='fetching',worker_id='fixture' WHERE article_id=%s RETURNING article_id,generation",
            (article_id,),
        )
        job = dict(cur.fetchone())
        cur.execute("SELECT title,summary FROM live_news WHERE article_id=%s", (article_id,))
        job.update(cur.fetchone())
    return job


@pytest.fixture
def catalog(postgres_connection, seeded_live_articles):
    for article_id in seeded_live_articles.article_ids:
        job = claim_fixture(postgres_connection, article_id)
        assert complete_job(
            postgres_connection,
            job,
            "fixture",
            [TopicAssignment(1000004, 0.9, 0.9, 0.9), TopicAssignment(1000005, 0.89, 0.89, 0.9)],
            "test",
        )
    postgres_connection.commit()
    repository = PostgresRuntimeRepository(replace(get_settings(), live_news_enabled=True))
    yield repository, seeded_live_articles
    repository.close()


@pytest.mark.postgres
def test_catalog_and_language_intersection(catalog):
    repository, fixture = catalog
    categories = repository.list_categories("live")
    assert len(categories.items) == 14
    assert categories.items[0].key == "live-world"
    feed = repository.get_feed(
        fixture.user_id, 10, False, source_space="live", category="live-technology", language="zh"
    )
    assert [i.article_id for i in feed.items] == [fixture.article_ids[1]]
    assert feed.current_watermark is not None
    science = repository.get_feed(
        fixture.user_id, 10, False, source_space="live", category="live-science", language="zh"
    )
    assert [i.article_id for i in science.items] == [fixture.article_ids[1]]
    empty = repository.get_feed(
        fixture.user_id, 10, False, source_space="live", category="live-sports"
    )
    assert empty.items == []
    with pytest.raises(UnknownCategoryError):
        repository.get_feed(fixture.user_id, 10, False, source_space="live", category="sports")


@pytest.mark.postgres
def test_cursor_binds_category_and_language(catalog):
    repository, fixture = catalog
    first = repository.get_feed(
        fixture.user_id, 1, False, source_space="live", category="live-technology"
    )
    assert first.next_cursor
    with pytest.raises(IdempotencyConflictError):
        repository.get_feed(
            fixture.user_id,
            1,
            False,
            source_space="live",
            category="live-science",
            cursor=first.next_cursor,
        )
    with pytest.raises(IdempotencyConflictError):
        repository.get_feed(
            fixture.user_id,
            1,
            False,
            source_space="live",
            category="live-technology",
            language="zh",
            cursor=first.next_cursor,
        )
    second = repository.get_feed(
        fixture.user_id,
        1,
        False,
        source_space="live",
        category="live-technology",
        cursor=first.next_cursor,
    )
    assert len(second.items) == 1
    assert first.items[0].article_id != second.items[0].article_id


@pytest.mark.postgres
def test_updates_follow_classification_and_ignore_pending(catalog, postgres_connection):
    repository, fixture = catalog
    old = datetime.now(UTC) - timedelta(days=1)
    with postgres_connection.cursor() as cur:
        cur.execute(
            "UPDATE live_news SET discovered_at=%s WHERE article_id=ANY(%s)",
            (old, list(fixture.article_ids)),
        )
    postgres_connection.commit()
    args = dict(
        user_id=fixture.user_id,
        source_space="live",
        language="zh",
        since=datetime.now(UTC) - timedelta(minutes=1),
    )
    assert repository.get_feed_update_status(**args, category="live-technology").has_updates
    assert not repository.get_feed_update_status(**args, category="live-sports").has_updates
    feed = repository.get_feed(
        fixture.user_id, 10, False, source_space="live", category="live-technology", language="zh"
    )
    args["since"] = feed.current_watermark
    assert not repository.get_feed_update_status(**args, category="live-technology").has_updates
    with postgres_connection.cursor() as cur:
        cur.execute(
            "UPDATE live_news SET title=title || ' changed' WHERE article_id=%s",
            (fixture.article_ids[1],),
        )
    postgres_connection.commit()
    pending = repository.get_feed(
        fixture.user_id, 10, False, source_space="live", category="live-technology", language="zh"
    )
    assert pending.items == []
    assert repository.get_feed(fixture.user_id, 10, False, source_space="live", language="zh").items


@pytest.mark.postgres
def test_general_is_filterable_and_failed_mapping_is_not(catalog, postgres_connection):
    repository, fixture = catalog
    article_id = fixture.article_ids[0]
    job = claim_fixture(postgres_connection, article_id)
    assert complete_job(
        postgres_connection, job, "fixture", [TopicAssignment(1000014, 0, 0, 0)], "test"
    )
    postgres_connection.commit()
    general = repository.get_feed(
        fixture.user_id, 10, False, source_space="live", category="live-general"
    )
    assert [item.article_id for item in general.items] == [article_id]
    with postgres_connection.cursor() as cur:
        cur.execute(
            "UPDATE live_topic_enrichment_job SET status='failed' WHERE article_id=%s",
            (article_id,),
        )
    postgres_connection.commit()
    assert (
        repository.get_feed(
            fixture.user_id, 10, False, source_space="live", category="live-general"
        ).items
        == []
    )


@pytest.mark.postgres
def test_classification_filter_precedes_candidate_limit(catalog, postgres_connection):
    repository, fixture = catalog
    # Nonmatching newer rows must not consume the 1000-candidate budget.
    try:
        with postgres_connection.cursor() as cur:
            cur.execute("""INSERT INTO live_news(article_id,canonical_url,title,summary,publisher,source_domain,language,
                published_at_quality,discovered_at,fetched_at,content_hash,status,raw_metadata_json)
                SELECT 'L' || md5('category-limit-' || i), 'https://example.test/category-limit-' || i,
                'Unclassified newer article', '', 'Fixture', 'example.test','zh','gdelt_unverified',
                CURRENT_TIMESTAMP + INTERVAL '1 hour', CURRENT_TIMESTAMP,repeat(md5(i::text),2),'active','{}'::jsonb
                FROM generate_series(1,1001) i""")
        # No commit: exercise the exact production query using this transaction.
        selected = repository._live_news_space._load_candidates(
            postgres_connection, language="zh", excluded=set(), category="live-technology"
        )
        assert [item.article_id for item in selected] == [fixture.article_ids[1]]
    finally:
        postgres_connection.rollback()
