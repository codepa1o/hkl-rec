from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from backend.app.auth.security import (
    InvalidAccessTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SECRET = "test-secret-key-that-is-at-least-32-characters"


def test_password_is_argon2_hash_and_verifies() -> None:
    encoded = hash_password("correct horse battery staple")

    assert encoded.startswith("$argon2")
    assert "correct horse battery staple" not in encoded
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)


def test_access_token_round_trip() -> None:
    token = create_access_token(42, SECRET, expires_delta=timedelta(minutes=15))

    assert decode_access_token(token, SECRET) == 42


@pytest.mark.parametrize("kind", ["tampered", "expired"])
def test_access_token_rejects_invalid_tokens(kind: str) -> None:
    if kind == "tampered":
        token = create_access_token(42, SECRET, expires_delta=timedelta(minutes=15)) + "broken"
    else:
        token = jwt.encode(
            {
                "sub": "42",
                "iat": datetime.now(UTC) - timedelta(hours=2),
                "exp": datetime.now(UTC) - timedelta(hours=1),
            },
            SECRET,
            algorithm="HS256",
        )

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, SECRET)
