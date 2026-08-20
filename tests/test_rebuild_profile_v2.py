from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.config import Settings
from scripts import rebuild_profile_v2


class TransactionConnection:
    def __init__(self) -> None:
        self.begins = 0
        self.commits = 0
        self.rollbacks = 0

    def begin(self) -> None:
        self.begins += 1

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class PsycopgStyleTransaction(AbstractContextManager[None]):
    def __init__(self, connection: PsycopgStyleConnection) -> None:
        self.connection = connection

    def __enter__(self) -> None:
        self.connection.transaction_enters += 1

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.connection.transaction_exits += 1
        return None


class PsycopgStyleConnection:
    """Models the raw psycopg API: transaction(), but no begin()."""

    def __init__(self) -> None:
        self.commits = 0
        self.transaction_enters = 0
        self.transaction_exits = 0

    def commit(self) -> None:
        self.commits += 1

    def transaction(self) -> PsycopgStyleTransaction:
        return PsycopgStyleTransaction(self)


def _event(event_id: int, *, user_id: int, event_ts: int) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "external_event_id": f"evt-{event_id}",
        "user_id": user_id,
        "event_type": "upvote",
        "article_id": "N101",
        "query_key": None,
        "surface": "feed",
        "dwell_ms": None,
        "topic_ids_json": [10],
        "event_ts": event_ts,
    }


def test_cli_requires_exactly_one_user_scope() -> None:
    parser = rebuild_profile_v2.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([])
    with pytest.raises(SystemExit):
        parser.parse_args(["--user-id", "7", "--all"])

    assert parser.parse_args(["--user-id", "7"]).user_id == 7
    assert parser.parse_args(["--user-id", "7"]).source_space == "mind"
    assert parser.parse_args(["--user-id", "7", "--source-space", "live"]).source_space == "live"
    assert parser.parse_args(["--all"]).all_users is True


def test_missing_explicit_profile_target_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rebuild_profile_v2, "load_target_profiles", lambda *args: [])

    with pytest.raises(
        rebuild_profile_v2.RebuildTargetNotFoundError,
        match=r"user_id=7.*source_space='live'",
    ):
        rebuild_profile_v2.rebuild_profiles(
            TransactionConnection(),
            settings=Settings(),
            user_id=7,
            source_space="live",
            all_users=False,
            dry_run=True,
        )


def test_rebuild_report_keeps_aggregate_and_source_aware_fields() -> None:
    targets = [
        rebuild_profile_v2.ProfileTarget(user_id=7, source_space="mind"),
        rebuild_profile_v2.ProfileTarget(user_id=7, source_space="live"),
    ]
    failures = [
        rebuild_profile_v2.FailedTarget(
            user_id=7,
            source_space="mind",
            error_type="ValueError",
            error_message="broken mind event",
        ),
        rebuild_profile_v2.FailedTarget(
            user_id=7,
            source_space="live",
            error_type="RuntimeError",
            error_message="broken live event",
        ),
    ]
    summary = rebuild_profile_v2.RebuildSummary(
        target_profiles=targets,
        selected_event_count=2,
        replayed_event_count=1,
        failed_targets=failures,
        dry_run=False,
    )

    assert rebuild_profile_v2.rebuild_summary_payload(summary) == {
        "report_schema_version": 2,
        "source_aware": True,
        "target_profiles": [
            {"user_id": 7, "source_space": "mind"},
            {"user_id": 7, "source_space": "live"},
        ],
        "failed_targets": [
            {
                "user_id": 7,
                "source_space": "mind",
                "error_type": "ValueError",
                "error_message": "broken mind event",
            },
            {
                "user_id": 7,
                "source_space": "live",
                "error_type": "RuntimeError",
                "error_message": "broken live event",
            },
        ],
        "target_user_count": 1,
        "target_profile_count": 2,
        "failed_user_ids": [7],
        "selected_event_count": 2,
        "replayed_event_count": 1,
        "dry_run": False,
    }


def test_main_returns_nonzero_json_error_for_missing_target(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(
        rebuild_profile_v2,
        "get_settings",
        lambda: Settings(database_url="postgresql://user:pass@127.0.0.1/safe_test"),
    )
    monkeypatch.setattr(rebuild_profile_v2, "connect", lambda *args, **kwargs: connection)
    monkeypatch.setattr(
        rebuild_profile_v2,
        "rebuild_profiles",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            rebuild_profile_v2.RebuildTargetNotFoundError(7, "live")
        ),
    )

    assert rebuild_profile_v2.main(["--user-id", "7", "--source-space", "live"]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "report_schema_version": 2,
        "source_aware": True,
        "error": {
            "code": "profile_target_not_found",
            "message": "profile target not found: user_id=7, source_space='live'",
        },
    }


