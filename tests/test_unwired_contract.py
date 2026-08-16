from __future__ import annotations

import pytest

_BUSINESS_ENDPOINTS = [
    ("GET", "/feed", {"user_id": 7248}, None),
    (
        "POST",
        "/search",
        None,
        {"user_id": 7248, "query_key": "248 12125", "page_size": 5},
    ),
    (
        "POST",
        "/event/recommendation_click",
        None,
        {"user_id": 7248, "news_id": "N1"},
    ),
    (
        "POST",
        "/event/search_result_click",
        None,
        {"user_id": 7248, "news_id": "N1", "query_key": "248 12125"},
    ),
    ("GET", "/debug/profile", {"user_id": 7248}, None),
    ("GET", "/personas", {"limit": 10}, None),
    ("GET", "/search/suggestions", {"limit": 12}, None),
    ("GET", "/articles/N1", None, None),
    (
        "POST",
        "/event/track",
        None,
        {
            "user_id": 7248,
            "event_type": "feed_impression",
            "surface": "home_feed",
            "news_id": "N1",
        },
    ),
]


@pytest.mark.parametrize("method, path, params, body", _BUSINESS_ENDPOINTS)
def test_unwired_business_endpoint_returns_503(unwired_client, method, path, params, body):
    if method == "GET":
        r = unwired_client.get(path, params=params)
    else:
        r = unwired_client.post(path, json=body)
    assert r.status_code == 503, r.text
    payload = r.json()
    assert payload["error_code"] == "repository_not_ready"
    assert payload["path"] == path
    assert isinstance(payload["operation"], str) and payload["operation"]


def test_openapi_exposes_only_article_product_fields(unwired_client):
    document = unwired_client.get("/openapi.json").json()

    assert "/articles/{news_id}" in document["paths"]
    assert not any(path.startswith("/answers") for path in document["paths"])
    forbidden = {
        "answer_id",
        "question_id",
        "question_title",
        "answer_summary",
        "recent_clicked_answers",
        "article_id",
        "recent_clicked_articles",
    }
    for schema in document["components"]["schemas"].values():
        assert forbidden.isdisjoint(schema.get("properties", {}))


def test_mmr_feed_arm_is_accepted_by_the_api_contract(unwired_client):
    response = unwired_client.get(
        "/feed",
        params={
            "user_id": 7248,
            "experiment_arm": "lgb_plus_als_plus_search_mmr",
        },
    )

    assert response.status_code == 503, response.text
    assert response.json()["error_code"] == "repository_not_ready"
