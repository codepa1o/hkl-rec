from __future__ import annotations

from dataclasses import replace

import pytest

import backend.app.auth.service as service_module
from backend.app.auth.repository import AccountRecord, DuplicateEmailError
from backend.app.auth.security import hash_password
from backend.app.auth.service import AuthService, InvalidCredentialsError


class MemoryAuthRepository:
    def __init__(self) -> None:
        self.accounts: dict[str, AccountRecord] = {}
        self.next_id = 7004

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
        return next((item for item in self.accounts.values() if item.user_id == user_id), None)

    def is_demo_user(self, user_id: int) -> bool:
        return False


def test_register_normalizes_email_and_hashes_password() -> None:
    repository = MemoryAuthRepository()
    service = AuthService(repository)

    user = service.register("  Reader@Example.COM ", "  新闻读者  ", "news-password")

    stored = repository.accounts["reader@example.com"]
    assert user.email == "reader@example.com"
    assert user.display_name == "新闻读者"
    assert stored.password_hash != "news-password"
    assert stored.password_hash.startswith("$argon2")


def test_register_rejects_duplicate_normalized_email() -> None:
    repository = MemoryAuthRepository()
    service = AuthService(repository)
    service.register("reader@example.com", "读者甲", "news-password")

    with pytest.raises(DuplicateEmailError):
        service.register(" READER@example.com ", "读者乙", "other-password")


def test_authenticate_accepts_correct_password() -> None:
    repository = MemoryAuthRepository()
    service = AuthService(repository)
    created = service.register("reader@example.com", "新闻读者", "news-password")

    authenticated = service.authenticate(" READER@example.com ", "news-password")

    assert authenticated.user_id == created.user_id


@pytest.mark.parametrize(
    ("email", "password"),
    [("missing@example.com", "news-password"), ("reader@example.com", "wrong-password")],
)
def test_authenticate_uses_generic_failure(email: str, password: str) -> None:
    repository = MemoryAuthRepository()
    repository.accounts["reader@example.com"] = AccountRecord(
        user_id=7004,
        email="reader@example.com",
        display_name="新闻读者",
        password_hash=hash_password("news-password"),
        is_active=True,
    )
    service = AuthService(repository)

    with pytest.raises(InvalidCredentialsError, match="邮箱或密码错误"):
        service.authenticate(email, password)


def test_authenticate_rejects_disabled_account() -> None:
    repository = MemoryAuthRepository()
    repository.accounts["reader@example.com"] = AccountRecord(
        user_id=7004,
        email="reader@example.com",
        display_name="新闻读者",
        password_hash=hash_password("news-password"),
        is_active=True,
    )
    repository.accounts["reader@example.com"] = replace(
        repository.accounts["reader@example.com"], is_active=False
    )

    with pytest.raises(InvalidCredentialsError, match="邮箱或密码错误"):
        AuthService(repository).authenticate("reader@example.com", "news-password")


def test_unknown_account_still_performs_password_verification(monkeypatch) -> None:
    repository = MemoryAuthRepository()
    verified_hashes: list[str] = []

    def record_verification(_password: str, password_hash: str) -> bool:
        verified_hashes.append(password_hash)
        return False

    monkeypatch.setattr(service_module, "verify_password", record_verification)

    with pytest.raises(InvalidCredentialsError):
        AuthService(repository).authenticate("missing@example.com", "news-password")

    assert len(verified_hashes) == 1
    assert verified_hashes[0].startswith("$argon2")
