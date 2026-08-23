from __future__ import annotations

from threading import Event

from backend.app.live_news.content_worker import WorkerBatchResult
from scripts.run_live_news_content_worker import run_loop


class FakeWorker:
    def __init__(self) -> None:
        self.calls = 0

    def run_once(self) -> WorkerBatchResult:
        self.calls += 1
        return WorkerBatchResult(claimed_count=1, completed_count=1)


def test_long_running_content_worker_stops_before_starting_another_cycle() -> None:
    stop_event = Event()
    worker = FakeWorker()
    emitted: list[dict[str, object]] = []

    def stop_instead_of_sleeping(_seconds: float) -> None:
        stop_event.set()

    result = run_loop(
        worker,
        once=False,
        interval=5,
        stop_event=stop_event,
        sleep=stop_instead_of_sleeping,
        emit=emitted.append,
    )

    assert result == 0
    assert worker.calls == 1
    assert emitted == [
        {
            "claimed_count": 1,
            "completed_count": 1,
            "retried_count": 0,
            "failed_count": 0,
        }
    ]
