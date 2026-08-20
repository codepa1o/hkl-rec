from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from backend.app.auth.repository import AccountRecord
from backend.app.auth.security import hash_password
from backend.app.auth.service import AuthService
from backend.app.config import Settings, get_settings
from backend.app.dependencies import (
    get_app_settings,
    get_auth_service,
    get_profile_service,
    get_runtime_repository,
)
from backend.app.errors import ProfileNotInitializedError, ProfileSeedUnavailableError
from backend.app.main import create_app
from backend.app.routers.auth import get_auth_service_factory
from backend.app.schemas.profile import (
    DebugProfileResponse,
    ProfileResponse,
    ProfileTermLayer,
    VectorSummary,
)
from backend.app.services.profile import ProfileService


@pytest.fixture(autouse=True)
def isolate_runtime_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWSREC_DATABASE_URL", "")
    get_settings.cache_clear()
    get_runtime_repository.cache_clear()


@dataclass
class SingleUserAuthRepository:
    account: AccountRecord

    def create_account(self, email: str, display_name: str, password_hash: str) -> AccountRecord:
        raise AssertionError("registration is not used by profile route tests")

    def get_by_email(self, email: str) -> AccountRecord | None:
        return self.account if email == self.account.email else None

    def get_by_user_id(self, user_id: int) -> AccountRecord | None:
        return self.account if user_id == self.account.user_id else None

    def is_demo_user(self, user_id: int) -> bool:
        return False


@dataclass
class ProfileRouteRepository:
    profile_error: Exception | None = None
    reset_error: Exception | None = None
    profile_targets: list[tuple[int, str]] = field(default_factory=list)
    reset_targets: list[tuple[int, str]] = field(default_factory=list)
    debug_targets: list[tuple[int, str]] = field(default_factory=list)

    def _profile(self, user_id: int, source_space: str = "mind") -> ProfileResponse:
        return ProfileResponse(
            source_space=source_space,
            user_id=user_id,
            status="learning",
            confidence=0.25,
            evidence_count=3,
            short_term=ProfileTermLayer(),
            long_term=ProfileTermLayer(),
        )

    def get_profile(self, user_id: int, source_space: str = "mind") -> ProfileResponse:
        self.profile_targets.append((user_id, source_space))
        if self.profile_error is not None:
            raise self.profile_error
        return self._profile(user_id, source_space)

    def reset_profile(self, user_id: int, source_space: str = "mind") -> ProfileResponse:
        self.reset_targets.append((user_id, source_space))
        if self.reset_error is not None:
            raise self.reset_error
        return ProfileResponse(
            source_space=source_space,
            user_id=user_id,
            status="cold",
            confidence=0.0,
            evidence_count=0,
            short_term=ProfileTermLayer(),
            long_term=ProfileTermLayer(),
        )

    def get_debug_profile(self, user_id: int, source_space: str = "mind") -> DebugProfileResponse:
        self.debug_targets.append((user_id, source_space))
        return DebugProfileResponse(
            user_id=user_id,
            cold_start_seed_key="cold_start_default",
            behavior_score=0.0,
            topic_weights=[],
            recent_clicked_news=[],
            recent_queries=[],
            vector_summary=VectorSummary(vector_key_count=0, top_contributing_topics=[]),
        )


def _client(repository: ProfileRouteRepository) -> TestClient:
    settings = Settings(auth_secret_key="test-secret-key-that-is-at-least-32-characters")
    account = AccountRecord(
        user_id=7004,
        email="reader@example.com",
        display_name="Reader",
        password_hash=hash_password("news-password"),
        is_active=True,
    )
    auth_service = AuthService(SingleUserAuthRepository(account))
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_auth_service_factory] = lambda: lambda: auth_service
    app.dependency_overrides[get_profile_service] = lambda: ProfileService(repository)  # type: ignore[arg-type]
    return TestClient(app)


def _login(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"email": "reader@example.com", "password": "news-password"},
    )
    assert response.status_code == 200


def test_profile_requires_authenticated_session() -> None:
    response = _client(ProfileRouteRepository()).get("/profile")

    assert response.status_code == 401


def test_profile_uses_session_user_when_target_is_omitted() -> None:
    repository = ProfileRouteRepository()
    client = _client(repository)
    _login(client)

    response = client.get("/profile")

    assert response.status_code == 200
    assert response.json()["user_id"] == 7004
    assert response.json()["profile_version"] == "v2"
    assert repository.profile_targets == [(7004, "mind")]


def test_profile_rejects_an_unrelated_target_user() -> None:
    repository = ProfileRouteRepository()
    client = _client(repository)
    _login(client)

    response = client.get("/profile", params={"user_id": 7001, "source_space": "live"})

    assert response.status_code == 403
    assert repository.profile_targets == []


def test_profile_not_initialized_returns_stable_404_error() -> None:
    client = _client(ProfileRouteRepository(profile_error=ProfileNotInitializedError(7004)))
    _login(client)

    response = client.get("/profile")

    assert response.status_code == 404
    assert response.json()["error_code"] == "PROFILE_NOT_INITIALIZED"


def test_profile_reset_uses_session_user_and_returns_cold_profile() -> None:
    repository = ProfileRouteRepository()
    client = _client(repository)
    _login(client)

    response = client.post(
        "/profile/reset",
        json={"user_id": 7004, "source_space": "live"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cold"
    assert response.json()["evidence_count"] == 0
    assert response.json()["source_space"] == "live"
    assert repository.reset_targets == [(7004, "live")]


def test_profile_reset_rejects_untrusted_origin() -> None:
    repository = ProfileRouteRepository()
    client = _client(repository)
    _login(client)

    response = client.post(
        "/profile/reset",
        headers={"Origin": "https://attacker.example"},
        json={"user_id": 7004, "source_space": "mind"},
    )

    assert response.status_code == 403
    assert repository.reset_targets == []


def test_profile_reset_reports_missing_seed_as_service_unavailable() -> None:
    repository = ProfileRouteRepository(
        reset_error=ProfileSeedUnavailableError("cold_start_default")
    )
    client = _client(repository)
    _login(client)

    response = client.post(
        "/profile/reset",
        json={"user_id": 7004, "source_space": "mind"},
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "PROFILE_SEED_UNAVAILABLE"


def test_debug_profile_route_remains_available_for_compatible_research_access() -> None:
    repository = ProfileRouteRepository()
    client = _client(repository)
    _login(client)

    response = client.get("/debug/profile", params={"user_id": 7004})

    assert response.status_code == 200
    assert response.json()["user_id"] == 7004
    assert repository.debug_targets == [(7004, "mind")]