def test_rebuild_all_scopes_same_user_profiles_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = TransactionConnection()
    targets = [
        rebuild_profile_v2.ProfileTarget(user_id=7, source_space="mind"),
        rebuild_profile_v2.ProfileTarget(user_id=7, source_space="live"),
    ]
    boundaries = {
        "mind": rebuild_profile_v2.ResetBoundary(event_ts=100, event_id=10),
        "live": rebuild_profile_v2.ResetBoundary(event_ts=200, event_id=20),
    }
    selected: list[tuple[int, str, rebuild_profile_v2.ResetBoundary | None]] = []
    cleared: list[tuple[int, str]] = []
    replayed: list[tuple[int, str, int]] = []

    monkeypatch.setattr(rebuild_profile_v2, "load_target_profiles", lambda *args: targets)

    def load_cutoff(
        connection_arg: Any,
        user_id: int,
        source_space: str,
        *,
        for_update: bool = False,
    ) -> rebuild_profile_v2.ResetBoundary:
        return boundaries[source_space]

    def load_events(
        connection_arg: Any,
        user_id: int,
        source_space: str,
        reset_cutoff: rebuild_profile_v2.ResetBoundary | None,
    ) -> list[dict[str, Any]]:
        selected.append((user_id, source_space, reset_cutoff))
        return [
            {
                **_event(11 if source_space == "mind" else 21, user_id=user_id, event_ts=300),
                "source_space": source_space,
                "article_id": "N101"
                if source_space == "mind"
                else "L550e8400e29b41d4a716446655440000",
                "news_id": "N101" if source_space == "mind" else None,
            }
        ]

    monkeypatch.setattr(rebuild_profile_v2, "load_reset_cutoff", load_cutoff)
    monkeypatch.setattr(rebuild_profile_v2, "load_rebuild_events", load_events)
    monkeypatch.setattr(
        rebuild_profile_v2,
        "clear_profile_v2_projection",
        lambda connection_arg, user_id, source_space: cleared.append((user_id, source_space)),
    )
    monkeypatch.setattr(
        rebuild_profile_v2,
        "replay_event",
        lambda connection_arg, row, *, settings: (
            replayed.append((int(row["user_id"]), str(row["source_space"]), int(row["event_id"])))
            or True
        ),
    )

    summary = rebuild_profile_v2.rebuild_profiles(
        connection,
        settings=Settings(),
        user_id=None,
        all_users=True,
        dry_run=False,
    )

    assert selected == [(7, "mind", boundaries["mind"]), (7, "live", boundaries["live"])]
    assert cleared == [(7, "mind"), (7, "live")]
    assert replayed == [(7, "mind", 11), (7, "live", 21)]
    assert summary.target_profiles == targets
    assert summary.failed_targets == []


class RecordingCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> RecordingCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class RecordingConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.cursor_value = RecordingCursor(rows)

    def cursor(self) -> RecordingCursor:
        return self.cursor_value


def test_rebuild_queries_filter_and_mutate_by_source_space() -> None:
    target_connection = RecordingConnection(
        [{"user_id": 7, "source_space": "mind"}, {"user_id": 7, "source_space": "live"}]
    )
    targets = rebuild_profile_v2.load_target_profiles(
        target_connection,
        user_id=None,
        source_space="mind",
        all_users=True,
    )
    assert targets == [
        rebuild_profile_v2.ProfileTarget(user_id=7, source_space="mind"),
        rebuild_profile_v2.ProfileTarget(user_id=7, source_space="live"),
    ]
    assert "ORDER BY user_id, source_space" in target_connection.cursor_value.executed[0][0]

    boundary_connection = RecordingConnection(
        [{"profile_reset_before_ts": 200, "profile_reset_before_event_id": 20}]
    )
    rebuild_profile_v2.load_reset_cutoff(boundary_connection, 7, "live")
    boundary_sql, boundary_params = boundary_connection.cursor_value.executed[0]
    assert "source_space = %s" in boundary_sql
    assert boundary_params == (7, "live")

    events_connection = RecordingConnection([])
    rebuild_profile_v2.load_rebuild_events(events_connection, 7, "live", None)
    events_sql, events_params = events_connection.cursor_value.executed[0]
    assert "source_space = %s" in events_sql
    assert events_params[:3] == (7, "live", list(rebuild_profile_v2._PROFILE_EVENT_TYPES))

    clear_connection = RecordingConnection([])
    rebuild_profile_v2.clear_profile_v2_projection(clear_connection, 7, "live")
    assert all(
        "source_space = %s" in sql for sql, _params in clear_connection.cursor_value.executed
    )
    assert all(params == (7, "live") for _sql, params in clear_connection.cursor_value.executed)


