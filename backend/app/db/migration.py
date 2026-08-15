from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from urllib.parse import unquote, urlparse

from sqlalchemy import Boolean, Table, create_engine, func, select, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.db.schema import metadata

ALEMBIC_HEAD = "20260814_0001"


@dataclass(frozen=True)
class TableMigrationResult:
    table: str
    source_rows: int
    target_rows: int
    source_sha256: str
    target_sha256: str


@dataclass(frozen=True)
class MigrationReport:
    source_database: str
    target_database: str
    alembic_revision: str
    tables: tuple[TableMigrationResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def migration_table_names() -> list[str]:
    return [table.name for table in metadata.sorted_tables]


def convert_row(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for column in table.columns:
        value = row[column.name]
        if value is not None and isinstance(column.type, JSONB):
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            if isinstance(value, str):
                value = json.loads(value)
        elif value is not None and isinstance(column.type, Boolean):
            value = bool(value)
        converted[column.name] = value
    return converted


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"decimal": format(value, "f")}
    if isinstance(value, datetime):
        return {"datetime": value.isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def canonical_row(columns: tuple[str, ...], row: dict[str, Any]) -> bytes:
    payload = [_canonical_value(row[column]) for column in columns]
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _mysql_connection(database_url: str) -> Any:
    import pymysql
    import pymysql.cursors

    parsed = urlparse(database_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise ValueError("source URL must start with mysql:// or mysql+pymysql://")
    database = unquote(parsed.path.lstrip("/"))
    if not parsed.hostname or not parsed.username or not database:
        raise ValueError("source MySQL URL must include host, username, and database")
    return pymysql.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=unquote(parsed.username),
        password=unquote(parsed.password or ""),
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def _postgres_sqlalchemy_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql+psycopg://"):
        return database_url
    raise ValueError("target URL must start with postgresql:// or postgresql+psycopg://")


def _database_name(database_url: str) -> str:
    return unquote(urlparse(database_url).path.lstrip("/"))


def _ensure_source_schema(source: Any) -> None:
    with source.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()"
        )
        existing = {str(row["TABLE_NAME"]) for row in cursor.fetchall()}
    missing = set(metadata.tables) - existing
    if missing:
        raise RuntimeError(f"source MySQL is missing tables: {', '.join(sorted(missing))}")


def _ensure_empty_target(target: Any) -> str:
    revision = target.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    if revision != ALEMBIC_HEAD:
        raise RuntimeError(
            f"target PostgreSQL must be at Alembic head {ALEMBIC_HEAD}, got {revision}"
        )
    nonempty: list[str] = []
    for table in metadata.sorted_tables:
        if table.name == "auth_user_id_sequence":
            continue
        count = int(target.execute(select(func.count()).select_from(table)).scalar_one())
        if count:
            nonempty.append(f"{table.name}={count}")
    if nonempty:
        raise RuntimeError("target PostgreSQL is not empty: " + ", ".join(nonempty))
    return cast(str, revision)


def _source_rows(source: Any, table: Table, batch_size: int) -> Any:
    columns = tuple(column.name for column in table.columns)
    order = ", ".join(f"`{column.name}`" for column in table.primary_key.columns)
    projection = ", ".join(f"`{column}`" for column in columns)
    cursor = source.cursor()
    cursor.execute(f"SELECT {projection} FROM `{table.name}` ORDER BY {order}")
    try:
        while rows := cursor.fetchmany(batch_size):
            yield [convert_row(table, row) for row in rows]
    finally:
        cursor.close()


def _digest_target(target: Any, table: Table) -> tuple[int, str]:
    columns = tuple(column.name for column in table.columns)
    statement = select(*table.columns).order_by(*table.primary_key.columns)
    digest = hashlib.sha256()
    count = 0
    for row in target.execute(statement).mappings():
        digest.update(canonical_row(columns, dict(row)))
        count += 1
    return count, digest.hexdigest()


def _reset_identity_sequences(target: Any) -> None:
    for table_name, column_name in (("user_event", "event_id"), ("event_outbox", "outbox_id")):
        target.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{table_name}', '{column_name}'), "
                f"COALESCE(MAX({column_name}), 0) + 1, false) FROM {table_name}"
            )
        )


def migrate_mysql_to_postgres(
    source_url: str,
    target_url: str,
    *,
    batch_size: int = 1000,
) -> MigrationReport:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    source = _mysql_connection(source_url)
    target_engine = create_engine(_postgres_sqlalchemy_url(target_url), pool_pre_ping=True)
    try:
        with source.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
        _ensure_source_schema(source)

        results: list[TableMigrationResult] = []
        with target_engine.begin() as target:
            revision = _ensure_empty_target(target)
            target.execute(metadata.tables["auth_user_id_sequence"].delete())

            for table in metadata.sorted_tables:
                columns = tuple(column.name for column in table.columns)
                source_digest = hashlib.sha256()
                source_count = 0
                for batch in _source_rows(source, table, batch_size):
                    for row in batch:
                        source_digest.update(canonical_row(columns, row))
                    source_count += len(batch)
                    target.execute(table.insert(), batch)

                target_count, target_digest = _digest_target(target, table)
                source_hash = source_digest.hexdigest()
                if target_count != source_count or target_digest != source_hash:
                    raise RuntimeError(
                        f"verification failed for {table.name}: "
                        f"source={source_count}/{source_hash}, "
                        f"target={target_count}/{target_digest}"
                    )
                results.append(
                    TableMigrationResult(
                        table=table.name,
                        source_rows=source_count,
                        target_rows=target_count,
                        source_sha256=source_hash,
                        target_sha256=target_digest,
                    )
                )

            _reset_identity_sequences(target)

        return MigrationReport(
            source_database=_database_name(source_url),
            target_database=_database_name(target_url),
            alembic_revision=revision,
            tables=tuple(results),
        )
    except Exception:
        source.rollback()
        raise
    finally:
        source.close()
        target_engine.dispose()
