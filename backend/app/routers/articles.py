from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path

from backend.app.dependencies import get_product_service
from backend.app.news_spaces.types import NewsSpace
from backend.app.schemas.article import ArticleCardResponse, ContentEnsureResponse
from backend.app.services.product import ProductService

router = APIRouter(prefix="/articles", tags=["product"])


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
