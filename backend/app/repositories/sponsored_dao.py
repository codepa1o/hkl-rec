from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.app.errors import IdempotencyConflictError
from backend.app.repositories._utils import json_text, placeholders
from backend.app.repositories.sponsored import (
    expected_spend_micros,
    sponsored_score,
)


@dataclass(frozen=True)
class SponsoredCandidate:
    campaign_id: int
    campaign_name: str
    creative_id: int
    news_id: str
    bid_micros: int
    predicted_ctr: float
    quality_score: float
    target_topic_ids: tuple[int, ...]

    @property
    def score(self) -> float:
        return float(sponsored_score(self.bid_micros, self.predicted_ctr, self.quality_score))

    @property
    def expected_spend_micros(self) -> int:
        return int(expected_spend_micros(self.bid_micros, self.predicted_ctr))


@dataclass(frozen=True)
class SponsoredDelivery:
    delivery_id: str
    request_id: str
    user_id: int
    campaign_id: int
    campaign_name: str
    creative_id: int
    news_id: str
    slot_position: int
    expected_spend_micros: int
    sponsored_score: float
    target_topic_ids: tuple[int, ...]


@dataclass(frozen=True)
class FeedRequestClaim:
    is_new: bool
    session_id: str
    page_number: int
    next_cursor: str | None


def claim_feed_request(
    connection: Any,
    *,
    request_id: str,
    user_id: int,
    page_size: int,
    debug: bool,
    include_sponsored: bool,
    experiment_arm: str,
    as_of_ts: int | None,
    category: str | None = None,
    cursor_token: str | None = None,
) -> FeedRequestClaim:
    with connection.cursor() as cursor:
        if cursor_token is None:
            session_id = request_id
            page_number = 0
        else:
            cursor.execute(
                """
                SELECT
                  session_id,
                  page_number,
                  user_id,
                  page_size,
                  debug,
                  include_sponsored,
                  experiment_arm,
                  as_of_ts,
                  category
                FROM feed_request
                WHERE cursor_token = %s
                FOR UPDATE
                """,
                (cursor_token,),
            )
            parent = cursor.fetchone()
            if parent is None:
                raise IdempotencyConflictError("feed cursor is invalid or expired")
            parent_shape = (
                int(parent["user_id"]),
                int(parent["page_size"]),
                bool(parent["debug"]),
                bool(parent["include_sponsored"]),
                str(parent["experiment_arm"]),
                int(parent["as_of_ts"]) if parent.get("as_of_ts") is not None else None,
                str(parent["category"]) if parent.get("category") is not None else None,
            )
            parent_requested_shape = (
                user_id,
                page_size,
                debug,
                include_sponsored,
                experiment_arm,
                as_of_ts,
                category,
            )
            if parent_shape != parent_requested_shape:
                raise IdempotencyConflictError("feed cursor reused with incompatible parameters")
            session_id = str(parent["session_id"])
            page_number = int(parent["page_number"]) + 1

        cursor.execute(
            """
            INSERT INTO feed_request (
              request_id,
              user_id,
              page_size,
              debug,
              include_sponsored,
              experiment_arm,
              as_of_ts,
              category,
              session_id,
              page_number,
              returned_news_ids_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '[]'::jsonb)
            ON CONFLICT (request_id) DO NOTHING
            """,
            (
                request_id,
                user_id,
                page_size,
                debug,
                include_sponsored,
                experiment_arm,
                as_of_ts,
                category,
                session_id,
                page_number,
            ),
        )
        inserted = int(cursor.rowcount) == 1
        if inserted:
            return FeedRequestClaim(
                is_new=True,
                session_id=session_id,
                page_number=page_number,
                next_cursor=None,
            )
        cursor.execute(
            """
            SELECT
              user_id,
              page_size,
              debug,
              include_sponsored,
              experiment_arm,
              as_of_ts,
              category,
              session_id,
              page_number,
              cursor_token
            FROM feed_request
            WHERE request_id = %s
            FOR UPDATE
            """,
            (request_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"feed request claim disappeared: {request_id}")
    existing_shape = (
        int(row["user_id"]),
        int(row["page_size"]),
        bool(row["debug"]),
        bool(row["include_sponsored"]),
        str(row["experiment_arm"]),
        int(row["as_of_ts"]) if row.get("as_of_ts") is not None else None,
        str(row["category"]) if row.get("category") is not None else None,
        str(row["session_id"]),
        int(row["page_number"]),
    )
    existing_requested_shape = (
        user_id,
        page_size,
        debug,
        include_sponsored,
        experiment_arm,
        as_of_ts,
        category,
        session_id,
        page_number,
    )
    if existing_shape != existing_requested_shape:
        raise IdempotencyConflictError(
            f"request_id reused with incompatible feed parameters: {request_id}"
        )
    return FeedRequestClaim(
        is_new=False,
        session_id=session_id,
        page_number=page_number,
        next_cursor=str(row["cursor_token"]) if row.get("cursor_token") else None,
    )


def load_feed_session_news_ids(
    connection: Any,
    *,
    session_id: str,
    exclude_request_id: str | None = None,
) -> set[str]:
    params: list[object] = [session_id]
    exclude_clause = ""
    if exclude_request_id is not None:
        exclude_clause = "AND request_id <> %s"
        params.append(exclude_request_id)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT returned.news_id
            FROM feed_request
            CROSS JOIN LATERAL jsonb_array_elements_text(
              returned_news_ids_json
            ) AS returned(news_id)
            WHERE session_id = %s
              {exclude_clause}
            """,
            tuple(params),
        )
        return {str(row["news_id"]) for row in cursor.fetchall()}


def complete_feed_request(
    connection: Any,
    *,
    request_id: str,
    news_ids: list[str],
    next_cursor: str | None,
) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE feed_request
            SET
              returned_news_ids_json = CASE
                WHEN jsonb_array_length(returned_news_ids_json) = 0
                  THEN %s::jsonb
                ELSE returned_news_ids_json
              END,
              cursor_token = COALESCE(cursor_token, %s)
            WHERE request_id = %s
            RETURNING cursor_token
            """,
            (json_text(news_ids), next_cursor, request_id),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"feed request disappeared before completion: {request_id}")
    return str(row["cursor_token"]) if row.get("cursor_token") else None


