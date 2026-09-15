from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings, get_settings  # noqa: E402
from backend.app.events.schema import UserEventMessage, UserEventType  # noqa: E402
from backend.app.live_news.topic_dao import load_live_topic_ids  # noqa: E402
from backend.app.news_spaces.types import NewsSpace  # noqa: E402
from backend.app.profiles.signals import topic_strengths_for_event  # noqa: E402
from backend.app.repositories._utils import parse_json  # noqa: E402
from backend.app.repositories.connection import (  # noqa: E402
    connect,
    parse_database_url,
    transaction,
)
from backend.app.repositories.content_dao import (  # noqa: E402
    load_news_topic_ids,
    load_query_topics,
)
from backend.app.repositories.profile_v2_dao import (  # noqa: E402
    apply_profile_v2_event,
    profile_signal_config,
)

_PROFILE_EVENT_TYPES = (
    "recommendation_click",
    "search_result_click",
    "upvote",
    "downvote",
    "dwell",
)


@dataclass(frozen=True, slots=True)
class ProfileTarget:
    user_id: int
    source_space: NewsSpace


@dataclass(frozen=True, slots=True)
class FailedTarget:
    user_id: int
    source_space: NewsSpace
    error_type: str
    error_message: str


class RebuildTargetNotFoundError(LookupError):
    def __init__(self, user_id: int, source_space: NewsSpace) -> None:
        self.user_id = user_id
        self.source_space = source_space
        super().__init__(
            f"profile target not found: user_id={user_id}, source_space={source_space!r}"
        )


@dataclass(frozen=True, slots=True)
class RebuildSummary:
    target_profiles: list[ProfileTarget]
    selected_event_count: int
    replayed_event_count: int
    failed_targets: list[FailedTarget]
    dry_run: bool

    @property
    def target_user_count(self) -> int:
        return len({target.user_id for target in self.target_profiles})

    @property
    def target_profile_count(self) -> int:
        return len(self.target_profiles)

    @property
    def failed_user_ids(self) -> list[int]:
        return sorted({target.user_id for target in self.failed_targets})


def rebuild_summary_payload(summary: RebuildSummary) -> dict[str, Any]:
    return {
        "report_schema_version": 2,
        "source_aware": True,
        "target_profiles": [asdict(target) for target in summary.target_profiles],
        "failed_targets": [asdict(target) for target in summary.failed_targets],
        "target_user_count": summary.target_user_count,
        "target_profile_count": summary.target_profile_count,
        "failed_user_ids": summary.failed_user_ids,
        "selected_event_count": summary.selected_event_count,
        "replayed_event_count": summary.replayed_event_count,
        "dry_run": summary.dry_run,
    }


@dataclass(frozen=True, slots=True)
class ResetBoundary:
    event_ts: int
    event_id: int | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministically rebuild Profile V2 projections from user_event facts."
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user-id", type=int, help="Rebuild one user profile.")
    scope.add_argument(
        "--all",
        dest="all_users",
        action="store_true",
        help="Rebuild every initialized user profile.",
    )
    parser.add_argument(
        "--source-space",
        choices=("mind", "live"),
        default="mind",
        help="News space for --user-id (default: mind). Ignored with --all.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count selected users and events without changing projections.",
    )
    return parser


def load_target_profiles(
    connection: Any,
    user_id: int | None,
    source_space: NewsSpace,
    all_users: bool,
) -> list[ProfileTarget]:
    with connection.cursor() as cursor:
        if all_users:
            cursor.execute(
                "SELECT user_id, source_space FROM user_profile ORDER BY user_id, source_space"
            )
        else:
            cursor.execute(
                "SELECT user_id, source_space FROM user_profile "
                "WHERE user_id = %s AND source_space = %s "
                "ORDER BY user_id, source_space",
                (user_id, source_space),
            )
        return [
            ProfileTarget(
                user_id=int(row["user_id"]),
                source_space=cast(NewsSpace, str(row["source_space"])),
            )
            for row in cursor.fetchall()
        ]


