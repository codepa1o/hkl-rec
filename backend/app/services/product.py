from __future__ import annotations

from backend.app.repositories.base import RuntimeRepository
from backend.app.schemas.article import ArticleCardResponse
from backend.app.schemas.category import CategoryListResponse
from backend.app.schemas.event_track import EventTrackRequest, EventTrackResponse
from backend.app.schemas.persona import PersonaListResponse
from backend.app.schemas.suggestion import SuggestionListResponse


class ProductService:
    def __init__(self, repository: RuntimeRepository) -> None:
        self._repository = repository

    def list_personas(self, limit: int) -> PersonaListResponse:
        return self._repository.list_personas(limit)

    def list_categories(self) -> CategoryListResponse:
        return self._repository.list_categories()

    def list_search_suggestions(self, limit: int) -> SuggestionListResponse:
        return self._repository.list_search_suggestions(limit)

    def get_article_card(self, news_id: str) -> ArticleCardResponse:
        return self._repository.get_article_card(news_id)

    def record_tracked_event(self, payload: EventTrackRequest) -> EventTrackResponse:
        return self._repository.record_tracked_event(payload)
