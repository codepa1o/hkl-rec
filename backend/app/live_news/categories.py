"""Public category keys backed by the versioned local Live taxonomy."""

from backend.app.errors import UnknownCategoryError
from backend.app.live_news.topic_classifier import load_taxonomy


def live_category_id(category: str | None) -> int | None:
    if category is None:
        return None
    for topic in load_taxonomy()["topics"]:
        if topic["key"].replace("live:", "live-", 1) == category:
            return int(topic["topic_id"])
    raise UnknownCategoryError(category)


def category_clause(category: str | None) -> tuple[str, tuple[int, ...]]:
    topic_id = live_category_id(category)
    if topic_id is None:
        return "", ()
    return (
        """AND EXISTS (
        SELECT 1 FROM live_news_topic t
        JOIN live_topic_enrichment_job j ON j.article_id=t.article_id
        WHERE t.article_id=live_news.article_id AND t.source_space='live'
          AND t.topic_id=%s AND j.status='completed')""",
        (topic_id,),
    )
