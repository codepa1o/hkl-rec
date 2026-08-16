from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.auth.service import AuthenticatedUser
from backend.app.dependencies import get_profile_service
from backend.app.routers.auth import get_current_user
from backend.app.schemas.profile import ProfileResponse
from backend.app.services.profile import ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse)
def profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileResponse:
    return service.get_profile(current_user.user_id)


@router.post("/reset", response_model=ProfileResponse)
def reset_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileResponse:
    return service.reset_profile(current_user.user_id)
