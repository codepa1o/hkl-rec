from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.app.dependencies import get_product_service
from backend.app.news_spaces.types import NewsSpace
from backend.app.schemas.category import CategoryListResponse
from backend.app.services.product import ProductService

router = APIRouter(tags=["categories"])


@router.get("/categories", response_model=CategoryListResponse)
def list_categories(
    source_space: NewsSpace = Query("mind"),
    service: ProductService = Depends(get_product_service),
) -> CategoryListResponse:
    return service.list_categories(source_space=source_space)
