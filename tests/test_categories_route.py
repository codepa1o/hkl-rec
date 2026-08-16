from __future__ import annotations

from unittest.mock import Mock

from backend.app.dependencies import get_product_service


def test_categories_returns_raw_keys_and_news_counts(unwired_client) -> None:
    service = Mock()
    service.list_categories.return_value = {
        "items": [
            {"key": "news", "news_count": 20039},
            {"key": "sports", "news_count": 19368},
        ]
    }
    unwired_client.app.dependency_overrides[get_product_service] = lambda: service

    response = unwired_client.get("/categories")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"key": "news", "news_count": 20039},
            {"key": "sports", "news_count": 19368},
        ]
    }
    service.list_categories.assert_called_once_with()