def load_sponsored_deliveries_for_request(
    connection: Any,
    *,
    request_id: str,
    user_id: int,
) -> list[SponsoredDelivery]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              sd.delivery_id,
              sd.request_id,
              sd.user_id,
              sd.campaign_id,
              sc.campaign_name,
              sd.creative_id,
              sd.news_id,
              sd.slot_position,
              sd.expected_spend_micros,
              scr.bid_micros,
              scr.predicted_ctr,
              scr.quality_score,
              STRING_AGG(
                DISTINCT sct.topic_id::text,
                ',' ORDER BY sct.topic_id::text
              ) AS target_topic_ids
            FROM sponsored_delivery sd
            JOIN sponsored_campaign sc ON sc.campaign_id = sd.campaign_id
            JOIN sponsored_creative scr ON scr.creative_id = sd.creative_id
            LEFT JOIN sponsored_campaign_topic sct
              ON sct.campaign_id = sd.campaign_id
            WHERE sd.request_id = %s
              AND sd.user_id = %s
            GROUP BY
              sd.delivery_id,
              sd.request_id,
              sd.user_id,
              sd.campaign_id,
              sc.campaign_name,
              sd.creative_id,
              sd.news_id,
              sd.slot_position,
              sd.expected_spend_micros,
              scr.bid_micros,
              scr.predicted_ctr,
              scr.quality_score
            ORDER BY sd.slot_position ASC
            """,
            (request_id, user_id),
        )
        rows = cursor.fetchall()
    return [
        SponsoredDelivery(
            delivery_id=str(row["delivery_id"]),
            request_id=str(row["request_id"]),
            user_id=int(row["user_id"]),
            campaign_id=int(row["campaign_id"]),
            campaign_name=str(row["campaign_name"]),
            creative_id=int(row["creative_id"]),
            news_id=str(row["news_id"]),
            slot_position=int(row["slot_position"]),
            expected_spend_micros=int(row["expected_spend_micros"]),
            sponsored_score=sponsored_score(
                int(row["bid_micros"]),
                float(row["predicted_ctr"]),
                float(row["quality_score"]),
            ),
            target_topic_ids=tuple(
                int(value) for value in str(row.get("target_topic_ids") or "").split(",") if value
            ),
        )
        for row in rows
    ]


def load_sponsored_candidates(
    connection: Any,
    *,
    user_id: int,
    target_topic_ids: list[int],
    now_ts: int,
    limit: int = 20,
    category: str | None = None,
) -> list[SponsoredCandidate]:
    if not target_topic_ids:
        return []
    topic_placeholders = placeholders(target_topic_ids)
    category_clause = "AND news.category = %s" if category is not None else ""
    category_params: tuple[object, ...] = (category,) if category is not None else ()
    budget_date = datetime.fromtimestamp(now_ts, UTC).date()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
              sc.campaign_id,
              sc.campaign_name,
              scr.creative_id,
              scr.news_id,
              scr.bid_micros,
              scr.predicted_ctr,
              scr.quality_score,
              STRING_AGG(
                DISTINCT sct.topic_id::text,
                ',' ORDER BY sct.topic_id::text
              ) AS target_topic_ids
            FROM sponsored_campaign sc
            JOIN sponsored_campaign_topic sct
              ON sct.campaign_id = sc.campaign_id
            JOIN sponsored_creative scr
              ON scr.campaign_id = sc.campaign_id
            JOIN mind_news AS news
              ON news.news_id = scr.news_id
            LEFT JOIN sponsored_campaign_daily_state daily
              ON daily.campaign_id = sc.campaign_id
             AND daily.budget_date = %s
            LEFT JOIN sponsored_user_daily_frequency frequency
              ON frequency.campaign_id = sc.campaign_id
             AND frequency.user_id = %s
             AND frequency.budget_date = %s
            WHERE sc.status = 'active'
              AND scr.status = 'active'
              AND sc.start_ts <= %s
              AND sc.end_ts >= %s
              AND sct.topic_id IN ({topic_placeholders})
              {category_clause}
              AND COALESCE(daily.expected_spend_micros, 0) < sc.daily_budget_micros
              AND COALESCE(frequency.served_impression_count, 0)
                    < sc.frequency_cap_per_user_per_day
            GROUP BY
              sc.campaign_id,
              sc.campaign_name,
              scr.creative_id,
              scr.news_id,
              scr.bid_micros,
              scr.predicted_ctr,
              scr.quality_score
            ORDER BY
              (scr.bid_micros * scr.predicted_ctr * scr.quality_score) DESC,
              scr.creative_id ASC
            LIMIT %s
            """,
            (
                budget_date,
                user_id,
                budget_date,
                now_ts,
                now_ts,
                *target_topic_ids,
                *category_params,
                limit,
            ),
        )
        rows = cursor.fetchall()
    return [
        SponsoredCandidate(
            campaign_id=int(row["campaign_id"]),
            campaign_name=str(row["campaign_name"]),
            creative_id=int(row["creative_id"]),
            news_id=str(row["news_id"]),
            bid_micros=int(row["bid_micros"]),
            predicted_ctr=float(row["predicted_ctr"]),
            quality_score=float(row["quality_score"]),
            target_topic_ids=tuple(
                int(value) for value in str(row.get("target_topic_ids") or "").split(",") if value
            ),
        )
        for row in rows
    ]


