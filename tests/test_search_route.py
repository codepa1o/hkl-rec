from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _make_client(search_impl) -> TestClient:
    """构建使用仓储桩的 TestClient，并覆写其 ``search()``。"""
    from backend.app.config import Settings, get_settings
    from backend.app.dependencies import (
        get_app_settings,
        get_event_service,
        get_feed_service,
        get_product_service,
        get_profile_service,
        get_repository_backend_name,
        get_runtime_repository,
        get_search_service,
    )
    from backend.app.main import create_app
    from backend.app.repositories.unwired import UnwiredRuntimeRepository
    from backend.app.services.event import EventService
    from backend.app.services.feed import FeedService
    from backend.app.services.product import ProductService
    from backend.app.services.profile import ProfileService
    from backend.app.services.search import SearchService

    get_settings.cache_clear()
    get_runtime_repository.cache_clear()
    settings = Settings(allow_unauthenticated_research_api=True)
    repo = UnwiredRuntimeRepository(settings)
    repo.search = search_impl  # type: ignore[method-assign]
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_repository_backend_name] = lambda: repo.backend_name
    app.dependency_overrides[get_feed_service] = lambda: FeedService(repo)
    app.dependency_overrides[get_search_service] = lambda: SearchService(repo)
    app.dependency_overrides[get_event_service] = lambda: EventService(repo)
    app.dependency_overrides[get_profile_service] = lambda: ProfileService(repo)
    app.dependency_overrides[get_product_service] = lambda: ProductService(repo)
    return TestClient(app)


def test_search_requires_query_key_or_query_text(unwired_client):
    response = unwired_client.post("/search", json={"user_id": 7248})
    assert response.status_code == 422


def test_search_blank_inputs_are_rejected(unwired_client):
    response = unwired_client.post(
        "/search", json={"user_id": 7248, "query_key": "   ", "query_text": "   "}
    )
    assert response.status_code == 422


def test_search_replay_timestamp_requires_debug(unwired_client):
    response = unwired_client.post(
        "/search",
        json={"user_id": 7248, "query_key": "1", "replay_event_ts": 100},
    )

    assert response.status_code == 422


def test_search_unresolved_text_returns_422_with_error_code():
    from backend.app.errors import UnresolvedQueryError
    from backend.app.schemas.search import SearchRequest

    captured: dict[str, Any] = {}

    def fake_search(payload: SearchRequest):
        captured["payload"] = payload
        raise UnresolvedQueryError(payload.query_text or payload.query_key or "")

    client = _make_client(fake_search)
    response = client.post("/search", json={"user_id": 7248, "query_text": "xyzzy-not-a-topic"})
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "unresolved_query"
    assert body["query_input"] == "xyzzy-not-a-topic"
    assert body["path"] == "/search"
    assert captured["payload"].query_text == "xyzzy-not-a-topic"


def test_search_missing_hybrid_artifact_returns_503():
    from backend.app.errors import SearchIndexNotReadyError
    from backend.app.schemas.search import SearchRequest

    def fake_search(_payload: SearchRequest):
        raise SearchIndexNotReadyError("metadata.json is missing")

    client = _make_client(fake_search)
    response = client.post("/search", json={"user_id": 7248, "query_text": "football tactics"})

    assert response.status_code == 503
    assert response.json()["error_code"] == "search_index_not_ready"


def test_search_numeric_query_key_reaches_repository():
    from backend.app.schemas.common import TopicCard
    from backend.app.schemas.search import (
        SearchItem,
        SearchItemScores,
        SearchRequest,
        SearchResponse,
    )

    captured: dict[str, Any] = {}

    def fake_search(payload: SearchRequest) -> SearchResponse:
        captured["payload"] = payload
        return SearchResponse(
            user_id=payload.user_id,
            request_id="search-test",
            query_key=payload.query_key or "",
            items=[
                SearchItem(
                    news_id="N1",
                    title="t",
                    abstract="s",
                    url="https://example.com/1",
                    source_domain="example.com",
                    category="news",
                    subcategory="local",
                    categories=[TopicCard(topic_id=3, display_name="Falafel")],
                    scores=SearchItemScores(
                        topic_match_score=1.0,
                        bm25_score=0.0,
                        dense_score=0.0,
                        hybrid_score=0.0,
                        final_score=1.0,
                    ),
                )
            ],
        )

    client = _make_client(fake_search)
    response = client.post(
        "/search", json={"user_id": 7248, "query_key": "248 12125", "page_size": 5}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["query_key"] == "248 12125"
    assert len(body["items"]) == 1
    assert captured["payload"].query_key == "248 12125"
    assert captured["payload"].query_text is None


def test_search_text_query_reaches_repository():
    from backend.app.schemas.search import SearchRequest, SearchResponse

    captured: dict[str, Any] = {}

    def fake_search(payload: SearchRequest) -> SearchResponse:
        captured["payload"] = payload
        return SearchResponse(
            user_id=payload.user_id,
            request_id="search-test",
            query_key="100 200",
            items=[],
        )

    client = _make_client(fake_search)
    response = client.post("/search", json={"user_id": 7248, "query_text": "Falafel"})
    assert response.status_code == 200
    assert response.json()["query_key"] == "100 200"
    assert captured["payload"].query_text == "Falafel"
    assert captured["payload"].query_key is None
