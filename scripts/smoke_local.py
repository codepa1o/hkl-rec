#!/usr/bin/env python3

from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a running NewsIntentRec local stack.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    return parser.parse_args()


def get_json(base_url: str, path: str, **params: Any) -> dict[str, Any]:
    query = f"?{urlencode(params)}" if params else ""
    with _opener.open(f"{base_url}{path}{query}", timeout=5) as response:
        return json.loads(response.read())


def post_json(base_url: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _opener.open(request, timeout=10) as response:
        return json.loads(response.read())


def ensure_smoke_session(base_url: str) -> None:
    from backend.app.config import get_settings

    if not get_settings().auth_secret_key:
        return
    email = "local-smoke@example.com"
    payload = {"email": email, "display_name": "Local Smoke", "password": "local-smoke-password"}
    try:
        post_json(base_url, "/auth/register", payload)
    except HTTPError as exc:
        if exc.code != 409:
            raise
        post_json(base_url, "/auth/login", {"email": email, "password": payload["password"]})


def wait_for_readiness(base_url: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return get_json(base_url, "/readyz")
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"backend did not become ready: {last_error}")


def pipeline_state(event_id: str, raw_topic: str, training_topic: str) -> dict[str, Any]:
    from backend.app.config import get_settings
    from backend.app.repositories.connection import connect, parse_database_url

    settings = get_settings()
    connection = connect(parse_database_url(settings.database_url))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS event_count
                FROM user_event
                WHERE external_event_id = %s
                """,
                (event_id,),
            )
            event_count = int(cursor.fetchone()["event_count"])
            cursor.execute(
                """
                SELECT topic, status
                FROM event_outbox
                WHERE event_id = %s
                  AND topic IN (%s, %s)
                """,
                (event_id, raw_topic, training_topic),
            )
            outbox = {str(row["topic"]): str(row["status"]) for row in cursor.fetchall()}
    finally:
        connection.close()
    return {"event_count": event_count, "outbox": outbox}


def main() -> None:
    args = parse_args()
    from backend.app.config import get_settings

    settings = get_settings()
    user_id = args.user_id or settings.default_demo_user_id
    readiness = wait_for_readiness(args.base_url, args.timeout_seconds)
    if readiness.get("status") != "ok":
        raise SystemExit(f"readiness failed: {readiness}")
    ensure_smoke_session(args.base_url)

    profile = get_json(args.base_url, "/debug/profile", user_id=user_id)
    feed = get_json(
        args.base_url,
        "/feed",
        user_id=user_id,
        page_size=10,
        debug="true",
    )
    if not feed.get("items"):
        raise SystemExit("feed smoke check returned no items")
    first = next(
        (item for item in feed["items"] if item.get("content_type") == "organic"),
        feed["items"][0],
    )
    event_id = f"smoke-click-{user_id}-{feed['request_id']}-{first['news_id']}"
    event = post_json(
        args.base_url,
        "/event/track",
        {
            "event_id": event_id,
            "user_id": user_id,
            "event_type": "recommendation_click",
            "surface": "feed",
            "news_id": first["news_id"],
            "request_id": feed["request_id"],
        },
    )
    if not event.get("ok"):
        raise SystemExit(f"click smoke check failed: {event}")

    baseline_score = float(profile["behavior_score"])
    deadline = time.monotonic() + args.timeout_seconds
    final_profile = profile
    state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        final_profile = get_json(args.base_url, "/debug/profile", user_id=user_id)
        state = pipeline_state(
            event_id,
            raw_topic=settings.kafka_raw_events_topic,
            training_topic=settings.kafka_training_topic,
        )
        profile_applied = float(final_profile["behavior_score"]) > baseline_score
        if readiness["event_mode"] == "sync_postgres":
            if profile_applied and state["event_count"] == 1:
                break
        else:
            raw_published = state["outbox"].get(settings.kafka_raw_events_topic) == "published"
            training_published = state["outbox"].get(settings.kafka_training_topic) == "published"
            if (
                profile_applied
                and state["event_count"] == 1
                and raw_published
                and training_published
            ):
                break
        time.sleep(0.5)
    else:
        raise SystemExit(
            "event pipeline did not complete before timeout: "
            f"profile={final_profile}, state={state}"
        )

    print(
        json.dumps(
            {
                "status": "ok",
                "repository_backend": readiness.get("repository_backend"),
                "user_id": profile.get("user_id"),
                "feed_items": len(feed["items"]),
                "click_event_id": event_id,
                "event_mode": readiness.get("event_mode"),
                "pipeline_state": state,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
