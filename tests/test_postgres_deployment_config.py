from __future__ import annotations

from pathlib import Path


def test_primary_compose_runs_only_postgres() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "postgres:16-alpine" in compose
    assert "newsrec-postgres" in compose
    assert "mysql:8.0" not in compose
    assert not Path("docker-compose.mysql-legacy.yml").exists()


def test_example_environment_uses_postgres_and_full_mind_assets() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")

    assert "NEWSREC_DATABASE_URL=postgresql+psycopg://" in example
    assert "NEWSREC_MYSQL_SOURCE_URL" not in example
    assert "NEWSREC_MIND_NORMALIZED_DIR=build/mind_normalized" in example
    assert "NEWSREC_SEARCH_INDEX_DIR=build/mind_search/full" in example
    assert "NEWSREC_EVENT_MODE=sync_postgres" in example
    assert "NEWSREC_POSTGRES_POOL_MAX_CONNECTIONS=" in example


def test_ci_upgrades_alembic_and_runs_postgres_integration() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "postgres-integration:" in workflow
    assert "POSTGRES_DB: newsrec_ci_test" in workflow
    assert "python -m alembic upgrade head" in workflow
    assert "tests/test_import_mind_catalog.py -m postgres" in workflow
    assert "tests/test_kafka_integration.py -m kafka" in workflow
    assert "mysql:" not in workflow.lower()
