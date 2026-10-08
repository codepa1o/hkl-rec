from datetime import UTC, datetime

import pytest

from backend.app.live_news.content_dao import ensure_content_job
from backend.app.live_news.content_policy import ContentPolicy


@pytest.mark.postgres
def test_html_fallback_scope_survives_ingestion_and_is_hidden_outside_local_mode(
    postgres_connection, seeded_live_articles
):
    from backend.app.config import Settings
    from backend.app.live_news.content_dao import complete_content_job
    from backend.app.live_news.content_document import ParagraphBlock, StructuredBodyDocument
    from backend.app.live_news.content_types import AcquiredContent, ContentJob, ContentRequest
    from backend.app.news_spaces.live import _body_access_allowed

    article_id = seeded_live_articles.article_ids[0]
    policy = ContentPolicy(
        "guardian_api", "full_text", target_extraction_version="guardian-structured-2"
    )
    request = ContentRequest(
        article_id=article_id,
        canonical_url="https://www.theguardian.com/example",
        expected_domain="theguardian.com",
        language="en",
        policy=policy,
    )
    now = datetime.now(UTC)
    doc = StructuredBodyDocument(
        extraction_version="guardian-structured-2",
        source="html",
        blocks=[ParagraphBlock(id="p-1", text="Local HTML body")],
    )
    try:
        ensure_content_job(postgres_connection, article_id, policy, now=now)
        complete_content_job(
            postgres_connection,
            ContentJob(article_id, request, "full_text", 1),
            AcquiredContent(
                "html",
                "Local HTML body",
                now,
                "guardian-html-1",
                doc,
                access_scope="local_research",
            ),
        )
        ensure_content_job(postgres_connection, article_id, policy, now=now)
        with postgres_connection.cursor() as cur:
            cur.execute(
                "SELECT body_access_scope FROM live_news WHERE article_id=%s", (article_id,)
            )
            row = cur.fetchone()
        assert row["body_access_scope"] == "local_research"
        assert not _body_access_allowed(
            row, Settings(environment="production", local_research_fulltext_enabled=True)
        )
        # Disabling and re-enabling a source must not resurrect a private document as public.
        ensure_content_job(
            postgres_connection, article_id, ContentPolicy("link_only", "link_only"), now=now
        )
        ensure_content_job(postgres_connection, article_id, policy, now=now)
        with postgres_connection.cursor() as cur:
            cur.execute(
                "SELECT body_access_scope FROM live_news WHERE article_id=%s", (article_id,)
            )
            assert cur.fetchone()["body_access_scope"] == "local_research"
    finally:
        postgres_connection.rollback()


@pytest.mark.postgres
def test_version_upgrade_preserves_old_valid_body_until_replacement(
    postgres_connection, seeded_live_articles
):
    article_id = seeded_live_articles.article_ids[0]
    with postgres_connection.cursor() as cur:
        cur.execute(
            """UPDATE live_news SET body_text='Old valid body',body_status='available',
            body_source='guardian_api',body_fetched_at=CURRENT_TIMESTAMP,body_content_hash=%s,
            body_extraction_version='trafilatura-2.1',body_document_version='structured-1'
            WHERE article_id=%s""",
            ("a" * 64, article_id),
        )
    postgres_connection.commit()
    try:
        ensure_content_job(
            postgres_connection,
            article_id,
            ContentPolicy(
                "guardian_api", "full_text", target_extraction_version="guardian-structured-2"
            ),
            now=datetime.now(UTC),
        )
        with postgres_connection.cursor() as cur:
            cur.execute(
                "SELECT body_status,body_text FROM live_news WHERE article_id=%s", (article_id,)
            )
            assert cur.fetchone() == {"body_status": "available", "body_text": "Old valid body"}
            cur.execute(
                "SELECT status,target_extraction_version FROM live_news_content_job WHERE article_id=%s",
                (article_id,),
            )
            assert cur.fetchone() == {
                "status": "pending",
                "target_extraction_version": "guardian-structured-2",
            }
    finally:
        postgres_connection.rollback()
