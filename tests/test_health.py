from __future__ import annotations

from datetime import UTC, datetime, timedelta


def test_livez_reports_process_health_without_dependencies(unwired_client):
    response = unwired_client.get("/livez")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["repository_backend"] == "unwired"
    assert body["database_configured"] is False
    assert body["dependencies"]["process"]["status"] == "ok"
    assert isinstance(body["app_name"], str)
    assert isinstance(body["app_version"], str)


def test_healthz_fails_when_postgres_is_not_configured(unwired_client):
    response = unwired_client.get("/healthz")
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["status"] == "error"
    assert body["dependencies"]["postgresql"]["status"] == "error"


def test_metrics_endpoint_exposes_prometheus_text(unwired_client):
    response = unwired_client.get("/metrics")
    assert response.status_code == 200
    assert "newsrec_http_requests_total" in response.text


def test_metrics_expose_source_and_collector_series(unwired_client):
    payload = unwired_client.get("/metrics").text
    assert "live_collector_last_success_timestamp" in payload
    assert "live_ingest_accepted_total" in payload
    assert "cross_space_validation_failures_total" in payload


def test_readiness_reports_disabled_live_collector():
    from backend.app.config import Settings
    from backend.app.health import check_readiness

    readiness = check_readiness(
        Settings(
            database_url="",
            search_retrieval_mode="lexical_v1",
            live_news_collector_enabled=False,
        )
    )

    assert readiness.dependencies["live_news_collector"].status == "disabled"


def test_live_collector_health_uses_durable_checkpoint_and_reports_staleness() -> None:
    from backend.app.config import Settings
    from backend.app.health import _live_collector_health

    now = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _query):
            return None

        def fetchone(self):
            return {
                "last_success_at": now - timedelta(minutes=10),
                "last_error": None,
            }

    class Connection:
        def cursor(self):
            return Cursor()

    health = _live_collector_health(
        Connection(),
        Settings(live_news_poll_interval_seconds=60),
        now=now,
    )

    assert health.status == "error"
    assert "last_success_age=600s" in str(health.detail)


def test_livez_does_not_open_postgres_connection():
    from fastapi.testclient import TestClient

    from backend.app.config import Settings
    from backend.app.dependencies import get_app_settings
    from backend.app.main import create_app

    settings = Settings(database_url="postgresql://newsrec:newsrec@127.0.0.1:1/unreachable")
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: settings

    response = TestClient(app).get("/livez")

    assert response.status_code == 200
    assert response.json()["repository_backend"] == "postgresql"


def test_unmatched_paths_use_bounded_metrics_label(unwired_client):
    first = unwired_client.get("/not-found/one")
    second = unwired_client.get("/not-found/two")

    assert first.status_code == 404
    assert second.status_code == 404
    metrics = unwired_client.get("/metrics").text
    assert 'path="__unmatched__"' in metrics
    assert 'path="/not-found/one"' not in metrics
    assert 'path="/not-found/two"' not in metrics


def test_readiness_reports_missing_hybrid_search_index(monkeypatch):
    from backend.app.config import Settings
    from backend.app.health import check_readiness
    from backend.app.search_retrieval import SearchArtifactError

    def fail_load(*_args, **_kwargs):
        raise SearchArtifactError("missing search artifact files: metadata.json")

    monkeypatch.setattr("backend.app.health.load_hybrid_search_index", fail_load)
    readiness = check_readiness(
        Settings(
            database_url="",
            search_retrieval_mode="hybrid_v1",
            search_index_dir="missing",
        )
    )

    assert readiness.status == "error"
    assert readiness.dependencies["search_index"].status == "error"
    assert "metadata.json" in str(readiness.dependencies["search_index"].detail)
