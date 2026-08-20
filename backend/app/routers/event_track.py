from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from backend.app.auth.service import AuthenticatedUser, AuthService
from backend.app.dependencies import get_product_service
from backend.app.errors import IdempotencyConflictError
from backend.app.observability import PROFILE_UPDATES, USER_EVENTS
from backend.app.routers.auth import (
    authorize_user_access,
    get_auth_service_factory,
    require_current_user_when_auth_enabled,
)
from backend.app.schemas.event_track import EventTrackRequest, EventTrackResponse
from backend.app.services.product import ProductService

router = APIRouter(prefix="/event", tags=["product"])


def _record_event(
    payload: EventTrackRequest,
    service: ProductService,
    current_user: AuthenticatedUser | None,
    auth_service_factory: Callable[[], AuthService],
) -> EventTrackResponse:
    authorize_user_access(payload.user_id, current_user, auth_service_factory)
    try:
        response = service.record_tracked_event(payload)
        USER_EVENTS.labels(
            source_space=response.source_space,
            event_type=response.event_type,
        ).inc()
        if response.profile_updated:
            PROFILE_UPDATES.labels(source_space=response.source_space).inc()
        return response
    except IdempotencyConflictError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/track", response_model=EventTrackResponse)
def track_event(
    payload: EventTrackRequest,
    service: ProductService = Depends(get_product_service),
    current_user: AuthenticatedUser | None = Depends(require_current_user_when_auth_enabled),
    auth_service_factory: Callable[[], AuthService] = Depends(get_auth_service_factory),
) -> EventTrackResponse:
    return _record_event(payload, service, current_user, auth_service_factory)


@router.post("/track/beacon", response_model=EventTrackResponse)
async def track_event_beacon(
    request: Request,
    service: ProductService = Depends(get_product_service),
    current_user: AuthenticatedUser | None = Depends(require_current_user_when_auth_enabled),
    auth_service_factory: Callable[[], AuthService] = Depends(get_auth_service_factory),
) -> EventTrackResponse:
    try:
        payload = EventTrackRequest.model_validate_json(await request.body())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid beacon event payload") from exc
    return _record_event(payload, service, current_user, auth_service_factory)
