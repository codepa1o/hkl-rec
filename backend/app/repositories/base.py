from __future__ import annotations

from typing import Protocol

from backend.app.schemas.article import ArticleCardResponse
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
        as_of_ts: int | None = None,
    ) -> FeedResponse: ...

    def search(self, payload: SearchRequest) -> SearchResponse: ...

    def record_recommendation_click(
        self, payload: RecommendationClickRequest
    ) -> EventAckResponse: ...

    def record_search_result_click(self, payload: SearchResultClickRequest) -> EventAckResponse: ...

    def get_debug_profile(self, user_id: int) -> DebugProfileResponse: ...

    def get_profile(self, user_id: int) -> ProfileResponse: ...

    def reset_profile(self, user_id: int) -> ProfileResponse: ...

    def list_personas(self, limit: int) -> PersonaListResponse: ...

    def list_search_suggestions(self, limit: int) -> SuggestionListResponse: ...

    def get_article_card(self, article_id: int) -> ArticleCardResponse: ...

    def record_tracked_event(self, payload: EventTrackRequest) -> EventTrackResponse: ...
