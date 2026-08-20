from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.app.dependencies import get_product_service
from backend.app.news_spaces.types import NewsSpace
from backend.app.schemas.persona import PersonaListResponse
from backend.app.services.product import ProductService

router = APIRouter(tags=["product"])


@router.get("/personas", response_model=PersonaListResponse)
def list_personas(
    limit: int = Query(10, ge=1, le=50, description="Max personas to return."),
    source_space: NewsSpace = Query("mind"),
    service: ProductService = Depends(get_product_service),
) -> PersonaListResponse:
    return service.list_personas(limit=limit, source_space=source_space)
