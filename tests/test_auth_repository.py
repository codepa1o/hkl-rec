from __future__ import annotations

import pytest
from psycopg.errors import UniqueViolation

from backend.app.auth.repository import PostgresAuthRepository
from backend.app.errors import RepositoryNotReadyError


class FakeCursor:
    def __init__(self, *, seed_exists: bool = True, next_user_id: int = 1_000_000_000) -> None:
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.lastrowid = 7004
        self.rowcount = 0
        self.seed_exists = seed_exists
        self.next_user_id = next_user_id

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))
        self.rowcount = 1 if "INSERT INTO user_profile" in sql and self.seed_exists else 0

    def fetchone(self) -> dict[str, int]:
        return {"next_user_id": self.next_user_id}


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.began = False
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def begin(self) -> None:
        self.began = True

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    def connect(self) -> FakeConnection:
        return self._connection


def repository_with(connection: FakeConnection) -> PostgresAuthRepository:
    repository = object.__new__(PostgresAuthRepository)
    repository._pool = FakePool(connection)  # type: ignore[attr-defined]
    repository._cold_start_seed_key = "cold_start_default"  # type: ignore[attr-defined]
    return repository


def test_create_account_writes_identity_credentials_and_cold_start_profile_atomically() -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)

    account = repository_with(connection).create_account(
        "reader@example.com", "新闻读者", "$argon2id$hash"
    )

    assert account.user_id == 1_000_000_000
    assert connection.began and connection.committed and not connection.rolled_back
    assert connection.closed
    assert ["INSERT INTO app_user" in sql for sql, _ in cursor.executions].count(True) == 1
    assert ["FOR UPDATE" in sql for sql, _ in cursor.executions].count(True) == 1
    assert ["UPDATE auth_user_id_sequence" in sql for sql, _ in cursor.executions].count(True) == 1
    assert ["INSERT INTO user_account" in sql for sql, _ in cursor.executions].count(True) == 1
    assert ["INSERT INTO user_profile" in sql for sql, _ in cursor.executions].count(True) == 1


def test_create_account_rolls_back_when_cold_start_seed_is_missing() -> None:
    connection = FakeConnection(FakeCursor(seed_exists=False))

    with pytest.raises(RepositoryNotReadyError):
        repository_with(connection).create_account(
            "reader@example.com", "新闻读者", "$argon2id$hash"
        )

    assert connection.rolled_back and not connection.committed
    assert connection.closed


def test_non_email_duplicate_key_is_not_reported_as_duplicate_email(monkeypatch) -> None:
    error = UniqueViolation("duplicate primary key")
    connection = FakeConnection(FakeCursor())

    def fail_execute(_sql: str, _params: tuple[object, ...]) -> None:
        raise error

    monkeypatch.setattr(connection._cursor, "execute", fail_execute)

    with pytest.raises(UniqueViolation) as raised:
        repository_with(connection).create_account(
            "reader@example.com", "新闻读者", "$argon2id$hash"
        )

    assert raised.value is error
