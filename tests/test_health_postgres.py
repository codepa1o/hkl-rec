from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from backend.app.config import Settings
from backend.app.health import check_readiness

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not os.environ.get("NEWSREC_DATABASE_URL", "").strip(),
        reason="NEWSREC_DATABASE_URL not set",
    ),
]


def test_kafka_readiness_requires_worker_heartbeats(monkeypatch):
    class FakeAdminClient:
        def __init__(self, _config):
            pass

        def list_topics(self, timeout):
            return SimpleNamespace(
                topics={
                    "newsrec.events.raw": object(),
                    "newsrec.training.interactions": object(),
                    "newsrec.events.dlq": object(),
                }
            )

    monkeypatch.setattr(
        "backend.app.health.importlib.import_module",
        lambda _name: SimpleNamespace(AdminClient=FakeAdminClient),
    )
    settings = Settings(
        database_url=os.environ["NEWSREC_DATABASE_URL"],
        event_mode="kafka_async",
        search_retrieval_mode="lexical_v1",
    )

    readiness = check_readiness(settings)

    assert readiness.status == "error"
    assert readiness.dependencies["workers"].status == "error"
    assert "missing heartbeat" in str(readiness.dependencies["workers"].detail)
