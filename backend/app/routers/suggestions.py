from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.app.dependencies import get_product_service
from backend.app.news_spaces.types import NewsSpace
from backend.app.schemas.suggestion import SuggestionListResponse
from backend.app.services.product import ProductService

router = APIRouter(prefix="/search", tags=["product"])


@router.get("/suggestions", response_model=SuggestionListResponse)
def list_search_suggestions(
    limit: int = Query(12, ge=1, le=50, description="Max suggestions to return."),
    source_space: NewsSpace = Query("mind"),
    service: ProductService = Depends(get_product_service),
) -> SuggestionListResponse:
    return service.list_search_suggestions(limit=limit, source_space=source_space)
