from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.auth.service import AuthenticatedUser, AuthService
from backend.app.dependencies import get_profile_service
from backend.app.news_spaces.types import NewsSpace
from backend.app.routers.auth import (
    authorize_user_access,
    get_auth_service_factory,
    require_current_user_when_auth_enabled,
    require_trusted_origin,
)
from backend.app.schemas.news_space import ProfileTargetRequest
from backend.app.schemas.profile import ProfileResponse
from backend.app.services.profile import ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse)
def profile(
    user_id: int | None = Query(None),
    source_space: NewsSpace = Query("mind"),
    current_user: AuthenticatedUser | None = Depends(require_current_user_when_auth_enabled),
    auth_service_factory: Callable[[], AuthService] = Depends(get_auth_service_factory),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileResponse:
    target_user_id = user_id if user_id is not None else getattr(current_user, "user_id", None)
    if target_user_id is None:
        raise HTTPException(status_code=422, detail="user_id is required")
    authorize_user_access(target_user_id, current_user, auth_service_factory)
    return service.get_profile(target_user_id, source_space)


@router.post("/reset", response_model=ProfileResponse)
def reset_profile(
    payload: ProfileTargetRequest,
    current_user: AuthenticatedUser | None = Depends(require_current_user_when_auth_enabled),
    auth_service_factory: Callable[[], AuthService] = Depends(get_auth_service_factory),
    _trusted_origin: None = Depends(require_trusted_origin),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileResponse:
    authorize_user_access(payload.user_id, current_user, auth_service_factory)
    return service.reset_profile(payload.user_id, payload.source_space)
