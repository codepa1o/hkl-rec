from __future__ import annotations

from typing import Any

from backend.app.repositories import content_dao
from backend.app.repositories.content_dao import (
    load_exploration_rows,
    load_hot_fallback_rows,
    load_news_ids_available_as_of,
    load_news_ids_for_topics,
    load_news_rows,
    load_unseen_catalog_rows,
    parse_mind_entities,
)


class FakeCursor:
    def __init__(self, scripted_rows: list[list[dict[str, Any]]]) -> None:
        self._scripted_rows = scripted_rows
        self._current: list[dict[str, Any]] = []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((sql, params))
        self._current = self._scripted_rows.pop(0)

    def fetchall(self) -> list[dict[str, Any]]:
        return self._current

    def fetchone(self) -> dict[str, Any] | None:
        return self._current[0] if self._current else None


class FakeConnection:
    def __init__(self, scripted_rows: list[list[dict[str, Any]]]) -> None:
        self.cursor_value = FakeCursor(scripted_rows)

    def cursor(self) -> FakeCursor:
        return self.cursor_value


def test_load_news_rows_is_keyed_by_canonical_news_id() -> None:
    connection = FakeConnection([[{"news_id": "N1", "title": "One", "hot_score": 0.0}]])

    rows = load_news_rows(connection, ["N1"])

    assert rows["N1"]["title"] == "One"
    sql, params = connection.cursor_value.executed[0]
    assert "FROM mind_news AS news" in sql
    assert "answer" not in sql.lower()
    assert params == (["N1"],)


def test_parse_mind_entities_maps_types_and_deduplicates_wikidata_ids() -> None:
    entities = parse_mind_entities(
        [
            {
                "Label": "Ada Lovelace",
                "Type": "P",
                "WikidataId": "Q7259",
                "Confidence": 1.0,
                "SurfaceForms": ["Ada"],
            },
            {
                "Label": "Ada Lovelace",
                "Type": "P",
                "WikidataId": "Q7259",
                "Confidence": 0.8,
                "SurfaceForms": ["Lovelace"],
            },
            {"Label": "OpenAI", "Type": "O", "WikidataId": "Q24283660"},
            {"Label": "London", "Type": "G", "WikidataId": "Q84"},
            {"Label": "Computing", "Type": "U", "WikidataId": "Q11660"},
            {"Type": "P", "WikidataId": "Q0"},
        ]
    )

    assert [(entity.label, entity.entity_type) for entity in entities] == [
        ("Ada Lovelace", "person"),
        ("OpenAI", "organization"),
        ("London", "location"),
        ("Computing", "other"),
    ]
    assert entities[0].surface_forms == ["Ada"]
    assert entities[0].confidence == 1.0


def test_topic_and_hot_recall_read_mind_news_stats() -> None:
    topic_connection = FakeConnection([[{"news_id": "N2", "hot_score": 2.0}]])
    hot_connection = FakeConnection([[{"news_id": "N3", "hot_score": 1.0}]])

    assert load_news_ids_for_topics(topic_connection, [7], 10)[0]["news_id"] == "N2"
    assert load_hot_fallback_rows(hot_connection, 10)[0]["news_id"] == "N3"
    assert "mind_news_stats" in topic_connection.cursor_value.executed[0][0]
    assert "mind_news_topic" in topic_connection.cursor_value.executed[0][0]
    assert "LOWER(display_name)" not in topic_connection.cursor_value.executed[0][0]
    assert "mind_news_stats" in hot_connection.cursor_value.executed[0][0]


def test_exploration_is_deterministic_and_does_not_filter_zero_stats() -> None:
    connection = FakeConnection([[{"news_id": "N999", "hot_score": 0.0}]])

    rows = load_exploration_rows(connection, bucket_seed="user:1:page:1", limit=5)

    assert rows == [{"news_id": "N999", "hot_score": 0.0}]
    sql, params = connection.cursor_value.executed[0]
    assert "md5(news.news_id || %s)" in sql
    assert "hot_score >" not in sql
    assert params == ("user:1:page:1", 5)


def test_exploration_seed_can_rotate_the_full_catalog_slice() -> None:
    first = FakeConnection([[{"news_id": "N1", "hot_score": 0.0}]])
    second = FakeConnection([[{"news_id": "N2", "hot_score": 0.0}]])

    load_exploration_rows(first, bucket_seed="user:1:request:r1:catalog", limit=10)
    load_exploration_rows(second, bucket_seed="user:1:request:r2:catalog", limit=10)

    assert first.cursor_value.executed[0][1] != second.cursor_value.executed[0][1]


def test_all_feed_candidate_queries_accept_an_exact_category() -> None:
    topic = FakeConnection([[]])
    hot = FakeConnection([[]])
    exploration = FakeConnection([[]])
    unseen = FakeConnection([[]])
    als = FakeConnection([[]])

    load_news_ids_for_topics(topic, [7], 10, category="sports")
    load_hot_fallback_rows(hot, 10, category="sports")
    load_exploration_rows(
        exploration,
        bucket_seed="category-sports",
        limit=10,
        category="sports",
    )
    load_unseen_catalog_rows(
        unseen,
        session_id="session-sports",
        bucket_seed="category-sports",
        limit=10,
        category="sports",
    )
    load_news_ids_available_as_of(
        als,
        ["N1", "N2"],
        as_of_ts=None,
        category="sports",
    )

    for connection in (topic, hot, exploration, unseen, als):
        sql, params = connection.cursor_value.executed[0]
        assert "news.category = %s" in sql
        assert "sports" in params


def test_news_category_exists_uses_an_exact_database_match() -> None:
    connection = FakeConnection([[{"exists": True}]])

    assert content_dao.news_category_exists(connection, "sports") is True

    sql, params = connection.cursor_value.executed[0]
    assert "category = %s" in sql
    assert params == ("sports",)
