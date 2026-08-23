from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.auth.service import AuthenticatedUser, AuthService
from backend.app.dependencies import get_feed_service
from backend.app.news_spaces.types import LiveLanguage, NewsSpace
from backend.app.observability import NEWS_FEED_REQUESTS
from backend.app.routers.auth import (
    authorize_user_access,
    get_auth_service_factory,
    require_current_user_when_auth_enabled,
)
from backend.app.schemas.feed import FeedExperimentArm, FeedResponse, FeedUpdateStatusResponse
from backend.app.services.feed import FeedService

router = APIRouter(tags=["recommendation"])


@router.get("/feed/updates", response_model=FeedUpdateStatusResponse)
def get_feed_update_status(
    user_id: int = Query(..., description="Demo user ID."),
    source_space: NewsSpace = Query("mind"),
    language: LiveLanguage = Query("all"),
    since: datetime = Query(..., description="Timezone-aware feed watermark."),
    service: FeedService = Depends(get_feed_service),
    current_user: AuthenticatedUser | None = Depends(require_current_user_when_auth_enabled),
    auth_service_factory: Callable[[], AuthService] = Depends(get_auth_service_factory),
) -> FeedUpdateStatusResponse:
    authorize_user_access(user_id, current_user, auth_service_factory)
    if since.tzinfo is None or since.utcoffset() is None:
        raise HTTPException(status_code=422, detail="since must include a timezone")
    if source_space == "mind" and language != "all":
        raise HTTPException(
            status_code=422,
            detail="language filtering is only supported for source_space 'live'",
        )
    return service.get_feed_update_status(
        user_id=user_id,
        source_space=source_space,
        language=language,
        since=since,
    )


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    user_id: int = Query(..., description="Demo user ID."),
    page_size: int = Query(10, ge=1, le=50, description="Requested news item count."),
    debug: bool = Query(False, description="Whether to include debug fields."),
    experiment_arm: FeedExperimentArm = Query(
        "default",
        description="Debug/evaluation arm; default preserves product behavior.",
    ),
    include_sponsored: bool = Query(
        True,
        description="Whether the product feed may include sponsored candidates.",
    ),
    request_id: str | None = Query(
        None,
        min_length=1,
        max_length=128,
        description="Optional client idempotency key for one logical feed load.",
    ),
    cursor: str | None = Query(
        None,
        min_length=1,
        max_length=128,
        description="Opaque cursor returned by the preceding feed page.",
    ),
    as_of_ts: int | None = Query(
        None,
        ge=0,
        description="Evaluation-only event-time boundary for popularity features.",
    ),
    category: str | None = Query(
        None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9-]+$",
        description="可选的 MIND 一级新闻分类精确值。",
    ),
    source_space: NewsSpace = Query("mind"),
    language: LiveLanguage = Query("all"),
    service: FeedService = Depends(get_feed_service),
    current_user: AuthenticatedUser | None = Depends(require_current_user_when_auth_enabled),
    auth_service_factory: Callable[[], AuthService] = Depends(get_auth_service_factory),
) -> FeedResponse:
    authorize_user_access(user_id, current_user, auth_service_factory)
    response = service.get_feed(
        user_id=user_id,
        page_size=page_size,
        debug=debug,
        experiment_arm=experiment_arm,
        include_sponsored=include_sponsored,
        request_id=request_id,
        cursor=cursor,
        as_of_ts=as_of_ts,
        category=category,
        source_space=source_space,
        language=language,
    )
    NEWS_FEED_REQUESTS.labels(source_space=source_space).inc()
    return response