@pytest.mark.postgres
def test_load_rebuild_events_uses_safe_shared_postgres_fixture(postgres_connection: Any) -> None:
    user_id = 9_000_000_000 + (uuid.uuid4().int % 100_000_000)

    events = rebuild_profile_v2.load_rebuild_events(
        postgres_connection,
        user_id,
        "mind",
        None,
    )

    assert events == []


def test_dry_run_counts_filtered_events_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = TransactionConnection()
    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_target_profiles",
        lambda *args: [
            rebuild_profile_v2.ProfileTarget(7, "mind"),
            rebuild_profile_v2.ProfileTarget(8, "mind"),
        ],
    )
    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_reset_cutoff",
        lambda connection_arg, user_id, source_space, *, for_update=False: (
            rebuild_profile_v2.ResetBoundary(event_ts=100, event_id=4) if user_id == 7 else None
        ),
    )
    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_rebuild_events",
        lambda connection_arg, user_id, source_space, reset_cutoff: (
            [_event(2, user_id=user_id, event_ts=200)] if user_id == 7 else []
        ),
    )
    monkeypatch.setattr(
        rebuild_profile_v2,
        "clear_profile_v2_projection",
        lambda *args, **kwargs: pytest.fail("dry-run must not clear projections"),
    )
    monkeypatch.setattr(
        rebuild_profile_v2,
        "replay_event",
        lambda *args, **kwargs: pytest.fail("dry-run must not replay events"),
    )

    summary = rebuild_profile_v2.rebuild_profiles(
        connection,
        settings=Settings(),
        user_id=None,
        all_users=True,
        dry_run=True,
    )

    assert summary.target_user_count == 2
    assert summary.selected_event_count == 1
    assert summary.replayed_event_count == 0
    assert summary.dry_run is True
    assert connection.begins == 0
    assert connection.commits == 0
    assert connection.rollbacks == 0


def test_live_rebuild_sorts_events_and_is_repeatable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = TransactionConnection()
    source_events = [
        _event(3, user_id=7, event_ts=200),
        _event(2, user_id=7, event_ts=100),
        _event(1, user_id=7, event_ts=100),
    ]
    projection: list[int] = []
    snapshots: list[list[int]] = []

    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_target_profiles",
        lambda *args: [rebuild_profile_v2.ProfileTarget(7, "mind")],
    )
    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_reset_cutoff",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_rebuild_events",
        lambda *args: list(reversed(source_events)),
    )
    monkeypatch.setattr(
        rebuild_profile_v2,
        "clear_profile_v2_projection",
        lambda *args: projection.clear(),
    )

    def replay(connection_arg: Any, row: dict[str, Any], *, settings: Settings) -> bool:
        projection.append(int(row["event_id"]))
        return True

    monkeypatch.setattr(rebuild_profile_v2, "replay_event", replay)

    for _ in range(2):
        summary = rebuild_profile_v2.rebuild_profiles(
            connection,
            settings=Settings(),
            user_id=7,
            all_users=False,
            dry_run=False,
        )
        snapshots.append(list(projection))
        assert summary.replayed_event_count == 3

    assert snapshots == [[1, 2, 3], [1, 2, 3]]
    assert connection.begins == 2
    assert connection.commits == 4
    assert connection.rollbacks == 0


def test_live_rebuild_uses_raw_psycopg_transaction_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = PsycopgStyleConnection()
    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_target_profiles",
        lambda *args: [rebuild_profile_v2.ProfileTarget(7, "mind")],
    )
    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_reset_cutoff",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(rebuild_profile_v2, "load_rebuild_events", lambda *args: [])
    monkeypatch.setattr(rebuild_profile_v2, "clear_profile_v2_projection", lambda *args: None)

    summary = rebuild_profile_v2.rebuild_profiles(
        connection,
        settings=Settings(),
        user_id=7,
        all_users=False,
        dry_run=False,
    )

    assert summary.failed_user_ids == []
    assert connection.commits == 1
    assert connection.transaction_enters == 1
    assert connection.transaction_exits == 1


def test_live_rebuild_rolls_back_only_failed_user_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = TransactionConnection()
    replayed_users: list[int] = []
    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_target_profiles",
        lambda *args: [
            rebuild_profile_v2.ProfileTarget(7, "mind"),
            rebuild_profile_v2.ProfileTarget(8, "mind"),
        ],
    )
    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_reset_cutoff",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_rebuild_events",
        lambda connection_arg, user_id, source_space, reset_cutoff: [
            _event(user_id, user_id=user_id, event_ts=100)
        ],
    )
    monkeypatch.setattr(rebuild_profile_v2, "clear_profile_v2_projection", lambda *args: None)

    def replay(connection_arg: Any, row: dict[str, Any], *, settings: Settings) -> bool:
        user_id = int(row["user_id"])
        if user_id == 7:
            raise RuntimeError("broken user event")
        replayed_users.append(user_id)
        return True

    monkeypatch.setattr(rebuild_profile_v2, "replay_event", replay)

    summary = rebuild_profile_v2.rebuild_profiles(
        connection,
        settings=Settings(),
        user_id=None,
        all_users=True,
        dry_run=False,
    )

    assert summary.failed_user_ids == [7]
    assert summary.failed_targets == [
        rebuild_profile_v2.FailedTarget(
            user_id=7,
            source_space="mind",
            error_type="RuntimeError",
            error_message="broken user event",
        )
    ]
    assert replayed_users == [8]
    assert connection.rollbacks == 1
    assert connection.begins == 2
    assert connection.commits == 2


