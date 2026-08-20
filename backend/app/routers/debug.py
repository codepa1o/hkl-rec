from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Query

from backend.app.auth.service import AuthenticatedUser, AuthService
from backend.app.dependencies import get_profile_service
from backend.app.news_spaces.types import NewsSpace
from backend.app.routers.auth import (
    authorize_user_access,
    get_auth_service_factory,
    require_current_user_when_auth_enabled,
)
from backend.app.schemas.profile import DebugProfileResponse
from backend.app.services.profile import ProfileService

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/profile", response_model=DebugProfileResponse)
def debug_profile(
    user_id: int = Query(..., description="Demo user ID."),
    source_space: NewsSpace = Query("mind"),
    service: ProfileService = Depends(get_profile_service),
    current_user: AuthenticatedUser | None = Depends(require_current_user_when_auth_enabled),
    auth_service_factory: Callable[[], AuthService] = Depends(get_auth_service_factory),
) -> DebugProfileResponse:
    authorize_user_access(user_id, current_user, auth_service_factory)
    return service.get_debug_profile(user_id=user_id, source_space=source_space)
