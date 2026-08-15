from __future__ import annotations

from pathlib import Path


def test_primary_compose_runs_postgres_and_keeps_legacy_mysql_separate() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    legacy = Path("docker-compose.mysql-legacy.yml").read_text(encoding="utf-8")

    assert "postgres:16-alpine" in compose
    assert "newsrec-postgres" in compose
    assert "mysql:8.0" not in compose
    assert "mysql:8.0" in legacy
    assert "newsrec-mysql" in legacy


def test_example_environment_uses_postgres_runtime_and_mysql_source() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")

    assert "NEWSREC_DATABASE_URL=postgresql+psycopg://" in example
    assert "NEWSREC_MYSQL_SOURCE_URL=mysql+pymysql://" in example
    assert "NEWSREC_EVENT_MODE=sync_postgres" in example
    assert "NEWSREC_POSTGRES_POOL_MAX_CONNECTIONS=" in example


def test_ci_upgrades_alembic_and_runs_postgres_integration() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "postgres-integration:" in workflow
    assert "python -m alembic upgrade head" in workflow
    assert 'python -m pytest -q -m "postgres and not kafka"' in workflow
