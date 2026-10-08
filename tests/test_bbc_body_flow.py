from dataclasses import replace
from datetime import UTC, datetime

import pytest

from backend.app.config import get_settings
from backend.app.live_news.content_dao import complete_content_job, ensure_content_job
from backend.app.live_news.content_document import ParagraphBlock, StructuredBodyDocument
from backend.app.live_news.content_policy import ContentPolicy
from backend.app.live_news.content_types import AcquiredContent, ContentJob, ContentRequest
from backend.app.repositories.postgres import PostgresRuntimeRepository


@pytest.mark.postgres
def test_bbc_link_only_record_can_be_backfilled_without_public_exposure(
    postgres_connection, seeded_live_articles
):
    c = postgres_connection
    article_id = seeded_live_articles.article_ids[0]
    url = "https://www.bbc.com/news/articles/bbcfixture1"
    with c.cursor() as cur:
        cur.execute(
            "UPDATE live_news SET canonical_url=%s,source_domain='www.bbc.com',content_rights='link_only',body_structure_status='blocked' WHERE article_id=%s",
            (url, article_id),
        )
    policy = ContentPolicy(
        "html",
        "full_text",
        adapter="bbc",
        access_scope="local_research",
        target_extraction_version="bbc-html-2",
    )
    now = datetime.now(UTC)
    ensure_content_job(c, article_id, policy, now=now)
    ensure_content_job(c, article_id, policy, now=now)
    with c.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS count FROM live_news_content_job WHERE article_id=%s", (article_id,)
        )
        assert cur.fetchone()["count"] == 1
    request = ContentRequest(article_id, url, "bbc.com", "en", policy, title="Fixture")
    doc = StructuredBodyDocument(
        extraction_version="bbc-html-2",
        source="html",
        blocks=[ParagraphBlock(id="p-1", text="Preserved BBC research body")],
    )
    complete_content_job(
        c,
        ContentJob(article_id, request, "full_text", 1),
        AcquiredContent(
            "html",
            "Preserved BBC research body",
            now,
            "bbc-html-2",
            doc,
            access_scope="local_research",
        ),
    )
    ensure_content_job(c, article_id, policy, now=now)
    c.commit()
    settings = replace(
        get_settings(),
        live_news_enabled=True,
        environment="development",
        local_research_fulltext_enabled=True,
    )
    repo = PostgresRuntimeRepository(settings)
    try:
        article = repo._live_news_space.get_article(article_id)
        assert article.body_status == "available" and article.body_document is not None
        assert article.body_access_scope == "local_research"
    finally:
        repo.close()
    repo = PostgresRuntimeRepository(replace(settings, environment="production"))
    try:
        article = repo._live_news_space.get_article(article_id)
        assert article.body_text is None and article.body_document is None
    finally:
        repo.close()