def load_reset_cutoff(
    connection: Any,
    user_id: int,
    source_space: NewsSpace,
    *,
    for_update: bool = False,
) -> ResetBoundary | None:
    lock_clause = " FOR UPDATE" if for_update else ""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT profile_reset_before_ts, profile_reset_before_event_id
            FROM user_profile
            WHERE user_id = %s AND source_space = %s
            """
            + lock_clause,
            (user_id, source_space),
        )
        row = cursor.fetchone()
    if row is None or row.get("profile_reset_before_ts") is None:
        return None
    reset_event_id = row.get("profile_reset_before_event_id")
    return ResetBoundary(
        event_ts=int(row["profile_reset_before_ts"]),
        event_id=(int(reset_event_id) if reset_event_id is not None else None),
    )


def load_rebuild_events(
    connection: Any,
    user_id: int,
    source_space: NewsSpace,
    reset_cutoff: ResetBoundary | None,
) -> list[dict[str, Any]]:
    reset_ts = reset_cutoff.event_ts if reset_cutoff is not None else None
    reset_event_id = reset_cutoff.event_id if reset_cutoff is not None else None
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              event_id,
              external_event_id,
              user_id,
              event_type,
              source_space,
              article_id,
              query_key,
              surface,
              dwell_ms,
              topic_ids_json,
              event_ts
            FROM user_event
            WHERE user_id = %s
              AND source_space = %s
              AND event_type = ANY(%s)
              AND (%s::BIGINT IS NULL OR event_ts >= %s)
              AND (%s::BIGINT IS NULL OR event_id > %s)
            ORDER BY user_id ASC, event_ts ASC, event_id ASC
            """,
            (
                user_id,
                source_space,
                list(_PROFILE_EVENT_TYPES),
                reset_ts,
                reset_ts,
                reset_event_id,
                reset_event_id,
            ),
        )
        return [dict(row) for row in cursor.fetchall()]


def clear_profile_v2_projection(
    connection: Any,
    user_id: int,
    source_space: NewsSpace,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM user_topic_profile WHERE user_id = %s AND source_space = %s",
            (user_id, source_space),
        )
        cursor.execute(
            """
            UPDATE user_profile
            SET
              profile_v2_evidence_count = 0,
              profile_v2_last_event_ts = NULL,
              profile_v2_updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s AND source_space = %s
            """,
            (user_id, source_space),
        )


def _news_id(row: dict[str, Any]) -> str | None:
    raw_value = row.get("article_id") or row.get("answer_id")
    if raw_value is None:
        return None
    text_value = str(raw_value)
    if text_value.startswith("L"):
        return text_value
    if text_value.startswith("N") and text_value[1:].isdigit():
        return text_value
    return f"N{text_value}" if text_value.isdigit() else None


def _stored_topic_ids(row: dict[str, Any]) -> list[int]:
    values = parse_json(row.get("topic_ids_json"), [])
    if not isinstance(values, list):
        return []
    return [int(value) for value in values]


def _event_message(row: dict[str, Any]) -> UserEventMessage:
    database_event_id = int(row["event_id"])
    source_space = cast(NewsSpace, str(row.get("source_space") or "mind"))
    article_id = _news_id(row)
    return UserEventMessage(
        event_id=str(row.get("external_event_id") or f"db-event-{database_event_id}"),
        event_type=cast(UserEventType, str(row["event_type"])),
        user_id=int(row["user_id"]),
        source_space=source_space,
        article_id=article_id,
        news_id=article_id if source_space == "mind" else None,
        query_key=(str(row["query_key"]) if row.get("query_key") is not None else None),
        surface=str(row.get("surface") or "feed"),
        dwell_ms=(int(row["dwell_ms"]) if row.get("dwell_ms") is not None else None),
        event_ts=int(row["event_ts"]),
        source="profile-v2-rebuild",
    )


