from __future__ import annotations

import json
import time
import uuid
from typing import Any

from backend.app.schemas.event import UpdatedTopicDelta
from backend.app.schemas.profile import ProfileRecentClick, ProfileRecentQuery, ProfileTopicWeight


def parse_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        if not value.strip():
            return default
        return json.loads(value)
    return default


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def placeholders(values: list[Any]) -> str:
    return ",".join(["%s"] * len(values))


def normalize_query_key(query_key: str) -> str:
    normalized = " ".join(query_key.split())
    if not normalized:
        raise ValueError("query_key must not be blank")
    return normalized


def query_tokens(query_key: str) -> list[int]:
    tokens: list[int] = []
    for part in (query_key or "").split():
        try:
            tokens.append(int(part))
        except ValueError as exc:
            raise ValueError(
                f"query_key must be space-separated integers; got token {part!r} in {query_key!r}"
            ) from exc
    return tokens


def is_numeric_query_key(query_key: str) -> bool:
    parts = (query_key or "").split()
    if not parts:
        return False
    return all(part.lstrip("-").isdigit() for part in parts)


def parse_topic_weights(value: Any) -> list[ProfileTopicWeight]:
    rows = parse_json(value, [])
    return [
        ProfileTopicWeight(
            topic_id=int(row["topic_id"]),
            weight=float(row.get("weight") or 0.0),
        )
        for row in rows
        if "topic_id" in row
    ]


def parse_recent_clicks(value: Any) -> list[ProfileRecentClick]:
    rows = parse_json(value, [])
    return [
        ProfileRecentClick(
            news_id=str(row["news_id"]),
            click_ts=int(row.get("click_ts") or 0),
        )
        for row in rows
        if "news_id" in row
    ]


def parse_recent_queries(value: Any) -> list[ProfileRecentQuery]:
    rows = parse_json(value, [])
    return [
        ProfileRecentQuery(
            query_key=str(row["query_key"]),
            query_ts=int(row.get("query_ts") or 0),
            confirmed_ts=(
                int(row["confirmed_ts"]) if row.get("confirmed_ts") is not None else None
            ),
        )
        for row in rows
        if "query_key" in row
    ]


def add_feed_candidate(
    candidates: dict[str, dict[str, Any]],
    news_id: str,
    source: str,
    is_fallback: bool,
    raw_base_score: float,
) -> None:
    candidate = candidates.setdefault(
        news_id,
        {
            "sources": set(),
            "is_fallback": is_fallback,
            "raw_base_score": raw_base_score,
        },
    )
    candidate["sources"].add(source)
    candidate["raw_base_score"] = max(float(candidate["raw_base_score"]), raw_base_score)
    if not is_fallback:
        candidate["is_fallback"] = False


def selected_reason(is_fallback: bool, sources: set[str]) -> str:
    if is_fallback:
        return "Filled by hot_or_fresh because primary recall was short."
    if "recent_query_topic" in sources:
        return "Selected because recent query categories boosted this article."
    if "profile_topic" in sources:
        return "Selected because its categories match the user profile."
    return "Selected by base recall score."


def topic_delta_models(topic_deltas: dict[int, float]) -> list[UpdatedTopicDelta]:
    return [
        UpdatedTopicDelta(topic_id=topic_id, delta=round(delta, 6))
        for topic_id, delta in sorted(topic_deltas.items())
    ]


def new_request_id(prefix: str, operation: str) -> str:
    return f"{prefix}-{operation}-{int(time.time() * 1000)}-{uuid.uuid4().hex}"


def updated_topic_weights(
    current_weights: Any,
    topic_deltas: dict[int, float],
    decay_factor: float,
) -> list[dict[str, float | int]]:
    weights: dict[int, float] = {}
    for row in current_weights:
        if not isinstance(row, dict) or "topic_id" not in row:
            continue
        weights[int(row["topic_id"])] = float(row.get("weight") or 0.0) * decay_factor

    for topic_id, delta in topic_deltas.items():
        weights[topic_id] = weights.get(topic_id, 0.0) + delta

    sorted_weights = sorted(
        (
            {"topic_id": topic_id, "weight": round(weight, 6)}
            for topic_id, weight in weights.items()
            if weight > 0
        ),
        key=lambda row: (-float(row["weight"]), int(row["topic_id"])),
    )
    return sorted_weights[:10]
