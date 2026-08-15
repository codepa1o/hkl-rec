from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


@dataclass(frozen=True)
class PostgresConnectionConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    sslmode: str | None = None


def parse_database_url(database_url: str) -> PostgresConnectionConfig:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError(
            "NEWSREC_DATABASE_URL must start with postgresql:// or postgresql+psycopg://"
        )
    if not parsed.hostname:
        raise ValueError("NEWSREC_DATABASE_URL must include a host")
    if not parsed.username:
        raise ValueError("NEWSREC_DATABASE_URL must include a username")

    database = parsed.path.lstrip("/")
    if not database:
        raise ValueError("NEWSREC_DATABASE_URL must include a database name")

    query = parse_qs(parsed.query)
    sslmode_values = query.get("sslmode", [])
    return PostgresConnectionConfig(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=unquote(parsed.username),
        password=unquote(parsed.password or ""),
        database=unquote(database),
        sslmode=sslmode_values[-1] if sslmode_values else None,
    )


def _conninfo(config: PostgresConnectionConfig, *, connect_timeout: int) -> str:
    from psycopg.conninfo import make_conninfo

    if config.sslmode:
        return make_conninfo(
            "",
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            dbname=config.database,
            connect_timeout=connect_timeout,
            sslmode=config.sslmode,
        )
    return make_conninfo(
        "",
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        dbname=config.database,
        connect_timeout=connect_timeout,
    )


def connect(
    config: PostgresConnectionConfig,
    *,
    connect_timeout: int = 5,
) -> Any:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(
        _conninfo(config, connect_timeout=connect_timeout),
        row_factory=dict_row,
    )


class _PooledConnection:
    def __init__(self, pool: Any, connection: Any) -> None:
        self._pool = pool
        self._connection = connection
        self._returned = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def begin(self) -> None:
        """Keep the repository transaction boundary API used before psycopg."""

    def close(self) -> None:
        if not self._returned:
            self._pool.putconn(self._connection)
            self._returned = True


class PostgresConnectionPool:
    def __init__(
        self,
        config: PostgresConnectionConfig,
        *,
        connect_timeout: int = 5,
        min_size: int = 1,
        max_connections: int = 10,
    ) -> None:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        self._pool: Any = ConnectionPool(
            conninfo=_conninfo(config, connect_timeout=connect_timeout),
            min_size=max(0, min_size),
            max_size=max(1, max_connections),
            kwargs={"row_factory": dict_row},
            open=True,
        )

    def connect(self) -> Any:
        return _PooledConnection(self._pool, self._pool.getconn())

    def close(self) -> None:
        self._pool.close()


@contextmanager
def transaction(connection: Any) -> Iterator[Any]:
    transaction_factory = getattr(connection, "transaction", None)
    if callable(transaction_factory):
        with transaction_factory():
            yield connection
        return
    connection.begin()
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
