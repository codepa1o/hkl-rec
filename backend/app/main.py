from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.config import get_settings
from backend.app.errors import (
    IdempotencyConflictError,
    RepositoryNotReadyError,
    SearchIndexNotReadyError,
    UnknownCategoryError,
    UnresolvedQueryError,
)
from backend.app.events.publisher import EventPublishError
from backend.app.observability import (
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS,
    configure_logging,
)
from backend.app.routers.articles import router as articles_router
from backend.app.routers.auth import (
    require_current_user_when_auth_enabled,
)
from backend.app.routers.auth import (
    router as auth_router,
)
from backend.app.routers.categories import router as categories_router
from backend.app.routers.debug import router as debug_router
from backend.app.routers.event import router as event_router
from backend.app.routers.event_track import router as event_track_router
from backend.app.routers.feed import router as feed_router
from backend.app.routers.health import router as health_router
from backend.app.routers.personas import router as personas_router
from backend.app.routers.search import router as search_router
from backend.app.routers.suggestions import router as suggestions_router

logger = logging.getLogger(__name__)


def metric_path(request: Request) -> str:
    route = request.scope.get("route")
    return str(getattr(route, "path", "__unmatched__"))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        from backend.app.repositories.ranker import load_model

        load_model()
    except FileNotFoundError:
        pass
    yield


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        summary="News recommendation serving and event-pipeline prototype",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def observe_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4().hex}"
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            path = metric_path(request)
            duration = time.perf_counter() - started
            HTTP_REQUESTS.labels(
                method=request.method,
                path=path,
                status="500",
            ).inc()
            HTTP_REQUEST_DURATION.labels(method=request.method, path=path).observe(duration)
            logger.exception(
                "http request failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": path,
                    "duration_ms": round(duration * 1000, 3),
                },
            )
            raise
        path = metric_path(request)
        duration = time.perf_counter() - started
        HTTP_REQUESTS.labels(
            method=request.method,
            path=path,
            status=str(response.status_code),
        ).inc()
        HTTP_REQUEST_DURATION.labels(method=request.method, path=path).observe(duration)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "http request complete",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration_ms": round(duration * 1000, 3),
            },
        )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(RepositoryNotReadyError)
    async def repository_not_ready_handler(
        request: Request,
        exc: RepositoryNotReadyError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": str(exc),
                "error_code": "repository_not_ready",
                "operation": exc.operation,
                "path": request.url.path,
            },
        )

    @app.exception_handler(UnresolvedQueryError)
    async def unresolved_query_handler(
        request: Request,
        exc: UnresolvedQueryError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": str(exc),
                "error_code": "unresolved_query",
                "query_input": exc.query_input,
                "path": request.url.path,
            },
        )

    @app.exception_handler(SearchIndexNotReadyError)
    async def search_index_not_ready_handler(
        request: Request,
        exc: SearchIndexNotReadyError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": str(exc),
                "error_code": "search_index_not_ready",
                "path": request.url.path,
            },
        )

    @app.exception_handler(EventPublishError)
    async def event_publish_error_handler(
        request: Request,
        exc: EventPublishError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": str(exc),
                "error_code": "event_publish_failed",
                "path": request.url.path,
            },
        )

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict_handler(
        request: Request,
        exc: IdempotencyConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "error_code": "idempotency_conflict",
                "path": request.url.path,
            },
        )

    @app.exception_handler(UnknownCategoryError)
    async def unknown_category_handler(
        request: Request,
        exc: UnknownCategoryError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": str(exc),
                "error_code": "unknown_category",
                "category": exc.category,
                "path": request.url.path,
            },
        )

    app.include_router(health_router)
    app.include_router(auth_router)
    auth_dependency = [Depends(require_current_user_when_auth_enabled)]
    app.include_router(feed_router, dependencies=auth_dependency)
    app.include_router(search_router, dependencies=auth_dependency)
    app.include_router(event_router, dependencies=auth_dependency)
    app.include_router(debug_router, dependencies=auth_dependency)
    app.include_router(personas_router, dependencies=auth_dependency)
    app.include_router(categories_router, dependencies=auth_dependency)
    app.include_router(suggestions_router, dependencies=auth_dependency)
    app.include_router(articles_router, dependencies=auth_dependency)
    app.include_router(event_track_router, dependencies=auth_dependency)

    return app


app = create_app()
