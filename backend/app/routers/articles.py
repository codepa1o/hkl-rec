from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path

from backend.app.dependencies import get_product_service
from backend.app.schemas.article import ArticleCardResponse
from backend.app.services.product import ProductService

router = APIRouter(prefix="/articles", tags=["product"])


@router.get("/{news_id}", response_model=ArticleCardResponse)
def get_article(
    news_id: str = Path(..., pattern=r"^N[0-9]+$", description="Canonical MIND news ID."),
    service: ProductService = Depends(get_product_service),
) -> ArticleCardResponse:
    try:
        return service.get_article_card(news_id=news_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
