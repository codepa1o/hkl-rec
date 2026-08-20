from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.config import Settings
from backend.app.dependencies import get_app_settings
from backend.app.schemas.news_space import NewsSpaceCapability, NewsSpaceListResponse

router = APIRouter(tags=["product"])


@router.get("/news-spaces", response_model=NewsSpaceListResponse)
def list_news_spaces(
    settings: Settings = Depends(get_app_settings),
) -> NewsSpaceListResponse:
    return NewsSpaceListResponse(
        items=[
            NewsSpaceCapability(source_space="mind", enabled=True),
            NewsSpaceCapability(
                source_space="live",
                enabled=settings.live_news_enabled,
            ),
        ]
    )
