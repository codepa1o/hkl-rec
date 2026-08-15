from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException

from backend.app.auth.service import AuthenticatedUser, AuthService
from backend.app.dependencies import get_product_service
from backend.app.errors import IdempotencyConflictError
from backend.app.routers.auth import (
    authorize_user_access,
    get_auth_service_factory,
    require_current_user_when_auth_enabled,
)
from backend.app.schemas.event_track import EventTrackRequest, EventTrackResponse
from backend.app.services.product import ProductService

router = APIRouter(prefix="/event", tags=["product"])


@router.post("/track", response_model=EventTrackResponse)
def track_event(
    payload: EventTrackRequest,
    service: ProductService = Depends(get_product_service),
    current_user: AuthenticatedUser | None = Depends(require_current_user_when_auth_enabled),
    auth_service_factory: Callable[[], AuthService] = Depends(get_auth_service_factory),
) -> EventTrackResponse:
    authorize_user_access(payload.user_id, current_user, auth_service_factory)
    try:
        return service.record_tracked_event(payload)
    except IdempotencyConflictError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
