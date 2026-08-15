from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.repositories.connection import connect, parse_database_url  # noqa: E402


def environment_value(name: str, legacy_name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ[name]
    if legacy_name in os.environ:
        print(f"deprecated environment variable {legacy_name}; use {name}", file=sys.stderr)
        return os.environ[legacy_name]
    return default


def parse_args() -> argparse.Namespace:
    seed_dir = environment_value(
        "NEWSREC_DEMO_SEED_DIR",
        "ZHIHUREC_DEMO_SEED_DIR",
        "build/mind_demo_world",
    )
    parser = argparse.ArgumentParser(
        description=(
            "Reset NewsIntentRec demo user profiles. By default all personas in the "
            "multi-persona seed are reset; pass --user-id to reset only one persona."
        )
    )
    parser.add_argument(
        "--profile-seed",
        default=f"{seed_dir}/demo_user_profile_seed.json",
        help="Legacy single-persona demo user profile seed JSON.",
    )
    parser.add_argument(
        "--persona-seeds",
        default=f"{seed_dir}/demo_persona_profile_seeds.json",
        help="Multi-persona demo user profile seed JSON (preferred when present).",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="If set, reset only the persona with this user_id. Otherwise reset every persona in the seed.",
    )
    return parser.parse_args()


def repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def max_ts(rows: list[dict], field: str) -> int | None:
    values = [int(row[field]) for row in rows if row.get(field) is not None]
    return max(values) if values else None


def load_seeds(persona_seeds_path: Path, legacy_seed_path: Path) -> list[dict]:
    if persona_seeds_path.exists():
        payload = json.loads(persona_seeds_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise SystemExit(f"{persona_seeds_path} must contain a JSON list")
        return payload
    if legacy_seed_path.exists():
        payload = json.loads(legacy_seed_path.read_text(encoding="utf-8"))
        return [payload]
    fixture_personas = ROOT / "build" / "mind_demo_fixture" / "demo_persona_profile_seeds.json"
    fixture_legacy = ROOT / "build" / "mind_demo_fixture" / "demo_user_profile_seed.json"
    if fixture_personas.exists():
        payload = json.loads(fixture_personas.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise SystemExit(f"{fixture_personas} must contain a JSON list")
        return payload
    if fixture_legacy.exists():
        return [json.loads(fixture_legacy.read_text(encoding="utf-8"))]
    raise SystemExit("no profile seed found in the full demo world or compact fixture")


def filter_seeds(seeds: Iterable[dict], user_id: int | None) -> list[dict]:
    if user_id is None:
        return list(seeds)
    filtered = [seed for seed in seeds if int(seed["user_id"]) == user_id]
    if not filtered:
        raise SystemExit(f"--user-id {user_id} not present in the loaded seed(s)")
    return filtered


def reset_one(cursor, seed: dict) -> tuple[int, int, int]:
    recent_clicks = seed.get("recent_clicked_answers", [])
    recent_queries = seed.get("recent_queries", [])
    candidate_ts = [
        max_ts(recent_clicks, "click_ts"),
        max_ts(recent_queries, "query_ts"),
        0,
    ]
    last_event_ts = max(value for value in candidate_ts if value is not None)
    cursor.execute(
        """
        INSERT INTO user_profile (
          user_id,
          cold_start_seed_key,
          topic_weights_json,
          recent_clicked_answers_json,
          recent_queries_json,
          behavior_score,
          user_vector_json,
          notes,
          last_event_ts
        )
        VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
          cold_start_seed_key = EXCLUDED.cold_start_seed_key,
          topic_weights_json = EXCLUDED.topic_weights_json,
          recent_clicked_answers_json = EXCLUDED.recent_clicked_answers_json,
          recent_queries_json = EXCLUDED.recent_queries_json,
          behavior_score = EXCLUDED.behavior_score,
          user_vector_json = EXCLUDED.user_vector_json,
          notes = EXCLUDED.notes,
          last_event_ts = EXCLUDED.last_event_ts
        """,
        (
            seed["user_id"],
            seed.get("cold_start_seed_key", "cold_start_default"),
            json_text(seed.get("topic_weights", [])),
            json_text(recent_clicks),
            json_text(recent_queries),
            seed.get("behavior_score", 0.0),
            seed.get("notes"),
            last_event_ts,
        ),
    )
    cursor.execute(
        """
        SELECT external_event_id
        FROM user_event
        WHERE user_id = %s
          AND derived_from_raw IS FALSE
          AND external_event_id IS NOT NULL
        """,
        (seed["user_id"],),
    )
    runtime_event_ids = [
        str(row["external_event_id"]) for row in cursor.fetchall() if row.get("external_event_id")
    ]
    if runtime_event_ids:
        placeholders = ",".join(["%s"] * len(runtime_event_ids))
        cursor.execute(
            f"DELETE FROM event_outbox WHERE event_id IN ({placeholders})",
            tuple(runtime_event_ids),
        )
    cursor.execute(
        "DELETE FROM user_event WHERE user_id = %s AND derived_from_raw IS FALSE",
        (seed["user_id"],),
    )
    cursor.execute(
        "DELETE FROM event_idempotency WHERE user_id = %s",
        (seed["user_id"],),
    )
    cursor.execute(
        "DELETE FROM feed_request WHERE user_id = %s",
        (seed["user_id"],),
    )
    cursor.execute(
        """
        SELECT
          campaign_id,
          budget_date,
          SUM(expected_spend_micros) AS expected_spend_micros,
          COUNT(*) AS served_impression_count,
          COUNT(*) FILTER (WHERE confirmed_impression_ts IS NOT NULL)
            AS confirmed_impression_count,
          COUNT(*) FILTER (WHERE clicked_ts IS NOT NULL) AS click_count
        FROM sponsored_delivery
        WHERE user_id = %s
        GROUP BY campaign_id, budget_date
        """,
        (seed["user_id"],),
    )
    delivery_totals = list(cursor.fetchall())
    cursor.execute("DELETE FROM sponsored_delivery WHERE user_id = %s", (seed["user_id"],))
    cursor.execute(
        "DELETE FROM sponsored_user_daily_frequency WHERE user_id = %s",
        (seed["user_id"],),
    )
    for totals in delivery_totals:
        cursor.execute(
            """
            UPDATE sponsored_campaign_daily_state
            SET
              expected_spend_micros = GREATEST(
                0,
                expected_spend_micros - %s
              ),
              served_impression_count = GREATEST(
                0,
                served_impression_count - %s
              ),
              confirmed_impression_count = GREATEST(
                0,
                confirmed_impression_count - %s
              ),
              click_count = GREATEST(0, click_count - %s)
            WHERE campaign_id = %s AND budget_date = %s
            """,
            (
                int(totals.get("expected_spend_micros") or 0),
                int(totals.get("served_impression_count") or 0),
                int(totals.get("confirmed_impression_count") or 0),
                int(totals.get("click_count") or 0),
                int(totals["campaign_id"]),
                totals["budget_date"],
            ),
        )
    return seed["user_id"], len(recent_clicks), len(recent_queries)


def main() -> None:
    args = parse_args()
    persona_seeds_path = repo_path(args.persona_seeds)
    legacy_seed_path = repo_path(args.profile_seed)

    database_url = environment_value(
        "NEWSREC_DATABASE_URL",
        "ZHIHUREC_DATABASE_URL",
    ).strip()
    if not database_url:
        raise SystemExit("NEWSREC_DATABASE_URL is required")

    config = parse_database_url(database_url)
    seeds = load_seeds(persona_seeds_path, legacy_seed_path)
    seeds = filter_seeds(seeds, args.user_id)

    connection = connect(config)
    try:
        with connection.transaction(), connection.cursor() as cursor:
            for seed in seeds:
                user_id, click_count, query_count = reset_one(cursor, seed)
                print(f"reset user_profile user_id={user_id}")
                print(f"  recent_clicked_articles={click_count}")
                print(f"  recent_queries={query_count}")
    finally:
        connection.close()

    print(f"reset complete: personas={len(seeds)}")


if __name__ == "__main__":
    main()
