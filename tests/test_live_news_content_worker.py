from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app.live_news.content_policy import ContentPolicy
from backend.app.live_news.content_types import (
    AcquiredContent,
    ContentAcquisitionError,
    ContentJob,
    ContentRequest,
)
from backend.app.live_news.content_worker import LiveNewsContentWorker, ProviderRegistry

NOW = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
BODY = " ".join(["A complete article paragraph with enough verified content."] * 12)
REQUEST = ContentRequest(
    article_id="L0123456789abcdef0123456789abcdef",
    canonical_url="https://example.com/story",
    expected_domain="example.com",
    language="en",
    policy=ContentPolicy("html", "full_text"),
)
JOB = ContentJob(REQUEST.article_id, REQUEST, "full_text", 1)


class FakeStore:
    def __init__(self, jobs: list[ContentJob] | None = None) -> None:
        self.jobs = list(jobs or [])
        self.calls: list[str] = []
        self.completed: list[tuple[ContentJob, AcquiredContent]] = []
        self.retried: list[tuple[ContentJob, str, datetime]] = []
        self.finished: list[tuple[ContentJob, str, str]] = []

    def recover_stale(self, stale_before: datetime) -> int:
        self.calls.append("recover")
        return 0

    def claim_due(self, worker_id: str, limit: int, now: datetime) -> list[ContentJob]:
        self.calls.append("claim")
        return self.jobs[:limit]

    def complete(self, job: ContentJob, acquired: AcquiredContent) -> None:
        self.completed.append((job, acquired))

    def retry(
        self,
        job: ContentJob,
        *,
        code: str,
        detail: str,
        next_attempt_at: datetime,
    ) -> None:
        self.retried.append((job, code, next_attempt_at))

    def finish(self, job: ContentJob, *, status: str, code: str, detail: str) -> None:
        self.finished.append((job, status, code))


class FakeProvider:
    def __init__(
        self,
        result: AcquiredContent | None = None,
        error: ContentAcquisitionError | None = None,
    ) -> None:
        self.result = result
        self.error = error

    def acquire(self, request: ContentRequest) -> AcquiredContent:
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _worker(store: FakeStore, provider: FakeProvider) -> LiveNewsContentWorker:
    return LiveNewsContentWorker(
        store,
        ProviderRegistry({"html": provider}),
        worker_id="worker-1",
        batch_size=10,
        clock=lambda: NOW,
        jitter=lambda: 0.0,
    )


def test_worker_recovers_stale_claims_before_claiming() -> None:
    store = FakeStore()

    result = _worker(store, FakeProvider()).run_once()

    assert store.calls == ["recover", "claim"]
    assert result.claimed_count == 0


def test_worker_completes_successful_job() -> None:
    acquired = AcquiredContent("html", BODY, NOW, "trafilatura-2.1")
    store = FakeStore([JOB])

    result = _worker(store, FakeProvider(result=acquired)).run_once()

    assert store.completed == [(JOB, acquired)]
    assert result.completed_count == 1
    assert result.failed_count == 0


def test_worker_retries_transient_failure_with_backoff() -> None:
    store = FakeStore([JOB])
    error = ContentAcquisitionError("network_error", "timeout", retryable=True)

    result = _worker(store, FakeProvider(error=error)).run_once()

    assert store.retried[0][0] == JOB
    assert store.retried[0][1] == "network_error"
    assert store.retried[0][2] == NOW + timedelta(seconds=30)
    assert result.retried_count == 1


def test_worker_blocks_permanent_paywall_failure() -> None:
    store = FakeStore([JOB])
    error = ContentAcquisitionError("paywall_or_login", "login required", retryable=False)

    result = _worker(store, FakeProvider(error=error)).run_once()

    assert store.finished == [(JOB, "blocked", "paywall_or_login")]
    assert result.failed_count == 1


def test_worker_blocks_disabled_local_research_job() -> None:
    store = FakeStore([JOB])
    error = ContentAcquisitionError(
        "local_research_disabled",
        "local research mode is disabled",
        retryable=False,
    )

    result = _worker(store, FakeProvider(error=error)).run_once()

    assert store.finished == [(JOB, "blocked", "local_research_disabled")]
    assert result.failed_count == 1


def test_worker_stops_retrying_after_five_claimed_attempts() -> None:
    final_job = ContentJob(REQUEST.article_id, REQUEST, "full_text", 5)
    store = FakeStore([final_job])
    error = ContentAcquisitionError("http_500", "server error", retryable=True)

    _worker(store, FakeProvider(error=error)).run_once()

    assert store.retried == []
    assert store.finished == [(final_job, "failed", "http_500")]


def test_stopped_worker_does_not_claim_jobs() -> None:
    store = FakeStore([JOB])
    worker = _worker(store, FakeProvider())
    worker.stop()

    result = worker.run_once()

    assert result.claimed_count == 0
    assert store.calls == []
