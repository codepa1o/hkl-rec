from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

ALGORITHM = "HS256"
_password_hash = PasswordHash.recommended()


class InvalidAccessTokenError(ValueError):
    """Raised when a session token is missing valid authentication claims."""


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def create_access_token(
    user_id: int,
    secret_key: str,
    *,
    expires_delta: timedelta,
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + expires_delta},
        secret_key,
        algorithm=ALGORITHM,
    )


def decode_access_token(token: str, secret_key: str) -> int:
    try:
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
        subject = payload.get("sub")
        if subject is None:
            raise InvalidAccessTokenError("access token subject is missing")
        user_id = int(subject)
        if user_id <= 0:
            raise InvalidAccessTokenError("access token subject is invalid")
        return user_id
    except (InvalidTokenError, TypeError, ValueError) as exc:
        if isinstance(exc, InvalidAccessTokenError):
            raise
        raise InvalidAccessTokenError("access token is invalid or expired") from exc