@pytest.mark.parametrize("dry_run, expected_for_update", [(True, False), (False, True)])
def test_reset_cutoff_is_locked_before_event_selection(
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
    expected_for_update: bool,
) -> None:
    connection = TransactionConnection()
    boundary = rebuild_profile_v2.ResetBoundary(event_ts=500, event_id=12)
    observed: list[tuple[bool, rebuild_profile_v2.ResetBoundary | None]] = []
    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_target_profiles",
        lambda *args: [rebuild_profile_v2.ProfileTarget(7, "mind")],
    )

    def load_cutoff(
        connection_arg: Any,
        user_id: int,
        source_space: str,
        *,
        for_update: bool = False,
    ) -> rebuild_profile_v2.ResetBoundary:
        observed.append((for_update, None))
        return boundary

    monkeypatch.setattr(rebuild_profile_v2, "load_reset_cutoff", load_cutoff)

    def load_events(
        connection_arg: Any,
        user_id: int,
        source_space: str,
        reset_cutoff: rebuild_profile_v2.ResetBoundary | None,
    ) -> list[dict[str, Any]]:
        observed[-1] = (observed[-1][0], reset_cutoff)
        return []

    monkeypatch.setattr(rebuild_profile_v2, "load_rebuild_events", load_events)

    rebuild_profile_v2.rebuild_profiles(
        connection,
        settings=Settings(),
        user_id=7,
        all_users=False,
        dry_run=dry_run,
    )

    assert observed == [(expected_for_update, boundary)]


def test_replay_uses_production_topic_signal_and_projection_functions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    derived: list[tuple[str, tuple[int, ...]]] = []
    projected: list[dict[str, Any]] = []

    def derive(
        event_type: str,
        *,
        article_topic_ids: list[int],
        query_topic_ids: list[int],
        dwell_ms: int | None,
    ) -> dict[int, float]:
        derived.append((event_type, tuple(article_topic_ids)))
        return {10: 2.0}

    def project(connection_arg: Any, **kwargs: Any) -> bool:
        projected.append(kwargs)
        return True

    monkeypatch.setattr(rebuild_profile_v2, "topic_strengths_for_event", derive)
    monkeypatch.setattr(rebuild_profile_v2, "apply_profile_v2_event", project)

    updated = rebuild_profile_v2.replay_event(
        object(),
        _event(1, user_id=7, event_ts=123),
        settings=Settings(),
    )

    assert updated is True
    assert derived == [("upvote", (10,))]
    assert projected[0]["user_id"] == 7
    assert projected[0]["event_ts"] == 123
    assert projected[0]["topic_strengths"] == {10: 2.0}


def test_search_click_rebuild_keeps_article_and_query_topic_attribution_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _event(1, user_id=7, event_ts=123)
    row.update(
        {
            "event_type": "search_result_click",
            "query_key": "market",
            "topic_ids_json": [10, 20],
        }
    )
    projected: list[dict[int, float]] = []
    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_news_topic_ids",
        lambda connection, news_id: [10],
    )
    monkeypatch.setattr(
        rebuild_profile_v2,
        "load_query_topics",
        lambda connection, query_key: [SimpleNamespace(topic_id=10), SimpleNamespace(topic_id=20)],
    )
    monkeypatch.setattr(
        rebuild_profile_v2,
        "apply_profile_v2_event",
        lambda connection, **kwargs: projected.append(kwargs["topic_strengths"]) or True,
    )

    assert rebuild_profile_v2.replay_event(object(), row, settings=Settings()) is True
    assert projected == [{10: 1.25, 20: 0.625}]


@pytest.mark.postgres
def test_load_rebuild_events_accepts_user_without_reset_boundary() -> None:
    from backend.app.config import get_settings
    from backend.app.repositories.connection import connect, parse_database_url

    settings = get_settings()
    if not settings.database_url:
        pytest.skip("NEWSREC_DATABASE_URL not set")
    connection = connect(parse_database_url(settings.database_url))
    try:
        events = rebuild_profile_v2.load_rebuild_events(connection, 7001, "mind", None)
    finally:
        connection.close()

    assert isinstance(events, list)
