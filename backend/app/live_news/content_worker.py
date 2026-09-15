from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from backend.app.live_news.content_providers import ContentProvider
from backend.app.live_news.content_types import (
    AcquiredContent,
    ContentAcquisitionError,
    ContentJob,
)

BLOCKED_FAILURE_CODES = frozenset(
    {
        "blocked_by_policy",
        "authentication_required",
        "local_research_disabled",
        "paywall_or_login",
        "publisher_blocked",
    }
)


class LiveContentStore(Protocol):
    def recover_stale(self, stale_before: datetime) -> int: ...

    def claim_due(self, worker_id: str, limit: int, now: datetime) -> list[ContentJob]: ...

    def complete(self, job: ContentJob, acquired: AcquiredContent) -> None: ...

    def retry(
        self,
        job: ContentJob,
        *,
        code: str,
        detail: str,
        next_attempt_at: datetime,
    ) -> None: ...

    def finish(
        self,
        job: ContentJob,
        *,
        status: str,
        code: str,
        detail: str,
    ) -> None: ...


class ProviderRegistry:
    def __init__(self, providers: Mapping[str, ContentProvider]) -> None:
        self._providers = dict(providers)

    def for_mode(self, mode: str) -> ContentProvider:
        provider = self._providers.get(mode)
        if provider is None:
            raise ContentAcquisitionError(
                "provider_unavailable",
                f"content provider {mode!r} is not configured",
                retryable=True,
            )
        return provider


@dataclass(frozen=True)
class WorkerBatchResult:
    claimed_count: int = 0
    completed_count: int = 0
    retried_count: int = 0
    failed_count: int = 0


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LiveNewsContentWorker:
    def __init__(
        self,
        store: LiveContentStore,
        providers: ProviderRegistry,
        *,
        worker_id: str,
        batch_size: int,
        clock: Callable[[], datetime] = _utc_now,
        jitter: Callable[[], float] = random.random,
        stale_claim_after: timedelta = timedelta(minutes=10),
        max_attempts: int = 5,
    ) -> None:
        self._store = store
        self._providers = providers
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._clock = clock
        self._jitter = jitter
        self._stale_claim_after = stale_claim_after
        self._max_attempts = max_attempts
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def run_once(self) -> WorkerBatchResult:
        if self._stopped:
            return WorkerBatchResult()
        now = self._clock()
        self._store.recover_stale(now - self._stale_claim_after)
        jobs = self._store.claim_due(self._worker_id, self._batch_size, now)
        completed = 0
        retried = 0
        failed = 0
        for job in jobs:
            if self._stopped:
                break
            try:
                provider = self._providers.for_mode(job.request.policy.mode)
                acquired = provider.acquire(job.request)
                self._store.complete(job, acquired)
                completed += 1
            except ContentAcquisitionError as exc:
                if exc.retryable and job.attempt_count < self._max_attempts:
                    self._store.retry(
                        job,
                        code=exc.code,
                        detail=exc.detail,
                        next_attempt_at=self._next_attempt(job, exc, now),
                    )
                    retried += 1
                else:
                    status = "blocked" if exc.code in BLOCKED_FAILURE_CODES else "failed"
                    self._store.finish(
                        job,
                        status=status,
                        code=exc.code,
                        detail=exc.detail,
                    )
                    failed += 1
        return WorkerBatchResult(
            claimed_count=len(jobs),
            completed_count=completed,
            retried_count=retried,
            failed_count=failed,
        )

    def _next_attempt(
        self,
        job: ContentJob,
        error: ContentAcquisitionError,
        now: datetime,
    ) -> datetime:
        if error.retry_after and error.retry_after.isdigit():
            seconds = min(3600, max(1, int(error.retry_after)))
        else:
            seconds = min(1800, 30 * (2 ** max(0, job.attempt_count - 1)))
        seconds += round(seconds * 0.2 * min(1.0, max(0.0, self._jitter())))
        return now + timedelta(seconds=seconds)
