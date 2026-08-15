from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends

from backend.app.auth.service import AuthenticatedUser, AuthService
from backend.app.dependencies import get_event_service
from backend.app.routers.auth import (
    authorize_user_access,
    get_auth_service_factory,
    require_current_user_when_auth_enabled,
)
from backend.app.schemas.event import (
    EventAckResponse,
    RecommendationClickRequest,
    SearchResultClickRequest,
)
from backend.app.services.event import EventService

router = APIRouter(prefix="/event", tags=["event"])


@router.post("/recommendation_click", response_model=EventAckResponse)
def recommendation_click(
    payload: RecommendationClickRequest,
    service: EventService = Depends(get_event_service),
    current_user: AuthenticatedUser | None = Depends(require_current_user_when_auth_enabled),
    auth_service_factory: Callable[[], AuthService] = Depends(get_auth_service_factory),
) -> EventAckResponse:
    authorize_user_access(payload.user_id, current_user, auth_service_factory)
    return service.record_recommendation_click(payload)


@router.post("/search_result_click", response_model=EventAckResponse)
def search_result_click(
    payload: SearchResultClickRequest,
    service: EventService = Depends(get_event_service),
    current_user: AuthenticatedUser | None = Depends(require_current_user_when_auth_enabled),
    auth_service_factory: Callable[[], AuthService] = Depends(get_auth_service_factory),
) -> EventAckResponse:
    authorize_user_access(payload.user_id, current_user, auth_service_factory)
    return service.record_search_result_click(payload)
