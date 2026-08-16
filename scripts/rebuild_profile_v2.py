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
from backend.app.profiles.signals import topic_strengths_for_event  # noqa: E402
from backend.app.repositories._utils import parse_json  # noqa: E402
from backend.app.repositories.connection import (  # noqa: E402
    connect,
    parse_database_url,
    transaction,
)
from backend.app.repositories.content_dao import (  # noqa: E402
    load_answer_topic_ids,
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
class RebuildSummary:
    target_user_count: int
    selected_event_count: int
    replayed_event_count: int
    failed_user_ids: list[int]
    dry_run: bool


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
        "--dry-run",
        action="store_true",
        help="Count selected users and events without changing projections.",
    )
    return parser


def load_target_user_ids(
    connection: Any,
    user_id: int | None,
    all_users: bool,
) -> list[int]:
    with connection.cursor() as cursor:
        if all_users:
            cursor.execute("SELECT user_id FROM user_profile ORDER BY user_id")
        else:
            cursor.execute(
                "SELECT user_id FROM user_profile WHERE user_id = %s",
                (user_id,),
            )
        return [int(row["user_id"]) for row in cursor.fetchall()]


def load_reset_cutoff(
    connection: Any,
    user_id: int,
    *,
    for_update: bool = False,
) -> ResetBoundary | None:
    lock_clause = " FOR UPDATE" if for_update else ""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT profile_reset_before_ts, profile_reset_before_event_id
            FROM user_profile
            WHERE user_id = %s
            """
            + lock_clause,
            (user_id,),
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
              news_id,
              query_key,
              surface,
              dwell_ms,
              topic_ids_json,
              event_ts
            FROM user_event
            WHERE user_id = %s
              AND event_type = ANY(%s)
              AND (%s IS NULL OR event_ts >= %s)
              AND (%s IS NULL OR event_id > %s)
            ORDER BY user_id ASC, event_ts ASC, event_id ASC
            """,
            (
                user_id,
                list(_PROFILE_EVENT_TYPES),
                reset_ts,
                reset_ts,
                reset_event_id,
                reset_event_id,
            ),
        )
        return [dict(row) for row in cursor.fetchall()]


def clear_profile_v2_projection(connection: Any, user_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM user_topic_profile WHERE user_id = %s", (user_id,))
        cursor.execute(
            """
            UPDATE user_profile
            SET
              profile_v2_evidence_count = 0,
              profile_v2_last_event_ts = NULL,
              profile_v2_updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s
            """,
            (user_id,),
        )


def _article_id(row: dict[str, Any]) -> int | None:
    raw_value = row.get("article_id", row.get("answer_id", row.get("news_id")))
    if raw_value is None:
        return None
    text_value = str(raw_value)
    if text_value.startswith("N"):
        text_value = text_value[1:]
    return int(text_value) if text_value.isdigit() else None


def _stored_topic_ids(row: dict[str, Any]) -> list[int]:
    values = parse_json(row.get("topic_ids_json"), [])
    if not isinstance(values, list):
        return []
    return [int(value) for value in values]


def _event_message(row: dict[str, Any]) -> UserEventMessage:
    database_event_id = int(row["event_id"])
    return UserEventMessage(
        event_id=str(row.get("external_event_id") or f"db-event-{database_event_id}"),
        event_type=cast(UserEventType, str(row["event_type"])),
        user_id=int(row["user_id"]),
        article_id=_article_id(row),
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
    article_topic_ids = (
        [] if event.event_type == "search_result_click" else _stored_topic_ids(row)
    )
    if event.article_id is not None and not article_topic_ids:
        article_topic_ids = load_answer_topic_ids(connection, event.article_id)
    query_topic_ids = (
        [item.topic_id for item in load_query_topics(connection, event.query_key)]
        if event.event_type == "search_result_click" and event.query_key
        else []
    )
    strengths = topic_strengths_for_event(
        event.event_type,
        article_topic_ids=article_topic_ids,
        query_topic_ids=query_topic_ids,
        dwell_ms=event.dwell_ms,
    )
    return bool(
        apply_profile_v2_event(
            connection,
            user_id=event.user_id,
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
    all_users: bool,
    dry_run: bool,
) -> RebuildSummary:
    if (user_id is not None) == all_users:
        raise ValueError("exactly one of user_id or all_users is required")
    target_user_ids = load_target_user_ids(connection, user_id, all_users)
    if not dry_run:
        # psycopg starts a transaction for the discovery SELECT. Close it before
        # opening one isolated transaction per user.
        connection.commit()
    selected_event_count = 0
    replayed_event_count = 0
    failed_user_ids: list[int] = []

    for target_user_id in target_user_ids:
        if dry_run:
            reset_cutoff = load_reset_cutoff(
                connection,
                target_user_id,
                for_update=False,
            )
            events = load_rebuild_events(connection, target_user_id, reset_cutoff)
            selected_event_count += len(events)
            continue

        try:
            with transaction(connection):
                reset_cutoff = load_reset_cutoff(
                    connection,
                    target_user_id,
                    for_update=True,
                )
                events = load_rebuild_events(connection, target_user_id, reset_cutoff)
                events.sort(key=lambda row: (int(row["event_ts"]), int(row["event_id"])))
                selected_event_count += len(events)
                clear_profile_v2_projection(connection, target_user_id)
                replayed_event_count += sum(
                    1 for row in events if replay_event(connection, row, settings=settings)
                )
        except Exception:
            failed_user_ids.append(target_user_id)

    return RebuildSummary(
        target_user_count=len(target_user_ids),
        selected_event_count=selected_event_count,
        replayed_event_count=replayed_event_count,
        failed_user_ids=failed_user_ids,
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
        summary = rebuild_profiles(
            connection,
            settings=settings,
            user_id=args.user_id,
            all_users=args.all_users,
            dry_run=args.dry_run,
        )
    finally:
        connection.close()
    print(json.dumps(asdict(summary), ensure_ascii=False, sort_keys=True))
    return 1 if summary.failed_user_ids else 0


if __name__ == "__main__":
    raise SystemExit(main())
