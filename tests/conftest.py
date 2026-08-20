from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.repositories.connection import connect, parse_database_url

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


@pytest.fixture
def unwired_client() -> TestClient:
    """强制使用 UnwiredRuntimeRepository 的 TestClient。

    绕过所有已配置的数据库 URL，使测试不受环境影响并保持封闭性。
    """
    from backend.app.config import Settings, get_settings
    from backend.app.dependencies import (
        get_app_settings,
        get_event_service,
        get_feed_service,
        get_product_service,
        get_profile_service,
        get_repository_backend_name,
        get_runtime_repository,
        get_search_service,
    )
    from backend.app.main import create_app
    from backend.app.repositories.unwired import UnwiredRuntimeRepository
    from backend.app.services.event import EventService
    from backend.app.services.feed import FeedService
    from backend.app.services.product import ProductService
    from backend.app.services.profile import ProfileService
    from backend.app.services.search import SearchService

    get_settings.cache_clear()
    get_runtime_repository.cache_clear()
    settings = Settings(allow_unauthenticated_research_api=True)
    unwired = UnwiredRuntimeRepository(settings)
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_repository_backend_name] = lambda: unwired.backend_name
    app.dependency_overrides[get_feed_service] = lambda: FeedService(unwired)
    app.dependency_overrides[get_search_service] = lambda: SearchService(unwired)
    app.dependency_overrides[get_event_service] = lambda: EventService(unwired)
    app.dependency_overrides[get_profile_service] = lambda: ProfileService(unwired)
    app.dependency_overrides[get_product_service] = lambda: ProductService(unwired)
    return TestClient(app)


def _database_url() -> str:
    return os.environ.get("NEWSREC_DATABASE_URL", "").strip()


@pytest.fixture
def postgres_connection() -> Iterator[Any]:
    """Yield a real dict-row PostgreSQL connection configured by the test environment."""
    database_url = _database_url()
    if not database_url:
        pytest.skip("NEWSREC_DATABASE_URL not set")
    connection = connect(parse_database_url(database_url))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database() AS database_name")
            database_name = str(cursor.fetchone()["database_name"])
        connection.rollback()
        if not database_name.endswith("_test"):
            pytest.fail(
                "postgres_connection requires NEWSREC_DATABASE_URL to name a *_test database"
            )
        yield connection
    finally:
        connection.close()


@dataclass(frozen=True)
class SeededLiveArticles:
    user_id: int
    article_ids: tuple[str, str]


@pytest.fixture
def seeded_live_articles(postgres_connection) -> Iterator[SeededLiveArticles]:
    user_id = 990_001
    article_ids = (
        "L0123456789abcdef0123456789abcdef",
        "Lfedcba9876543210fedcba9876543210",
    )
    rows = (
        (
            article_ids[0],
            "https://www.reuters.com/live-fixture-en",
            "Live English fixture",
            "Reuters",
            "www.reuters.com",
            "en",
            "e" * 64,
        ),
        (
            article_ids[1],
            "https://www.xinhuanet.com/live-fixture-zh",
            "实时中文测试新闻",
            "新华网",
            "www.xinhuanet.com",
            "zh",
            "c" * 64,
        ),
    )
    with postgres_connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO system_profile_seed (
              seed_key, source_space, topic_weights_json,
              recent_clicked_news_json, recent_queries_json,
              behavior_score, notes
            ) VALUES (
              'cold_start_default', 'mind', '[]'::jsonb,
              '[]'::jsonb, '[]'::jsonb, 0, 'Test MIND cold start'
            ) ON CONFLICT (seed_key) DO NOTHING
            """
        )
        cursor.execute(
            """
            INSERT INTO app_user (user_id, display_name, is_demo_user, source)
            VALUES (%s, 'Live test user', TRUE, 'live_test')
            ON CONFLICT (user_id) DO UPDATE SET display_name = EXCLUDED.display_name
            """,
            (user_id,),
        )
        cursor.executemany(
            """
            INSERT INTO live_news (
              article_id, canonical_url, title, summary, publisher,
              source_domain, language, published_at, published_at_quality,
              discovered_at, fetched_at, content_hash, status,
              raw_metadata_json, created_at, updated_at
            ) VALUES (
              %s, %s, %s, 'Fixture summary', %s, %s, %s,
              CURRENT_TIMESTAMP, 'gdelt_unverified',
              CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, %s, 'active',
              '{}'::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) ON CONFLICT (article_id) DO UPDATE SET
              title = EXCLUDED.title,
              discovered_at = CURRENT_TIMESTAMP,
              status = 'active'
            """,
            rows,
        )
    postgres_connection.commit()
    yield SeededLiveArticles(user_id=user_id, article_ids=article_ids)
    with postgres_connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM event_outbox WHERE payload_json ->> 'user_id' = %s",
            (str(user_id),),
        )
        cursor.execute(
            "DELETE FROM event_outbox WHERE event_id IN ("
            "SELECT external_event_id FROM event_idempotency WHERE user_id = %s)",
            (user_id,),
        )
        cursor.execute("DELETE FROM event_idempotency WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM user_event WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM feed_request WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM user_topic_profile WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM user_profile WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM app_user WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM live_news WHERE article_id = ANY(%s)", (list(article_ids),))
    postgres_connection.commit()


@pytest.fixture
def postgres_demo_user() -> int:
    """重置 PostgreSQL 中的默认研究用户，使可变状态保持可预测。"""
    if not _database_url():
        pytest.skip("NEWSREC_DATABASE_URL not set")
    subprocess.run(
        [PY, str(ROOT / "scripts" / "reset_demo_user.py")],
        check=True,
        cwd=ROOT,
    )
    return int(os.environ.get("NEWSREC_DEFAULT_DEMO_USER_ID", "7001"))


@pytest.fixture
def postgres_client() -> Iterator[TestClient]:
    """由真实 PostgresRuntimeRepository 支持的 TestClient。

    测试进程启动时必须设置 NEWSREC_DATABASE_URL。
    """
    if not _database_url():
        pytest.skip("NEWSREC_DATABASE_URL not set")
    from backend.app.config import get_settings
    from backend.app.dependencies import (
        close_runtime_repository,
        get_app_settings,
        get_auth_repository,
        get_runtime_repository,
    )
    from backend.app.main import create_app

    get_settings.cache_clear()
    get_runtime_repository.cache_clear()
    get_auth_repository.cache_clear()
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: replace(
        get_settings(),
        auth_secret_key="",
        allow_unauthenticated_research_api=True,
    )
    with TestClient(app) as client:
        yield client
    close_runtime_repository()
    get_runtime_repository.cache_clear()
    get_auth_repository.cache_clear()
