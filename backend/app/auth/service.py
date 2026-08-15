from __future__ import annotations

from dataclasses import dataclass

from backend.app.auth.repository import AccountRecord, AuthRepository
from backend.app.auth.security import hash_password, verify_password

_DUMMY_PASSWORD_HASH = hash_password("newsrec-auth-timing-placeholder")


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: int
    email: str
    display_name: str


class InvalidCredentialsError(ValueError):
    """Raised for every login failure without revealing which credential failed."""


class AccountNotFoundError(ValueError):
    """Raised when a valid session references an unavailable account."""


def _public_user(account: AccountRecord) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=account.user_id,
        email=account.email,
        display_name=account.display_name,
    )


class AuthService:
    def __init__(self, repository: AuthRepository) -> None:
        self._repository = repository

    def register(self, email: str, display_name: str, password: str) -> AuthenticatedUser:
        account = self._repository.create_account(
            email=email.strip().lower(),
            display_name=display_name.strip(),
            password_hash=hash_password(password),
        )
        return _public_user(account)

    def authenticate(self, email: str, password: str) -> AuthenticatedUser:
        account = self._repository.get_by_email(email.strip().lower())
        if account is None or not account.is_active:
            verify_password(password, _DUMMY_PASSWORD_HASH)
            raise InvalidCredentialsError("邮箱或密码错误")
        if not verify_password(password, account.password_hash):
            raise InvalidCredentialsError("邮箱或密码错误")
        return _public_user(account)

    def get_user(self, user_id: int) -> AuthenticatedUser:
        account = self._repository.get_by_user_id(user_id)
        if account is None or not account.is_active:
            raise AccountNotFoundError("账号不存在或已停用")
        return _public_user(account)

    def can_access_user(self, current_user: AuthenticatedUser, target_user_id: int) -> bool:
        return current_user.user_id == target_user_id or self._repository.is_demo_user(
            target_user_id
        )
