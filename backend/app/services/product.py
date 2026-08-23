from __future__ import annotations

from backend.app.news_spaces.types import NewsSpace
from backend.app.repositories.base import RuntimeRepository
from backend.app.schemas.article import ArticleCardResponse, ContentEnsureResponse
from backend.app.schemas.category import CategoryListResponse
from backend.app.schemas.event_track import EventTrackRequest, EventTrackResponse
from backend.app.schemas.persona import PersonaListResponse
from backend.app.schemas.suggestion import SuggestionListResponse


class ProductService:
    def __init__(self, repository: RuntimeRepository) -> None:
        self._repository = repository

    def list_personas(self, limit: int, source_space: NewsSpace = "mind") -> PersonaListResponse:
        return self._repository.list_personas(limit, source_space)

    def list_categories(self, source_space: NewsSpace = "mind") -> CategoryListResponse:
        return self._repository.list_categories(source_space)

    def list_search_suggestions(
        self, limit: int, source_space: NewsSpace = "mind"
    ) -> SuggestionListResponse:
        return self._repository.list_search_suggestions(limit, source_space)

    def get_article_card(self, source_space: NewsSpace, article_id: str) -> ArticleCardResponse:
        return self._repository.get_article_card(source_space, article_id)

    def ensure_article_content(
        self, source_space: NewsSpace, article_id: str
    ) -> ContentEnsureResponse:
        return self._repository.ensure_article_content(source_space, article_id)

    def record_tracked_event(self, payload: EventTrackRequest) -> EventTrackResponse:
        return self._repository.record_tracked_event(payload)
