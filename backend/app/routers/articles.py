from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from backend.app.config import Settings, local_research_content_allowed
from backend.app.dependencies import get_app_settings, get_product_service
from backend.app.live_news import research_images
from backend.app.live_news.content_types import ContentAcquisitionError
from backend.app.news_spaces.types import NewsSpace
from backend.app.schemas.article import ArticleCardResponse, ContentEnsureResponse
from backend.app.services.product import ProductService

router = APIRouter(prefix="/articles", tags=["product"])


@router.get("/live/{article_id}/assets/{asset_id}")
def get_research_image(
    article_id: str = Path(..., pattern=r"^L[0-9a-f]{32}$"),
    asset_id: str = Path(..., pattern=r"^[0-9a-f]{32}$"),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    if not local_research_content_allowed(settings):
        raise HTTPException(status_code=404, detail="research image not available")
    try:
        body, media_type = research_images.load_research_image(settings, article_id, asset_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="research image not available") from exc
    except ContentAcquisitionError as exc:
        raise HTTPException(
            status_code=503 if exc.code == "image_busy" else 502,
            detail="publisher image temporarily unavailable",
        ) from exc
    return Response(
        body,
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/live/{article_id}/content/ensure", response_model=ContentEnsureResponse)
def ensure_live_article_content(
    article_id: str = Path(..., pattern=r"^L[0-9a-f]{32}$"),
    service: ProductService = Depends(get_product_service),
) -> ContentEnsureResponse:
    try:
        return service.ensure_article_content(source_space="live", article_id=article_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{source_space}/{article_id}", response_model=ArticleCardResponse)
def get_source_article(
    source_space: NewsSpace,
    article_id: str = Path(..., min_length=2, max_length=64),
    service: ProductService = Depends(get_product_service),
) -> ArticleCardResponse:
    try:
        return service.get_article_card(source_space=source_space, article_id=article_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{news_id}", response_model=ArticleCardResponse)
def get_article(
    news_id: str = Path(..., pattern=r"^N[0-9]+$", description="Canonical MIND news ID."),
    service: ProductService = Depends(get_product_service),
) -> ArticleCardResponse:
    try:
        return service.get_article_card(source_space="mind", article_id=news_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
