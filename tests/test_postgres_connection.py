from __future__ import annotations

from typing import Any

import pytest

from backend.app.repositories.connection import (
    PostgresConnectionConfig,
    parse_database_url,
    transaction,
)


def test_parse_database_url_accepts_psycopg_url_and_decodes_credentials() -> None:
    config = parse_database_url(
        "postgresql+psycopg://news%40user:p%2Fass@db.internal:5544/news%2Drec?sslmode=require"
    )

    assert config == PostgresConnectionConfig(
        host="db.internal",
        port=5544,
        user="news@user",
        password="p/ass",
        database="news-rec",
        sslmode="require",
    )


def test_parse_database_url_uses_postgresql_default_port() -> None:
    config = parse_database_url("postgresql://newsrec:secret@localhost/newsrec_demo")

    assert config.port == 5432
    assert config.sslmode is None


@pytest.mark.parametrize(
    "database_url",
    [
        "mysql+pymysql://root:root@localhost/newsrec_demo",
        "postgresql://user@/newsrec_demo",
        "postgresql://localhost/newsrec_demo",
        "postgresql://user@localhost/",
    ],
)
def test_parse_database_url_rejects_non_postgres_or_incomplete_urls(database_url: str) -> None:
    with pytest.raises(ValueError):
        parse_database_url(database_url)


class FakeTransaction:
    def __init__(self) -> None:
        self.entered = False
        self.exited_with: type[BaseException] | None = None

    def __enter__(self) -> FakeTransaction:
        self.entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        self.exited_with = exc_type


class FakeConnection:
    def __init__(self) -> None:
        self.tx = FakeTransaction()

    def transaction(self) -> FakeTransaction:
        return self.tx


def test_transaction_uses_psycopg_transaction_context() -> None:
    connection = FakeConnection()

    with transaction(connection):
        assert connection.tx.entered is True

    assert connection.tx.exited_with is None


def test_transaction_propagates_error_to_psycopg_context() -> None:
    connection = FakeConnection()

    with pytest.raises(RuntimeError, match="boom"), transaction(connection):
        raise RuntimeError("boom")

    assert connection.tx.exited_with is RuntimeError
