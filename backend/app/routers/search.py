from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends

from backend.app.auth.service import AuthenticatedUser, AuthService
from backend.app.dependencies import get_search_service
from backend.app.routers.auth import (
    authorize_user_access,
    get_auth_service_factory,
    require_current_user_when_auth_enabled,
)
from backend.app.schemas.search import SearchRequest, SearchResponse
from backend.app.services.search import SearchService

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search(
    payload: SearchRequest,
    service: SearchService = Depends(get_search_service),
    current_user: AuthenticatedUser | None = Depends(require_current_user_when_auth_enabled),
    auth_service_factory: Callable[[], AuthService] = Depends(get_auth_service_factory),
) -> SearchResponse:
    authorize_user_access(payload.user_id, current_user, auth_service_factory)
    return service.search(payload)
