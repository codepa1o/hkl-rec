from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.news_spaces.types import NewsSpace  # noqa: E402
from backend.app.repositories.connection import connect, parse_database_url  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset one PostgreSQL demo profile.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("NEWSREC_DATABASE_URL", ""),
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=int(os.environ.get("NEWSREC_DEFAULT_DEMO_USER_ID", "7001")),
    )
    parser.add_argument(
        "--user-count",
        type=int,
        default=1,
        help="Reset this many consecutive research users, starting at --user-id.",
    )
    parser.add_argument(
        "--source-space",
        choices=("mind", "live"),
        default="mind",
        help="Profile and event space to reset (default: mind).",
    )
    return parser.parse_args()


def reset_demo_user(
    connection: object,
    user_id: int,
    source_space: NewsSpace = "mind",
) -> None:
    with connection.transaction(), connection.cursor() as cursor:  # type: ignore[attr-defined]
        if source_space == "mind":
            cursor.execute(
                """
                INSERT INTO system_profile_seed (
                    seed_key, source_space, topic_weights_json, recent_clicked_news_json,
                    recent_queries_json, behavior_score, notes
                )
                SELECT
                    'cold_start_default', 'mind',
                    COALESCE(
                        jsonb_agg(
                            jsonb_build_object('topic_id', topic_id, 'weight', 0.166667)
                            ORDER BY news_count DESC, topic_id
                        ),
                        '[]'::jsonb
                    ),
                    '[]'::jsonb, '[]'::jsonb, 0, %s
                FROM (
                    SELECT topic_id, news_count
                    FROM topic
                    WHERE source_space = 'mind' AND source = 'mind_small'
                    ORDER BY news_count DESC, topic_id
                    LIMIT 6
                ) AS top_topics
                ON CONFLICT (seed_key) DO UPDATE SET
                    source_space = 'mind',
                    topic_weights_json = EXCLUDED.topic_weights_json,
                    notes = EXCLUDED.notes
                """,
                ("Canonical MIND cold-start seed",),
            )
        seed_key = "cold_start_default" if source_space == "mind" else "live_cold_start_default"
        cursor.execute(
            """
            INSERT INTO app_user (user_id, display_name, is_demo_user, source)
            VALUES (%s, %s, TRUE, %s)
            ON CONFLICT (user_id) DO UPDATE SET is_demo_user = TRUE
            """,
            (
                user_id,
                f"{'MIND' if source_space == 'mind' else 'Live'} Reader {user_id}",
                "mind_small" if source_space == "mind" else "live",
            ),
        )
        cursor.execute(
            "DELETE FROM user_event WHERE user_id = %s AND source_space = %s",
            (user_id, source_space),
        )
        cursor.execute(
            "DELETE FROM feed_request WHERE user_id = %s AND source_space = %s",
            (user_id, source_space),
        )
        cursor.execute(
            "DELETE FROM event_idempotency WHERE user_id = %s AND source_space = %s",
            (user_id, source_space),
        )
        cursor.execute(
            "DELETE FROM user_topic_profile WHERE user_id = %s AND source_space = %s",
            (user_id, source_space),
        )
        if source_space == "mind":
            cursor.execute("DELETE FROM sponsored_delivery WHERE user_id = %s", (user_id,))
            cursor.execute(
                "DELETE FROM sponsored_user_daily_frequency WHERE user_id = %s",
                (user_id,),
            )
        cursor.execute(
            """
            INSERT INTO user_profile (
                user_id, source_space, cold_start_seed_key, topic_weights_json,
                recent_clicked_news_json, recent_queries_json, behavior_score,
                user_vector_json, notes, last_event_ts
            )
            SELECT
                %s, %s, seed_key, topic_weights_json,
                COALESCE(recent_clicked_news_json, '[]'::jsonb),
                COALESCE(recent_queries_json, '[]'::jsonb),
                behavior_score, NULL, %s, NULL
            FROM system_profile_seed
            WHERE seed_key = %s AND source_space = %s
            ON CONFLICT (user_id, source_space) DO UPDATE SET
                cold_start_seed_key = EXCLUDED.cold_start_seed_key,
                topic_weights_json = EXCLUDED.topic_weights_json,
                recent_clicked_news_json = EXCLUDED.recent_clicked_news_json,
                recent_queries_json = EXCLUDED.recent_queries_json,
                behavior_score = EXCLUDED.behavior_score,
                user_vector_json = NULL,
                notes = EXCLUDED.notes,
                last_event_ts = NULL,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                source_space,
                "Reset by scripts/reset_demo_user.py",
                seed_key,
                source_space,
            ),
        )


def main() -> int:
    args = _parse_args()
    if not args.database_url:
        print("error: NEWSREC_DATABASE_URL or --database-url is required", file=sys.stderr)
        return 2
    if args.user_count < 1 or args.user_count > 100:
        print("error: --user-count must be between 1 and 100", file=sys.stderr)
        return 2
    connection = connect(parse_database_url(args.database_url))
    try:
        user_ids = list(range(args.user_id, args.user_id + args.user_count))
        for user_id in user_ids:
            reset_demo_user(connection, user_id, args.source_space)
    finally:
        connection.close()
    print(
        json.dumps(
            {"user_ids": user_ids, "source_space": args.source_space, "status": "reset"},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
