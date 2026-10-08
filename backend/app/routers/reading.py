from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.auth.service import AuthenticatedUser
from backend.app.dependencies import get_runtime_repository
from backend.app.news_spaces.types import LiveLanguage, NewsSpace
from backend.app.reading.repository import ReadingRepository
from backend.app.routers.auth import get_current_user, require_trusted_origin
from backend.app.schemas.feed import FeedResponse
from backend.app.schemas.reading import (
    LibraryResponse,
    ReadingRuleDeleteRequest,
    ReadingRuleListResponse,
    ReadingRuleRequest,
    ReadingRuleResponse,
    ReadingSearchRequest,
    ReadingSearchResponse,
    ReadingStateListResponse,
    ReadingStateRequest,
    ReadingStateResponse,
    SavedSearchDeleteRequest,
    SavedSearchListResponse,
    SavedSearchRequest,
    SavedSearchResponse,
)
from backend.app.schemas.search import SearchRequest

router = APIRouter(prefix="/reading", tags=["reading"])


def _repository(runtime: Any = Depends(get_runtime_repository)) -> ReadingRepository:
    return ReadingRepository(runtime)


@router.get("/states", response_model=ReadingStateListResponse)
def get_states(
    source_space: NewsSpace = Query("mind"),
    article_ids: str = Query(..., min_length=1, max_length=8192),
    user: AuthenticatedUser = Depends(get_current_user),
    repo: ReadingRepository = Depends(_repository),
) -> ReadingStateListResponse:
    ids = list(dict.fromkeys(value.strip() for value in article_ids.split(",") if value.strip()))
    if not ids or len(ids) > 100:
        raise HTTPException(422, "请求文章数量必须在 1 到 100 之间")
    try:
        from backend.app.news_spaces.types import validate_article_id_shape

        for article_id in ids:
            validate_article_id_shape(source_space, article_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with repo.connection() as connection:
        values = repo.states(connection, user.user_id, source_space, ids)
    return ReadingStateListResponse(items=values)


@router.post("/state", response_model=ReadingStateResponse)
def update_state(
    payload: ReadingStateRequest,
    _origin: None = Depends(require_trusted_origin),
    user: AuthenticatedUser = Depends(get_current_user),
    repo: ReadingRepository = Depends(_repository),
) -> ReadingStateResponse:
    return ReadingStateResponse(**repo.write_state(user.user_id, payload))


@router.get("/library", response_model=LibraryResponse)
def get_library(
    source_space: NewsSpace = Query("mind"),
    saved_only: bool = Query(True),
    unread_only: bool = Query(False),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    user: AuthenticatedUser = Depends(get_current_user),
    repo: ReadingRepository = Depends(_repository),
) -> LibraryResponse:
    return LibraryResponse(
        **repo.library(user.user_id, source_space, saved_only, unread_only, offset, limit)
    )


@router.get("/rules", response_model=ReadingRuleListResponse)
def get_rules(
    source_space: NewsSpace = Query("mind"),
    user: AuthenticatedUser = Depends(get_current_user),
    repo: ReadingRepository = Depends(_repository),
) -> ReadingRuleListResponse:
    with repo.connection() as connection:
        return ReadingRuleListResponse(items=repo.rules(connection, user.user_id, source_space))


@router.post("/rules", response_model=ReadingRuleResponse)
def upsert_rule(
    payload: ReadingRuleRequest,
    _origin: None = Depends(require_trusted_origin),
    user: AuthenticatedUser = Depends(get_current_user),
    repo: ReadingRepository = Depends(_repository),
) -> ReadingRuleResponse:
    return ReadingRuleResponse(**repo.write_rule(user.user_id, payload))


@router.post("/rules/{rule_id}/delete")
def remove_rule(
    rule_id: int,
    payload: ReadingRuleDeleteRequest,
    _origin: None = Depends(require_trusted_origin),
    user: AuthenticatedUser = Depends(get_current_user),
    repo: ReadingRepository = Depends(_repository),
) -> dict[str, bool]:
    return repo.delete(user.user_id, payload.source_space, "rule", rule_id)


@router.get("/searches", response_model=SavedSearchListResponse)
def get_saved_searches(
    source_space: NewsSpace = Query("mind"),
    user: AuthenticatedUser = Depends(get_current_user),
    repo: ReadingRepository = Depends(_repository),
) -> SavedSearchListResponse:
    with repo.connection() as connection:
        return SavedSearchListResponse(items=repo.searches(connection, user.user_id, source_space))


@router.post("/searches", response_model=SavedSearchResponse)
def upsert_saved_search(
    payload: SavedSearchRequest,
    _origin: None = Depends(require_trusted_origin),
    user: AuthenticatedUser = Depends(get_current_user),
    repo: ReadingRepository = Depends(_repository),
) -> SavedSearchResponse:
    return SavedSearchResponse(**repo.write_search(user.user_id, payload))


@router.post("/searches/{search_id}/delete")
def remove_saved_search(
    search_id: int,
    payload: SavedSearchDeleteRequest,
    _origin: None = Depends(require_trusted_origin),
    user: AuthenticatedUser = Depends(get_current_user),
    repo: ReadingRepository = Depends(_repository),
) -> dict[str, bool]:
    return repo.delete(user.user_id, payload.source_space, "search", search_id)


@router.get("/feed", response_model=FeedResponse)
def get_reading_feed(
    source_space: NewsSpace = Query("mind"),
    language: LiveLanguage = Query("all"),
    category: str | None = Query(None, min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$"),
    unread_only: bool = Query(False),
    page_size: int = Query(20, ge=1, le=50),
    request_id: str = Query(..., min_length=1, max_length=128),
    cursor: str | None = Query(None, min_length=1, max_length=128),
    user: AuthenticatedUser = Depends(get_current_user),
    repo: ReadingRepository = Depends(_repository),
) -> FeedResponse:
    return repo.feed(
        user.user_id, source_space, language, category, unread_only, page_size, request_id, cursor
    )


@router.post("/search", response_model=ReadingSearchResponse)
def search_with_rules(
    payload: ReadingSearchRequest,
    _origin: None = Depends(require_trusted_origin),
    user: AuthenticatedUser = Depends(get_current_user),
    repo: ReadingRepository = Depends(_repository),
) -> ReadingSearchResponse:
    search_request = SearchRequest(
        user_id=user.user_id,
        source_space=payload.source_space,
        event_id=payload.event_id,
        query_text=payload.query,
        page_size=50,
    )
    response = repo.runtime.search(search_request)
    with repo.connection() as connection:
        rules = repo.rules(connection, user.user_id, payload.source_space)
        allowed_ids = None
        if payload.category is not None or payload.language != "all":
            allowed_ids = {
                row["article_id"]
                for row in repo.catalog(
                    connection,
                    payload.source_space,
                    payload.language,
                    payload.category,
                )
            }
    retained = []
    hidden_count = 0
    for item in response.items:
        if allowed_ids is not None and item.article_id not in allowed_ids:
            continue
        article = {
            "title": item.title,
            "abstract": item.abstract,
            "source_domain": item.source_domain,
            "category": item.category,
            "subcategory": item.subcategory,
            "topics": [topic.display_name for topic in item.categories],
        }
        from backend.app.reading.policy import evaluate_rules

        blocked, boost, _ = evaluate_rules(article, rules)
        if blocked:
            hidden_count += 1
            if not payload.include_hidden:
                continue
        item.scores.final_score = round(item.scores.final_score + boost, 6)
        retained.append(item)
    retained.sort(key=lambda item: (-item.scores.final_score, item.article_id))
    visible = retained[: payload.page_size]
    result = response.model_dump()
    result.update(user_id=user.user_id, items=visible, hidden_count=hidden_count)
    return ReadingSearchResponse(**result)
