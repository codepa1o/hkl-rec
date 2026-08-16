from __future__ import annotations

from typing import Any

from backend.app.repositories.content_dao import load_search_candidates
from backend.app.search_retrieval import HybridHit


class FakeCursor:
    def __init__(self, script: list[list[dict[str, Any]]]) -> None:
        self._script = script
        self._current: list[dict[str, Any]] = []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((sql, params))
        self._current = self._script.pop(0) if self._script else []

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._current)


class FakeConnection:
    def __init__(self, script: list[list[dict[str, Any]]]) -> None:
        self.cursor_value = FakeCursor(script)

    def cursor(self) -> FakeCursor:
        return self.cursor_value


def test_hybrid_candidates_use_artifact_hits_without_sql_or_hot_backfill():
    connection = FakeConnection(script=[])
    hits = (
        HybridHit(
            news_id="N42",
            bm25_score=12.0,
            dense_score=0.7,
            fusion_score=0.03,
            bm25_rank=1,
            dense_rank=2,
        ),
    )

    candidates = load_search_candidates(
        connection,
        query_key="14",
        page_size=10,
        query_text="football tactics",
        retrieval_mode="hybrid_v1",
        hybrid_hits=hits,
    )

    assert connection.cursor_value.executed == []
    assert candidates == {
        "N42": {
            "source": "bm25+dense",
            "topic_match_score": 0.0,
            "bm25_score": 12.0,
            "dense_score": 0.7,
            "hybrid_score": 0.03,
        }
    }


def test_topic_lookup_does_not_backfill_hot_articles_when_empty():
    connection = FakeConnection(script=[[]])

    candidates = load_search_candidates(
        connection,
        query_key="14",
        page_size=10,
        query_text=None,
        retrieval_mode="hybrid_v1",
    )

    assert candidates == {}
    assert len(connection.cursor_value.executed) == 1
    assert "mind_news_stats" in connection.cursor_value.executed[0][0]
