from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.app.news_spaces.types import LiveLanguage, NewsSpace
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


class RuntimeRepository(Protocol):
    backend_name: str

    def close(self) -> None: ...

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
    ) -> FeedResponse: ...

    def get_feed_update_status(
        self,
        user_id: int,
        source_space: NewsSpace,
        language: LiveLanguage,
        since: datetime,
    ) -> FeedUpdateStatusResponse: ...

    def search(self, payload: SearchRequest) -> SearchResponse: ...

    def record_recommendation_click(
        self, payload: RecommendationClickRequest
    ) -> EventAckResponse: ...

    def record_search_result_click(self, payload: SearchResultClickRequest) -> EventAckResponse: ...

    def get_debug_profile(
        self, user_id: int, source_space: NewsSpace = "mind"
    ) -> DebugProfileResponse: ...

    def get_profile(self, user_id: int, source_space: NewsSpace = "mind") -> ProfileResponse: ...

    def reset_profile(self, user_id: int, source_space: NewsSpace = "mind") -> ProfileResponse: ...

    def list_personas(
        self, limit: int, source_space: NewsSpace = "mind"
    ) -> PersonaListResponse: ...

    def list_categories(self, source_space: NewsSpace = "mind") -> CategoryListResponse: ...

    def list_search_suggestions(
        self, limit: int, source_space: NewsSpace = "mind"
    ) -> SuggestionListResponse: ...

    def get_article_card(self, source_space: NewsSpace, article_id: str) -> ArticleCardResponse: ...

    def ensure_article_content(
        self, source_space: NewsSpace, article_id: str
    ) -> ContentEnsureResponse: ...

    def record_tracked_event(self, payload: EventTrackRequest) -> EventTrackResponse: ...
