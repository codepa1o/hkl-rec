from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from backend.app.auth.repository import AccountRecord, DuplicateEmailError
from backend.app.auth.service import AuthService
from backend.app.config import Settings, get_settings
from backend.app.dependencies import get_app_settings, get_auth_service, get_runtime_repository
from backend.app.main import create_app
from backend.app.routers.auth import _auth_attempts, get_auth_service_factory


@pytest.fixture(autouse=True)
def isolate_runtime_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWSREC_DATABASE_URL", "")
    get_settings.cache_clear()
    get_runtime_repository.cache_clear()


@dataclass
class MemoryAuthRepository:
    accounts: dict[str, AccountRecord]
    next_id: int = 7004
    demo_user_ids: frozenset[int] = frozenset({7001, 7002, 7003})

    def create_account(self, email: str, display_name: str, password_hash: str) -> AccountRecord:
        if email in self.accounts:
            raise DuplicateEmailError(email)
        account = AccountRecord(
            user_id=self.next_id,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            is_active=True,
        )
        self.next_id += 1
        self.accounts[email] = account
        return account

    def get_by_email(self, email: str) -> AccountRecord | None:
        return self.accounts.get(email)

    def get_by_user_id(self, user_id: int) -> AccountRecord | None:
        return next(
            (account for account in self.accounts.values() if account.user_id == user_id), None
        )

    def is_demo_user(self, user_id: int) -> bool:
        return user_id in self.demo_user_ids


@pytest.fixture
def auth_client() -> TestClient:
    _auth_attempts.clear()
    settings = Settings(auth_secret_key="test-secret-key-that-is-at-least-32-characters")
    service = AuthService(MemoryAuthRepository(accounts={}))
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_auth_service_factory] = lambda: lambda: service
    return TestClient(app)


def _register(client: TestClient) -> object:
    return client.post(
        "/auth/register",
        json={
            "email": "reader@example.com",
            "display_name": "新闻读者",
            "password": "news-password",
        },
    )


def test_register_sets_session_cookie_and_me_restores_user(auth_client: TestClient) -> None:
    response = _register(auth_client)

    assert response.status_code == 201
    assert response.json() == {
        "user_id": 7004,
        "email": "reader@example.com",
        "display_name": "新闻读者",
    }
    cookie = response.headers["set-cookie"].lower()
    assert "newsrec_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie

    current = auth_client.get("/auth/me")
    assert current.status_code == 200
    assert current.json()["email"] == "reader@example.com"


def test_register_rejects_duplicate_email(auth_client: TestClient) -> None:
    assert _register(auth_client).status_code == 201

    response = _register(auth_client)

    assert response.status_code == 409
    assert response.json()["detail"] == "该邮箱已注册"


