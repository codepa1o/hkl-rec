from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
    settings = Settings()
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
def mysql_demo_user() -> int:
    """重置已配置的第一个演示画像，使可变状态保持可预测。"""
    if not _database_url():
        pytest.skip("NEWSREC_DATABASE_URL not set")
    subprocess.run(
        [PY, str(ROOT / "scripts" / "reset_demo_user.py")],
        check=True,
        cwd=ROOT,
    )
    seed_dir = Path(os.environ.get("NEWSREC_DEMO_SEED_DIR", "build/mind_demo_world"))
    if not seed_dir.is_absolute():
        seed_dir = ROOT / seed_dir
    seed_path = seed_dir / "demo_user_profile_seed.json"
    if not seed_path.is_file():
        seed_path = ROOT / "build" / "mind_demo_fixture" / "demo_user_profile_seed.json"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    return int(seed["user_id"])


@pytest.fixture
def mysql_client() -> TestClient:
    """由真实 MysqlRuntimeRepository 支持的 TestClient。

    测试进程启动时必须设置 NEWSREC_DATABASE_URL。
    """
    if not _database_url():
        pytest.skip("NEWSREC_DATABASE_URL not set")
    from backend.app.config import get_settings
    from backend.app.dependencies import get_runtime_repository
    from backend.app.main import create_app

    get_settings.cache_clear()
    get_runtime_repository.cache_clear()
    return TestClient(create_app())
