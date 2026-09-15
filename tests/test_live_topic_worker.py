from contextlib import nullcontext
from types import SimpleNamespace

from scripts import run_live_topic_worker as worker


def test_worker_reconnects_after_database_disconnect(monkeypatch):
    class Connection:
        closed = False

        def transaction(self):
            return nullcontext()

        def cursor(self):
            return nullcontext(self)

        def execute(self, *args):
            pass

        def fetchall(self):
            return []

        def close(self):
            self.closed = True

    connections = [Connection(), Connection()]
    waiting = SimpleNamespace(stopped=False)
    waiting.is_set = lambda: waiting.stopped
    waiting.set = lambda: setattr(waiting, "stopped", True)
    waiting.wait = lambda seconds: None
    calls = []

    def run_batch(connection, *args):
        calls.append(connection)
        if len(calls) == 1:
            raise OSError("database disconnected")
        waiting.set()
        return {"claimed": 0}

    monkeypatch.setattr(worker.sys, "argv", ["worker"])
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(database_url="unused"))
    monkeypatch.setattr(worker, "parse_database_url", lambda value: value)
    monkeypatch.setattr(worker, "connect", lambda value: connections[len(calls)])
    monkeypatch.setattr(worker, "TopicClassifier", lambda **kwargs: SimpleNamespace(version="v1"))
    monkeypatch.setattr(worker, "seed_topics", lambda connection: None)
    monkeypatch.setattr(worker, "Event", lambda: waiting)
    monkeypatch.setattr(worker.signal, "signal", lambda *args: None)
    monkeypatch.setattr(worker, "run_batch", run_batch)
    worker.main()
    assert calls == connections
    assert all(connection.closed for connection in connections)
