#!/usr/bin/env python3
"""根据 MIND 演示世界导入包生成 MySQL 种子 SQL。

此脚本明确保持 V1 的运行时边界：
- build/mind_demo_world 是离线导入包
- MySQL 是唯一的运行时事实来源

它不会直接连接 MySQL，而是生成一个 SQL 文件；在 `sql/schema.sql`
创建目标表后即可应用该文件。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence, Tuple

REQUIRED_INPUTS = [
    "manifest.json",
    "topic.jsonl",
    "author.jsonl",
    "app_user.jsonl",
    "question.jsonl",
    "answer.jsonl",
    "question_topic.jsonl",
    "answer_topic.jsonl",
    "query_topic_map.jsonl",
    "hot_answer_snapshot.jsonl",
    "default_profile_seed.json",
    "demo_user_profile_seed.json",
    "demo_event_replay.jsonl",
]

# 可选输入（多画像）；缺失时导入器回退到单画像行为。
OPTIONAL_INPUTS = [
    "demo_persona_profile_seeds.json",
    "demo_personas.json",
    "sponsored_campaign.jsonl",
    "sponsored_campaign_topic.jsonl",
    "sponsored_creative.jsonl",
    "evaluation_default_profile_seed.json",
]

DELETE_ORDER = [
    "event_outbox",
    "user_event",
    "event_idempotency",
    "feed_request",
    "sponsored_delivery",
    "sponsored_user_daily_frequency",
    "sponsored_campaign_daily_state",
    "sponsored_creative",
    "sponsored_campaign_topic",
    "sponsored_campaign",
    "user_profile",
    "system_profile_seed",
    "hot_answer_snapshot",
    "query_topic_map",
    "answer_topic",
    "question_topic",
    "answer",
    "question",
    "app_user",
    "author",
    "topic",
    "worker_heartbeat",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render MySQL seed SQL from a demo-world pack.")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "build" / "mind_demo_world",
        help="Directory that contains the demo-world import pack.",
    )
    parser.add_argument(
        "--output-sql",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "build"
        / "mind_demo_world"
        / "import_demo_world.sql",
        help="Output SQL file to write.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Maximum rows per multi-value INSERT statement.",
    )
    parser.add_argument(
        "--truncate-first",
        action="store_true",
        help="Emit DELETE statements before inserts so the seed file can refresh an existing schema.",
    )
    return parser.parse_args()


def ensure_inputs(input_dir: Path) -> None:
    missing = [name for name in REQUIRED_INPUTS if not (input_dir / name).exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing required demo-world files under {input_dir}: {', '.join(missing)}"
        )


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            yield json.loads(line)


def sql_quote(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def to_json_text(value: object | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sql_literal(value: object | None) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return sql_quote(str(value))


def chunked(
    rows: Sequence[Tuple[object, ...]], batch_size: int
) -> Iterator[Sequence[Tuple[object, ...]]]:
    for start in range(0, len(rows), batch_size):
        yield rows[start : start + batch_size]


def emit_insert_blocks(
    handle,
    table: str,
    columns: Sequence[str],
    rows: Sequence[Tuple[object, ...]],
    batch_size: int,
) -> None:
    if not rows:
        return

    handle.write(f"-- {table}: {len(rows)} row(s)\n")
    prefix = f"INSERT INTO {table} ({', '.join(columns)}) VALUES\n"
    for batch in chunked(rows, batch_size):
        values_sql = []
        for row in batch:
            values_sql.append("(" + ", ".join(sql_literal(value) for value in row) + ")")
        handle.write(prefix)
        handle.write(",\n".join(values_sql))
        handle.write(";\n\n")


def max_nested_ts(items: Iterable[dict], key: str) -> int | None:
    values = [int(item[key]) for item in items if item.get(key) is not None]
    return max(values) if values else None


def max_defined(values: Iterable[int | None]) -> int | None:
    concrete = [value for value in values if value is not None]
    return max(concrete) if concrete else None


def infer_surface(event_type: str) -> str:
    if event_type in {
        "recommendation_click",
        "feed_impression",
        "detail_view",
        "dwell",
        "upvote",
        "downvote",
        "share",
    }:
        return "feed"
    return "search"


def build_topic_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    rows = []
    for row in iter_jsonl(input_dir / "topic.jsonl"):
        rows.append(
            (
                row["topic_id"],
                row.get("display_name"),
                row.get("answer_count", 0),
                row.get("question_count", 0),
                row.get("source", "mind_small"),
            )
        )
    return rows


def build_author_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    rows = []
    for row in iter_jsonl(input_dir / "author.jsonl"):
        rows.append(
            (
                row["author_id"],
                row.get("display_name"),
                row.get("is_excellent_author", 0),
                row.get("follower_count", 0),
                row.get("is_excellent_answerer", 0),
                row.get("source", "mind_small"),
            )
        )
    return rows


def build_app_user_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    rows = []
    for row in iter_jsonl(input_dir / "app_user.jsonl"):
        rows.append(
            (
                row["user_id"],
                row.get("display_name"),
                row.get("register_ts"),
                row.get("gender"),
                row.get("login_frequency"),
                row.get("follower_count", 0),
                row.get("followed_topic_count", 0),
                row.get("answer_count", 0),
                row.get("question_count", 0),
                row.get("comment_count", 0),
                row.get("thanks_received_count", 0),
                row.get("likes_received_count", 0),
                row.get("province"),
                row.get("city"),
                to_json_text(row.get("followed_topic_ids")),
                row.get("is_demo_user", False),
                row.get("source", "mind_small"),
            )
        )
    return rows


def build_question_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    rows = []
    for row in iter_jsonl(input_dir / "question.jsonl"):
        rows.append(
            (
                row["question_id"],
                row.get("create_ts"),
                row.get("answer_count", 0),
                row.get("follower_count", 0),
                row.get("invitation_count", 0),
                row.get("comment_count", 0),
                to_json_text(row.get("token_ids")),
                to_json_text(row.get("topic_ids")),
                row.get("display_title"),
                row.get("source", "mind_small"),
            )
        )
    return rows


def build_answer_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    rows = []
    for row in iter_jsonl(input_dir / "answer.jsonl"):
        rows.append(
            (
                row["answer_id"],
                row.get("question_id"),
                row.get("author_id"),
                row.get("is_anonymous", 0),
                row.get("is_high_value", 0),
                row.get("is_editor_recommended", 0),
                row.get("create_ts"),
                row.get("has_picture", 0),
                row.get("has_video", 0),
                row.get("thanks_count", 0),
                row.get("likes_count", 0),
                row.get("comment_count", 0),
                row.get("collection_count", 0),
                row.get("dislike_count", 0),
                row.get("report_count", 0),
                row.get("helpless_count", 0),
                to_json_text(row.get("token_ids")),
                to_json_text(row.get("topic_ids")),
                row.get("display_summary"),
                row.get("vector_key"),
                row.get("is_demo_selected", False),
                row.get("hot_score", 0),
                row.get("click_count", 0),
                row.get("impression_count", 0),
                row.get("source", "mind_small"),
            )
        )
    return rows


def build_question_topic_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    return [
        (row["question_id"], row["topic_id"], row.get("source_rank", 0))
        for row in iter_jsonl(input_dir / "question_topic.jsonl")
    ]


def build_answer_topic_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    return [
        (row["answer_id"], row["topic_id"], row.get("source_rank", 0))
        for row in iter_jsonl(input_dir / "answer_topic.jsonl")
    ]


def build_query_topic_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    rows = []
    for row in iter_jsonl(input_dir / "query_topic_map.jsonl"):
        rows.append(
            (
                row["query_key"],
                row.get("display_query"),
                to_json_text(row.get("query_tokens")),
                row["topic_id"],
                row.get("score", 0),
                row.get("evidence_query_count", 0),
                row.get("evidence_user_count", 0),
                row.get("match_rank", 0),
                row.get("source_method", "offline_user_topic_cooccurrence"),
            )
        )
    return rows


def build_hot_answer_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    rows = []
    for row in iter_jsonl(input_dir / "hot_answer_snapshot.jsonl"):
        rows.append(
            (
                row["snapshot_key"],
                row["rank_position"],
                row["answer_id"],
                row.get("hot_score", 0),
                row.get("click_count", 0),
                row.get("impression_count", 0),
                row.get("source_window", "selected_mind_impressions"),
            )
        )
    return rows


def build_system_profile_seed_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    paths = [input_dir / "default_profile_seed.json"]
    evaluation_path = input_dir / "evaluation_default_profile_seed.json"
    if evaluation_path.exists():
        paths.append(evaluation_path)
    rows: List[Tuple[object, ...]] = []
    for path in paths:
        row = load_json(path)
        rows.append(
            (
                row["seed_key"],
                to_json_text(row.get("topic_weights", [])),
                to_json_text(row.get("recent_clicked_answers", [])),
                to_json_text(row.get("recent_queries", [])),
                row.get("behavior_score", 0),
                row.get("notes"),
            )
        )
    return rows


def build_user_profile_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    persona_seeds_path = input_dir / "demo_persona_profile_seeds.json"
    if persona_seeds_path.exists():
        persona_rows = load_json(persona_seeds_path)
        if not isinstance(persona_rows, list):
            raise ValueError(
                f"{persona_seeds_path} must contain a JSON list of persona profile seeds"
            )
        seeds = persona_rows
    else:
        seeds = [load_json(input_dir / "demo_user_profile_seed.json")]

    rows: List[Tuple[object, ...]] = []
    for seed in seeds:
        recent_clicks = seed.get("recent_clicked_answers", [])
        recent_queries = seed.get("recent_queries", [])
        last_event_ts = max_defined(
            [
                max_nested_ts(recent_clicks, "click_ts"),
                max_nested_ts(recent_queries, "query_ts"),
            ]
        )
        rows.append(
            (
                seed["user_id"],
                seed.get("cold_start_seed_key", "cold_start_default"),
                to_json_text(seed.get("topic_weights", [])),
                to_json_text(recent_clicks),
                to_json_text(recent_queries),
                seed.get("behavior_score", 0),
                None,
                seed.get("notes"),
                last_event_ts,
            )
        )
    return rows


def build_user_event_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    rows = []
    for row in iter_jsonl(input_dir / "demo_event_replay.jsonl"):
        query_key = row.get("query_key")
        if query_key is None:
            query_key = row.get("matched_query_key")
        rows.append(
            (
                row.get("event_id"),
                row["user_id"],
                row["event_type"],
                row.get("answer_id"),
                row.get("sponsored_delivery_id"),
                row.get("campaign_id"),
                row.get("creative_id"),
                query_key,
                to_json_text(row.get("query_tokens")),
                to_json_text(row.get("topic_ids")),
                row.get("surface") or infer_surface(row["event_type"]),
                row.get("request_id"),
                row.get("dwell_ms"),
                1,
                row.get("source_confidence", "not_applicable"),
                row["event_ts"],
                None,
            )
        )
    return rows


def build_sponsored_campaign_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    path = input_dir / "sponsored_campaign.jsonl"
    if not path.exists():
        return []
    return [
        (
            row["campaign_id"],
            row["campaign_name"],
            row.get("status", "active"),
            row["start_ts"],
            row["end_ts"],
            row["daily_budget_micros"],
            row.get("pacing_mode", "even"),
            row.get("frequency_cap_per_user_per_day", 2),
        )
        for row in iter_jsonl(path)
    ]


def build_sponsored_campaign_topic_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    path = input_dir / "sponsored_campaign_topic.jsonl"
    if not path.exists():
        return []
    return [(row["campaign_id"], row["topic_id"]) for row in iter_jsonl(path)]


def build_sponsored_creative_rows(input_dir: Path) -> List[Tuple[object, ...]]:
    path = input_dir / "sponsored_creative.jsonl"
    if not path.exists():
        return []
    return [
        (
            row["creative_id"],
            row["campaign_id"],
            row["answer_id"],
            row.get("status", "active"),
            row["bid_micros"],
            row["predicted_ctr"],
            row["quality_score"],
        )
        for row in iter_jsonl(path)
    ]


def build_table_payloads(
    input_dir: Path,
) -> List[Tuple[str, Sequence[str], List[Tuple[object, ...]]]]:
    return [
        (
            "topic",
            ["topic_id", "display_name", "answer_count", "question_count", "source"],
            build_topic_rows(input_dir),
        ),
        (
            "author",
            [
                "author_id",
                "display_name",
                "is_excellent_author",
                "follower_count",
                "is_excellent_answerer",
                "source",
            ],
            build_author_rows(input_dir),
        ),
        (
            "app_user",
            [
                "user_id",
                "display_name",
                "register_ts",
                "gender",
                "login_frequency",
                "follower_count",
                "followed_topic_count",
                "answer_count",
                "question_count",
                "comment_count",
                "thanks_received_count",
                "likes_received_count",
                "province",
                "city",
                "followed_topic_ids_json",
                "is_demo_user",
                "source",
            ],
            build_app_user_rows(input_dir),
        ),
        (
            "question",
            [
                "question_id",
                "create_ts",
                "answer_count",
                "follower_count",
                "invitation_count",
                "comment_count",
                "token_ids_json",
                "topic_ids_json",
                "display_title",
                "source",
            ],
            build_question_rows(input_dir),
        ),
        (
            "answer",
            [
                "answer_id",
                "question_id",
                "author_id",
                "is_anonymous",
                "is_high_value",
                "is_editor_recommended",
                "create_ts",
                "has_picture",
                "has_video",
                "thanks_count",
                "likes_count",
                "comment_count",
                "collection_count",
                "dislike_count",
                "report_count",
                "helpless_count",
                "token_ids_json",
                "topic_ids_json",
                "display_summary",
                "vector_key",
                "is_demo_selected",
                "hot_score",
                "click_count",
                "impression_count",
                "source",
            ],
            build_answer_rows(input_dir),
        ),
        (
            "question_topic",
            ["question_id", "topic_id", "source_rank"],
            build_question_topic_rows(input_dir),
        ),
        (
            "answer_topic",
            ["answer_id", "topic_id", "source_rank"],
            build_answer_topic_rows(input_dir),
        ),
        (
            "query_topic_map",
            [
                "query_key",
                "display_query",
                "query_tokens_json",
                "topic_id",
                "score",
                "evidence_query_count",
                "evidence_user_count",
                "match_rank",
                "source_method",
            ],
            build_query_topic_rows(input_dir),
        ),
        (
            "hot_answer_snapshot",
            [
                "snapshot_key",
                "rank_position",
                "answer_id",
                "hot_score",
                "click_count",
                "impression_count",
                "source_window",
            ],
            build_hot_answer_rows(input_dir),
        ),
        (
            "system_profile_seed",
            [
                "seed_key",
                "topic_weights_json",
                "recent_clicked_answers_json",
                "recent_queries_json",
                "behavior_score",
                "notes",
            ],
            build_system_profile_seed_rows(input_dir),
        ),
        (
            "user_profile",
            [
                "user_id",
                "cold_start_seed_key",
                "topic_weights_json",
                "recent_clicked_answers_json",
                "recent_queries_json",
                "behavior_score",
                "user_vector_json",
                "notes",
                "last_event_ts",
            ],
            build_user_profile_rows(input_dir),
        ),
        (
            "sponsored_campaign",
            [
                "campaign_id",
                "campaign_name",
                "status",
                "start_ts",
                "end_ts",
                "daily_budget_micros",
                "pacing_mode",
                "frequency_cap_per_user_per_day",
            ],
            build_sponsored_campaign_rows(input_dir),
        ),
        (
            "sponsored_campaign_topic",
            ["campaign_id", "topic_id"],
            build_sponsored_campaign_topic_rows(input_dir),
        ),
        (
            "sponsored_creative",
            [
                "creative_id",
                "campaign_id",
                "answer_id",
                "status",
                "bid_micros",
                "predicted_ctr",
                "quality_score",
            ],
            build_sponsored_creative_rows(input_dir),
        ),
        (
            "user_event",
            [
                "external_event_id",
                "user_id",
                "event_type",
                "answer_id",
                "sponsored_delivery_id",
                "campaign_id",
                "creative_id",
                "query_key",
                "query_tokens_json",
                "topic_ids_json",
                "surface",
                "request_id",
                "dwell_ms",
                "derived_from_raw",
                "source_confidence",
                "event_ts",
                "debug_payload_json",
            ],
            build_user_event_rows(input_dir),
        ),
    ]


def render_sql(
    output_path: Path,
    manifest: dict,
    table_payloads: Sequence[Tuple[str, Sequence[str], List[Tuple[object, ...]]]],
    batch_size: int,
    truncate_first: bool,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()

    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("-- Generated by scripts/import_demo_world.py\n")
        handle.write(f"-- Generated at: {generated_at}\n")
        handle.write(
            f"-- Source import pack: {manifest.get('output_dir', 'build/mind_demo_world')}\n"
        )
        handle.write(f"-- Demo user ID: {manifest.get('demo_user_id')}\n\n")
        handle.write("SET NAMES utf8mb4;\n")
        handle.write("START TRANSACTION;\n\n")

        if truncate_first:
            handle.write("-- Optional refresh path for an existing schema\n")
            for table in DELETE_ORDER:
                handle.write(f"DELETE FROM {table};\n")
            handle.write("\n")

        for table, columns, rows in table_payloads:
            emit_insert_blocks(handle, table, columns, rows, batch_size)

        handle.write("COMMIT;\n")


def main() -> None:
    args = parse_args()
    ensure_inputs(args.input_dir)
    manifest = load_json(args.input_dir / "manifest.json")
    table_payloads = build_table_payloads(args.input_dir)
    render_sql(
        output_path=args.output_sql,
        manifest=manifest,
        table_payloads=table_payloads,
        batch_size=args.batch_size,
        truncate_first=args.truncate_first,
    )
    total_rows = sum(len(rows) for _, _, rows in table_payloads)
    print(
        f"Wrote {args.output_sql} with {total_rows} row(s) across {len(table_payloads)} table payload(s)."
    )


if __name__ == "__main__":
    main()
