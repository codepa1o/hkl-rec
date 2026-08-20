from __future__ import annotations

from threading import Event
from urllib.error import URLError

import pytest

from backend.app.live_news.types import LiveImportResult
from scripts.run_live_news_collector import run_loop


class FlakyCollector:
    def __init__(self, stop_event: Event) -> None:
        self.calls = 0
        self.stop_event = stop_event

    def run_once(self):
        self.calls += 1
        if self.calls == 1:
            raise URLError("transient TLS failure")
        self.stop_event.set()
        return [LiveImportResult("batch", 2, 1)]


def test_long_running_collector_recovers_after_transient_cycle_failure() -> None:
    stop_event = Event()
    collector = FlakyCollector(stop_event)
    emitted: list[dict[str, object]] = []
    sleeps: list[float] = []

    result = run_loop(
        collector,
        once=False,
        interval=5,
        stop_event=stop_event,
        sleep=sleeps.append,
        emit=emitted.append,
    )

    assert result == 0
    assert collector.calls == 2
    assert emitted[0]["status"] == "error"
    assert emitted[0]["error_type"] == "URLError"
    assert emitted[1] == {"status": "ok", "batches": 1, "accepted": 2, "rejected": 1}
    assert sleeps == [5]


def test_one_shot_collector_propagates_failure() -> None:
    stop_event = Event()
    collector = FlakyCollector(stop_event)

    with pytest.raises(URLError):
        run_loop(
            collector,
            once=True,
            interval=5,
            stop_event=stop_event,
            sleep=lambda _seconds: None,
            emit=lambda _payload: None,
        )