def reserve_sponsored_delivery(
    connection: Any,
    *,
    candidate: SponsoredCandidate,
    user_id: int,
    request_id: str,
    slot_position: int,
    now_ts: int,
    pacing_headroom_seconds: int,
) -> SponsoredDelivery | None:
    budget_date = datetime.fromtimestamp(now_ts, UTC).date()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              sc.campaign_name,
              sc.status,
              sc.start_ts,
              sc.end_ts,
              sc.daily_budget_micros,
              sc.pacing_mode,
              sc.frequency_cap_per_user_per_day,
              scr.status AS creative_status,
              scr.news_id,
              scr.bid_micros,
              scr.predicted_ctr,
              scr.quality_score
            FROM sponsored_campaign sc
            JOIN sponsored_creative scr
              ON scr.campaign_id = sc.campaign_id
            WHERE sc.campaign_id = %s
              AND scr.creative_id = %s
            FOR UPDATE
            """,
            (candidate.campaign_id, candidate.creative_id),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        if (
            row["status"] != "active"
            or row["creative_status"] != "active"
            or int(row["start_ts"]) > now_ts
            or int(row["end_ts"]) < now_ts
            or str(row["news_id"]) != candidate.news_id
        ):
            return None

        cursor.execute(
            """
            INSERT INTO sponsored_campaign_daily_state (campaign_id, budget_date)
            VALUES (%s, %s)
            ON CONFLICT (campaign_id, budget_date) DO NOTHING
            """,
            (candidate.campaign_id, budget_date),
        )
        cursor.execute(
            """
            SELECT expected_spend_micros
            FROM sponsored_campaign_daily_state
            WHERE campaign_id = %s AND budget_date = %s
            FOR UPDATE
            """,
            (candidate.campaign_id, budget_date),
        )
        daily = cursor.fetchone()

        cursor.execute(
            """
            INSERT INTO sponsored_user_daily_frequency (
              campaign_id,
              user_id,
              budget_date
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (campaign_id, user_id, budget_date) DO NOTHING
            """,
            (candidate.campaign_id, user_id, budget_date),
        )
        cursor.execute(
            """
            SELECT served_impression_count
            FROM sponsored_user_daily_frequency
            WHERE campaign_id = %s
              AND user_id = %s
              AND budget_date = %s
            FOR UPDATE
            """,
            (candidate.campaign_id, user_id, budget_date),
        )
        frequency = cursor.fetchone()

        bid_micros = int(row["bid_micros"])
        predicted_ctr = float(row["predicted_ctr"])
        quality_score = float(row["quality_score"])
        expected_spend = expected_spend_micros(bid_micros, predicted_ctr)
        daily_budget = int(row["daily_budget_micros"])
        spent = int(daily["expected_spend_micros"])
        frequency_count = int(frequency["served_impression_count"])
        if frequency_count >= int(row["frequency_cap_per_user_per_day"]):
            return None

        pacing_limit = daily_budget
        if row["pacing_mode"] == "even":
            current = datetime.fromtimestamp(now_ts, UTC)
            elapsed_seconds = current.hour * 3600 + current.minute * 60 + current.second
            delivery_fraction = min(
                1.0,
                (elapsed_seconds + max(0, pacing_headroom_seconds)) / 86_400,
            )
            pacing_limit = max(expected_spend, round(daily_budget * delivery_fraction))
        if spent + expected_spend > min(daily_budget, pacing_limit):
            return None

        delivery_id = f"ad-{uuid.uuid4().hex}"
        cursor.execute(
            """
            INSERT INTO sponsored_delivery (
              delivery_id,
              request_id,
              user_id,
              campaign_id,
              creative_id,
              news_id,
              slot_position,
              budget_date,
              expected_spend_micros,
              served_ts
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                delivery_id,
                request_id,
                user_id,
                candidate.campaign_id,
                candidate.creative_id,
                candidate.news_id,
                slot_position,
                budget_date,
                expected_spend,
                now_ts,
            ),
        )
        cursor.execute(
            """
            UPDATE sponsored_campaign_daily_state
            SET
              expected_spend_micros = expected_spend_micros + %s,
              served_impression_count = served_impression_count + 1
            WHERE campaign_id = %s AND budget_date = %s
            """,
            (expected_spend, candidate.campaign_id, budget_date),
        )
        cursor.execute(
            """
            UPDATE sponsored_user_daily_frequency
            SET
              served_impression_count = served_impression_count + 1,
              last_served_ts = %s
            WHERE campaign_id = %s
              AND user_id = %s
              AND budget_date = %s
            """,
            (now_ts, candidate.campaign_id, user_id, budget_date),
        )

    return SponsoredDelivery(
        delivery_id=delivery_id,
        request_id=request_id,
        user_id=user_id,
        campaign_id=candidate.campaign_id,
        campaign_name=str(row["campaign_name"]),
        creative_id=candidate.creative_id,
        news_id=candidate.news_id,
        slot_position=slot_position,
        expected_spend_micros=expected_spend,
        sponsored_score=sponsored_score(bid_micros, predicted_ctr, quality_score),
        target_topic_ids=candidate.target_topic_ids,
    )


