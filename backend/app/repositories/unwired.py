from __future__ import annotations

from datetime import datetime

from backend.app.config import Settings
from backend.app.errors import RepositoryNotReadyError
from backend.app.news_spaces.types import LiveLanguage, NewsSpace
from backend.app.repositories.base import RuntimeRepository
from backend.app.schemas.article import ArticleCardResponse, ContentEnsureResponse
from backend.app.schemas.category import CategoryListResponse
from backend.app.schemas.event import (
    EventAckResponse,
    RecommendationClickRequest,
    SearchResultClickRequest,
)
from backend.app.schemas.event_track import EventTrackRequest, EventTrackResponse
from backend.app.schemas.feed import FeedExperimentArm, FeedResponse, FeedUpdateStatusResponse
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
        source_space: NewsSpace = "mind",
        language: LiveLanguage = "all",
    ) -> FeedResponse:
        raise RepositoryNotReadyError("GET /feed")

    def get_feed_update_status(
        self,
        user_id: int,
        source_space: NewsSpace,
        language: LiveLanguage,
        since: datetime,
    ) -> FeedUpdateStatusResponse:
        raise RepositoryNotReadyError("GET /feed/updates")

    def search(self, payload: SearchRequest) -> SearchResponse:
        raise RepositoryNotReadyError("POST /search")

    def record_recommendation_click(self, payload: RecommendationClickRequest) -> EventAckResponse:
        raise RepositoryNotReadyError("POST /event/recommendation_click")

    def record_search_result_click(self, payload: SearchResultClickRequest) -> EventAckResponse:
        raise RepositoryNotReadyError("POST /event/search_result_click")

    def get_debug_profile(
        self, user_id: int, source_space: NewsSpace = "mind"
    ) -> DebugProfileResponse:
        raise RepositoryNotReadyError("GET /debug/profile")

    def get_profile(self, user_id: int, source_space: NewsSpace = "mind") -> ProfileResponse:
        raise RepositoryNotReadyError("GET /profile")

    def reset_profile(self, user_id: int, source_space: NewsSpace = "mind") -> ProfileResponse:
        raise RepositoryNotReadyError("POST /profile/reset")

    def list_personas(self, limit: int, source_space: NewsSpace = "mind") -> PersonaListResponse:
        raise RepositoryNotReadyError("GET /personas")

    def list_categories(self, source_space: NewsSpace = "mind") -> CategoryListResponse:
        raise RepositoryNotReadyError("GET /categories")

    def list_search_suggestions(
        self, limit: int, source_space: NewsSpace = "mind"
    ) -> SuggestionListResponse:
        raise RepositoryNotReadyError("GET /search/suggestions")

    def get_article_card(self, source_space: NewsSpace, article_id: str) -> ArticleCardResponse:
        raise RepositoryNotReadyError(f"GET /articles/{source_space}/{article_id}")

    def ensure_article_content(
        self, source_space: NewsSpace, article_id: str
    ) -> ContentEnsureResponse:
        raise RepositoryNotReadyError(f"POST /articles/{source_space}/{article_id}/content/ensure")

    def record_tracked_event(self, payload: EventTrackRequest) -> EventTrackResponse:
        raise RepositoryNotReadyError("POST /event/track")