def replay_event(
    connection: Any,
    row: dict[str, Any],
    *,
    settings: Settings,
) -> bool:
    event = _event_message(row)
    news_topic_ids = [] if event.event_type == "search_result_click" else _stored_topic_ids(row)
    if event.source_space == "mind" and event.article_id is not None and not news_topic_ids:
        news_topic_ids = load_news_topic_ids(connection, event.article_id)
    elif event.source_space == "live" and event.article_id is not None:
        # Live metadata can change; immutable event snapshots are audit facts,
        # not the current catalog classification used to rebuild projections.
        news_topic_ids = load_live_topic_ids(connection, event.article_id)
    query_topic_ids = (
        [item.topic_id for item in load_query_topics(connection, event.query_key)]
        if event.source_space == "mind"
        and event.event_type == "search_result_click"
        and event.query_key
        else []
    )
    strengths = topic_strengths_for_event(
        event.event_type,
        article_topic_ids=news_topic_ids,
        query_topic_ids=query_topic_ids,
        dwell_ms=event.dwell_ms,
    )
    return bool(
        apply_profile_v2_event(
            connection,
            user_id=event.user_id,
            source_space=event.source_space,
            event_type=event.event_type,
            event_ts=event.event_ts,
            topic_strengths=strengths,
            config=profile_signal_config(settings),
        )
    )


def rebuild_profiles(
    connection: Any,
    *,
    settings: Settings,
    user_id: int | None,
    source_space: NewsSpace = "mind",
    all_users: bool,
    dry_run: bool,
) -> RebuildSummary:
    if (user_id is not None) == all_users:
        raise ValueError("exactly one of user_id or all_users is required")
    target_profiles = load_target_profiles(connection, user_id, source_space, all_users)
    if user_id is not None and not target_profiles:
        raise RebuildTargetNotFoundError(user_id, source_space)
    if not dry_run:
        # psycopg starts a transaction for the discovery SELECT. Close it before
        # opening one isolated transaction per user.
        connection.commit()
    selected_event_count = 0
    replayed_event_count = 0
    failed_targets: list[FailedTarget] = []

    for target in target_profiles:
        if dry_run:
            reset_cutoff = load_reset_cutoff(
                connection,
                target.user_id,
                target.source_space,
                for_update=False,
            )
            events = load_rebuild_events(
                connection,
                target.user_id,
                target.source_space,
                reset_cutoff,
            )
            selected_event_count += len(events)
            continue

        try:
            with transaction(connection):
                reset_cutoff = load_reset_cutoff(
                    connection,
                    target.user_id,
                    target.source_space,
                    for_update=True,
                )
                events = load_rebuild_events(
                    connection,
                    target.user_id,
                    target.source_space,
                    reset_cutoff,
                )
                events.sort(key=lambda row: (int(row["event_ts"]), int(row["event_id"])))
                selected_event_count += len(events)
                clear_profile_v2_projection(
                    connection,
                    target.user_id,
                    target.source_space,
                )
                replayed_event_count += sum(
                    1 for row in events if replay_event(connection, row, settings=settings)
                )
        except Exception as exc:
            failed_targets.append(
                FailedTarget(
                    user_id=target.user_id,
                    source_space=target.source_space,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            )

    return RebuildSummary(
        target_profiles=target_profiles,
        selected_event_count=selected_event_count,
        replayed_event_count=replayed_event_count,
        failed_targets=failed_targets,
        dry_run=dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    if not settings.database_url.strip():
        raise SystemExit("NEWSREC_DATABASE_URL is required")
    connection = connect(
        parse_database_url(settings.database_url),
        connect_timeout=settings.postgres_connect_timeout_seconds,
    )
    try:
        try:
            summary = rebuild_profiles(
                connection,
                settings=settings,
                user_id=args.user_id,
                source_space=cast(NewsSpace, args.source_space),
                all_users=args.all_users,
                dry_run=args.dry_run,
            )
        except RebuildTargetNotFoundError as exc:
            print(
                json.dumps(
                    {
                        "report_schema_version": 2,
                        "source_aware": True,
                        "error": {
                            "code": "profile_target_not_found",
                            "message": str(exc),
                        },
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 2
    finally:
        connection.close()
    print(json.dumps(rebuild_summary_payload(summary), ensure_ascii=False, sort_keys=True))
    return 1 if summary.failed_targets else 0


if __name__ == "__main__":
    raise SystemExit(main())