def test_login_uses_generic_invalid_credentials_error(auth_client: TestClient) -> None:
    assert _register(auth_client).status_code == 201
    auth_client.cookies.clear()

    response = auth_client.post(
        "/auth/login",
        json={"email": "reader@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "邮箱或密码错误"


def test_me_rejects_missing_session(auth_client: TestClient) -> None:
    response = auth_client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "请先登录"


def test_logout_clears_session_and_blocks_me(auth_client: TestClient) -> None:
    assert _register(auth_client).status_code == 201

    response = auth_client.post("/auth/logout")

    assert response.status_code == 204
    assert "newsrec_session=" in response.headers["set-cookie"].lower()
    assert auth_client.get("/auth/me").status_code == 401


def test_login_restores_session_after_logout(auth_client: TestClient) -> None:
    assert _register(auth_client).status_code == 201
    assert auth_client.post("/auth/logout").status_code == 204

    response = auth_client.post(
        "/auth/login",
        json={"email": "reader@example.com", "password": "news-password"},
    )

    assert response.status_code == 200
    assert auth_client.get("/auth/me").json()["user_id"] == 7004


def test_custom_cookie_name_is_used_for_session_restore() -> None:
    _auth_attempts.clear()
    settings = Settings(
        auth_secret_key="test-secret-key-that-is-at-least-32-characters",
        auth_cookie_name="custom_session",
    )
    service = AuthService(MemoryAuthRepository(accounts={}))
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_auth_service_factory] = lambda: lambda: service
    client = TestClient(app)

    response = _register(client)

    assert "custom_session=" in response.headers["set-cookie"].lower()
    assert client.get("/auth/me").status_code == 200


def test_configured_auth_protects_business_routes(auth_client: TestClient) -> None:
    response = auth_client.get("/personas")
    assert response.status_code == 401

    assert _register(auth_client).status_code == 201
    response = auth_client.get("/personas")
    assert response.status_code != 401


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("GET", "/feed", {"params": {"user_id": 999_999}}),
        (
            "POST",
            "/search",
            {"json": {"user_id": 999_999, "query_key": "security"}},
        ),
        (
            "POST",
            "/event/recommendation_click",
            {"json": {"user_id": 999_999, "article_id": 1}},
        ),
        (
            "POST",
            "/event/search_result_click",
            {"json": {"user_id": 999_999, "article_id": 1, "query_key": "security"}},
        ),
        (
            "POST",
            "/event/track",
            {
                "json": {
                    "user_id": 999_999,
                    "event_type": "upvote",
                    "surface": "feed",
                    "article_id": 1,
                }
            },
        ),
        ("GET", "/debug/profile", {"params": {"user_id": 999_999}}),
    ],
)
def test_authenticated_user_cannot_access_another_registered_user(
    auth_client: TestClient,
    method: str,
    path: str,
    kwargs: dict[str, object],
) -> None:
    assert _register(auth_client).status_code == 201

    response = auth_client.request(method, path, **kwargs)

    assert response.status_code == 403
    assert response.json()["detail"] == "无权访问其他用户数据"


def test_authenticated_user_can_select_server_verified_demo_persona(
    auth_client: TestClient,
) -> None:
    assert _register(auth_client).status_code == 201

    response = auth_client.get("/feed", params={"user_id": 7001})

    assert response.status_code != 403


def test_disabled_auth_does_not_construct_auth_repository() -> None:
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: Settings(
        auth_secret_key="",
        allow_unauthenticated_research_api=True,
    )

    def unexpected_service() -> AuthService:
        raise AssertionError("auth service must stay lazy when authentication is disabled")

    app.dependency_overrides[get_auth_service_factory] = lambda: unexpected_service

    response = TestClient(app).get("/personas")
    assert response.status_code != 500


def test_missing_auth_secret_fails_closed_by_default() -> None:
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: Settings(auth_secret_key="")

    response = TestClient(app).get("/personas")

    assert response.status_code == 503
    assert response.json()["detail"] == "鉴权密钥未配置"


def test_untrusted_browser_origin_is_rejected(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/auth/register",
        headers={"Origin": "https://attacker.example"},
        json={
            "email": "reader@example.com",
            "display_name": "新闻读者",
            "password": "news-password",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "请求来源不受信任"


def test_auth_endpoint_is_rate_limited() -> None:
    _auth_attempts.clear()
    settings = Settings(
        auth_secret_key="test-secret-key-that-is-at-least-32-characters",
        auth_rate_limit_attempts=2,
    )
    service = AuthService(MemoryAuthRepository(accounts={}))
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_auth_service] = lambda: service
    client = TestClient(app)

    payload = {"email": "missing@example.com", "password": "wrong-password"}
    assert client.post("/auth/login", json=payload).status_code == 401
    assert client.post("/auth/login", json=payload).status_code == 401
    response = client.post("/auth/login", json=payload)

    assert response.status_code == 429


def test_production_requires_secure_cookie(auth_client: TestClient) -> None:
    settings = Settings(
        auth_secret_key="test-secret-key-that-is-at-least-32-characters",
        environment="production",
        auth_cookie_secure=False,
    )
    auth_client.app.dependency_overrides[get_app_settings] = lambda: settings

    response = _register(auth_client)

    assert response.status_code == 503
    assert response.json()["detail"] == "生产环境必须启用安全 Cookie"
