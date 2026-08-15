from __future__ import annotations

from pathlib import Path

from backend.app.auth.repository import PostgresAuthRepository
from backend.app.repositories.postgres import PostgresRuntimeRepository


def test_runtime_repository_reports_postgresql_backend() -> None:
    assert PostgresRuntimeRepository.backend_name == "postgresql"


def test_runtime_database_code_contains_no_mysql_only_sql() -> None:
    root = Path(__file__).resolve().parents[1] / "backend" / "app"
    sources = [
        root / "auth" / "repository.py",
        root / "repositories" / "postgres.py",
        root / "repositories" / "event_dao.py",
        root / "repositories" / "sponsored_dao.py",
        root / "events" / "outbox.py",
        root / "events" / "worker_state.py",
    ]
    mysql_only = (
        "ON DUPLICATE KEY",
        "VALUES(request_id)",
        "UNIX_TIMESTAMP()",
        "JSON_ARRAY()",
    )

    for source in sources:
        contents = source.read_text(encoding="utf-8")
        for token in mysql_only:
            assert token not in contents, f"{token} remains in {source.name}"


def test_auth_repository_is_postgresql_implementation() -> None:
    assert PostgresAuthRepository.__name__ == "PostgresAuthRepository"
