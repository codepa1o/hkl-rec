from __future__ import annotations

from backend.app.config import Settings
from backend.app.errors import RepositoryNotReadyError
from backend.app.repositories.base import RuntimeRepository
from backend.app.schemas.article import ArticleCardResponse
from backend.app.schemas.category import CategoryListResponse
from backend.app.schemas.event import (
    EventAckResponse,
    RecommendationClickRequest,
    SearchResultClickRequest,
)
from backend.app.schemas.event_track import EventTrackRequest, EventTrackResponse
from backend.app.schemas.feed import FeedExperimentArm, FeedResponse
from backend.app.schemas.persona import PersonaListResponse
from backend.app.schemas.profile import DebugProfileResponse, ProfileResponse
from backend.app.schemas.search import SearchRequest, SearchResponse
from backend.app.schemas.suggestion import SuggestionListResponse


class UnwiredRuntimeRepository(RuntimeRepository):
    backend_name = "unwired"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def close(self) -> None:
        return None

    def get_feed(
        self,
        user_id: int,
        page_size: int,
        debug: bool,
        experiment_arm: FeedExperimentArm = "default",
        include_sponsored: bool = True,
        request_id: str | None = None,
        cursor: str | None = None,
        as_of_ts: int | None = None,
        category: str | None = None,
    ) -> FeedResponse:
        raise RepositoryNotReadyError("GET /feed")

    def search(self, payload: SearchRequest) -> SearchResponse:
        raise RepositoryNotReadyError("POST /search")

    def record_recommendation_click(self, payload: RecommendationClickRequest) -> EventAckResponse:
        raise RepositoryNotReadyError("POST /event/recommendation_click")

    def record_search_result_click(self, payload: SearchResultClickRequest) -> EventAckResponse:
        raise RepositoryNotReadyError("POST /event/search_result_click")

    def get_debug_profile(self, user_id: int) -> DebugProfileResponse:
        raise RepositoryNotReadyError("GET /debug/profile")

    def get_profile(self, user_id: int) -> ProfileResponse:
        raise RepositoryNotReadyError("GET /profile")

    def reset_profile(self, user_id: int) -> ProfileResponse:
        raise RepositoryNotReadyError("POST /profile/reset")

    def list_personas(self, limit: int) -> PersonaListResponse:
        raise RepositoryNotReadyError("GET /personas")

    def list_categories(self) -> CategoryListResponse:
        raise RepositoryNotReadyError("GET /categories")

    def list_search_suggestions(self, limit: int) -> SuggestionListResponse:
        raise RepositoryNotReadyError("GET /search/suggestions")

    def get_article_card(self, news_id: str) -> ArticleCardResponse:
        raise RepositoryNotReadyError("GET /articles/{news_id}")

    def record_tracked_event(self, payload: EventTrackRequest) -> EventTrackResponse:
        raise RepositoryNotReadyError("POST /event/track")
