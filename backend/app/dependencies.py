from __future__ import annotations

import atexit
import logging
from functools import lru_cache

from backend.app.auth.repository import PostgresAuthRepository
from backend.app.auth.service import AuthService
from backend.app.config import Settings, get_settings
from backend.app.repositories.base import RuntimeRepository
from backend.app.repositories.postgres import PostgresRuntimeRepository
from backend.app.repositories.unwired import UnwiredRuntimeRepository
from backend.app.services.event import EventService
from backend.app.services.feed import FeedService
from backend.app.services.product import ProductService
from backend.app.services.profile import ProfileService
from backend.app.services.search import SearchService

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_runtime_repository() -> RuntimeRepository:
    settings = get_settings()
    if settings.database_configured:
        return PostgresRuntimeRepository(settings)
    return UnwiredRuntimeRepository(settings)


def get_feed_service() -> FeedService:
    return FeedService(get_runtime_repository())


def get_search_service() -> SearchService:
    return SearchService(get_runtime_repository())


def get_event_service() -> EventService:
    return EventService(get_runtime_repository())


def get_profile_service() -> ProfileService:
    return ProfileService(get_runtime_repository())


def get_product_service() -> ProductService:
    return ProductService(get_runtime_repository())


def get_repository_backend_name() -> str:
    return get_runtime_repository().backend_name


def get_app_settings() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def get_auth_repository() -> PostgresAuthRepository:
    return PostgresAuthRepository(get_settings())


def get_auth_service() -> AuthService:
    return AuthService(get_auth_repository())


def close_runtime_repository() -> None:
    if get_runtime_repository.cache_info().currsize:
        try:
            get_runtime_repository().close()
        except Exception:
            logger.exception("failed to close runtime repository")

    if get_auth_repository.cache_info().currsize:
        try:
            get_auth_repository().close()
        except Exception:
            logger.exception("failed to close auth repository")


atexit.register(close_runtime_repository)