def load_sponsored_attribution(
    connection: Any,
    *,
    delivery_id: str,
    user_id: int,
    news_id: str,
    for_update: bool = False,
) -> dict[str, Any]:
    lock_clause = " FOR UPDATE" if for_update else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
              delivery_id,
              request_id,
              user_id,
              campaign_id,
              creative_id,
              news_id,
              budget_date,
              confirmed_impression_ts,
              clicked_ts
            FROM sponsored_delivery
            WHERE delivery_id = %s
            {lock_clause}
            """,
            (delivery_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise ValueError(f"unknown sponsored_delivery_id: {delivery_id}")
    if int(row["user_id"]) != user_id or str(row["news_id"]) != news_id:
        raise ValueError("sponsored delivery does not match user_id and news_id")
    return dict(row)


def confirm_sponsored_impression(
    connection: Any,
    *,
    attribution: dict[str, Any],
    event_ts: int,
) -> bool:
    if attribution.get("confirmed_impression_ts") is not None:
        return False
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE sponsored_delivery
            SET
              confirmed_impression_ts = %s,
              delivery_status = CASE
                WHEN delivery_status = 'clicked' THEN delivery_status
                ELSE 'confirmed'
              END
            WHERE delivery_id = %s
              AND confirmed_impression_ts IS NULL
            """,
            (event_ts, attribution["delivery_id"]),
        )
        updated = int(cursor.rowcount) == 1
        if updated:
            cursor.execute(
                """
                UPDATE sponsored_campaign_daily_state
                SET confirmed_impression_count = confirmed_impression_count + 1
                WHERE campaign_id = %s AND budget_date = %s
                """,
                (attribution["campaign_id"], attribution["budget_date"]),
            )
    return updated


def record_sponsored_click(
    connection: Any,
    *,
    attribution: dict[str, Any],
    event_ts: int,
) -> bool:
    if attribution.get("clicked_ts") is not None:
        return False
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE sponsored_delivery
            SET
              clicked_ts = %s,
              delivery_status = 'clicked'
            WHERE delivery_id = %s
              AND clicked_ts IS NULL
            """,
            (event_ts, attribution["delivery_id"]),
        )
        updated = int(cursor.rowcount) == 1
        if updated:
            cursor.execute(
                """
                UPDATE sponsored_campaign_daily_state
                SET click_count = click_count + 1
                WHERE campaign_id = %s AND budget_date = %s
                """,
                (attribution["campaign_id"], attribution["budget_date"]),
            )
    return updated
