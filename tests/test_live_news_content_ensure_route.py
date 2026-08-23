from __future__ import annotations

from unittest.mock import Mock

from backend.app.dependencies import get_product_service
from backend.app.schemas.article import ContentEnsureResponse

ARTICLE_ID = "L8c9744585e25ce284d0afe62c422577e"


def test_content_ensure_route_enqueues_without_fetching(unwired_client) -> None:
    service = Mock()
    service.ensure_article_content.return_value = ContentEnsureResponse(
        article_id=ARTICLE_ID,
        status="pending",
        enqueued=True,
        retry_after_seconds=5,
    )
    unwired_client.app.dependency_overrides[get_product_service] = lambda: service

    response = unwired_client.post(f"/articles/live/{ARTICLE_ID}/content/ensure")

    assert response.status_code == 200
    assert response.json() == {
        "article_id": ARTICLE_ID,
        "status": "pending",
        "enqueued": True,
        "retry_after_seconds": 5,
    }
    service.ensure_article_content.assert_called_once_with(
        source_space="live",
        article_id=ARTICLE_ID,
    )


def test_content_ensure_route_returns_not_found(unwired_client) -> None:
    service = Mock()
    service.ensure_article_content.side_effect = LookupError("live news not found")
    unwired_client.app.dependency_overrides[get_product_service] = lambda: service

    response = unwired_client.post(f"/articles/live/{ARTICLE_ID}/content/ensure")

    assert response.status_code == 404
