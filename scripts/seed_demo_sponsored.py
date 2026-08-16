from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.repositories.connection import connect, parse_database_url  # noqa: E402


def seed_demo_sponsored(connection: object) -> list[int]:
    with connection.transaction(), connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            """
            SELECT DISTINCT ON (news.news_id) news.news_id
            FROM mind_news AS news
            JOIN mind_news_stats AS stats USING (news_id)
            JOIN mind_news_topic AS mapping USING (news_id)
            WHERE mapping.topic_id IN (
                SELECT topic_id FROM topic ORDER BY news_count DESC, topic_id LIMIT 6
            )
            ORDER BY news.news_id, stats.hot_score DESC
            LIMIT 3
            """
        )
        news_ids = [str(row["news_id"]) for row in cursor.fetchall()]
        if len(news_ids) < 3:
            raise RuntimeError("at least three canonical MIND news rows are required for demo ads")

        campaign_ids: list[int] = []
        for offset, news_id in enumerate(news_ids, start=1):
            campaign_id = 91_000 + offset
            creative_id = 92_000 + offset
            campaign_ids.append(campaign_id)
            cursor.execute(
                """
                INSERT INTO sponsored_campaign (
                    campaign_id, campaign_name, status, start_ts, end_ts,
                    daily_budget_micros, pacing_mode, frequency_cap_per_user_per_day
                ) VALUES (%s, %s, 'active', 0, 4102444800, 100000000, 'asap', 10)
                ON CONFLICT (campaign_id) DO UPDATE SET
                    campaign_name = EXCLUDED.campaign_name,
                    status = EXCLUDED.status,
                    start_ts = EXCLUDED.start_ts,
                    end_ts = EXCLUDED.end_ts,
                    daily_budget_micros = EXCLUDED.daily_budget_micros,
                    pacing_mode = EXCLUDED.pacing_mode,
                    frequency_cap_per_user_per_day = EXCLUDED.frequency_cap_per_user_per_day,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (campaign_id, f"MIND Demo Campaign {offset}"),
            )
            cursor.execute(
                """
                INSERT INTO sponsored_creative (
                    creative_id, campaign_id, news_id, status, bid_micros,
                    predicted_ctr, quality_score
                ) VALUES (%s, %s, %s, 'active', %s, %s, %s)
                ON CONFLICT (creative_id) DO UPDATE SET
                    campaign_id = EXCLUDED.campaign_id,
                    news_id = EXCLUDED.news_id,
                    status = EXCLUDED.status,
                    bid_micros = EXCLUDED.bid_micros,
                    predicted_ctr = EXCLUDED.predicted_ctr,
                    quality_score = EXCLUDED.quality_score,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (creative_id, campaign_id, news_id, 1000 + offset * 100, 0.1, 1.0),
            )
            cursor.execute(
                "DELETE FROM sponsored_campaign_topic WHERE campaign_id = %s",
                (campaign_id,),
            )
            cursor.execute(
                """
                INSERT INTO sponsored_campaign_topic (campaign_id, topic_id)
                SELECT %s, topic_id FROM mind_news_topic WHERE news_id = %s
                """,
                (campaign_id, news_id),
            )
    return campaign_ids


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed canonical MIND-backed demo campaigns.")
    parser.add_argument("--database-url", default=os.environ.get("NEWSREC_DATABASE_URL", ""))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.database_url:
        print("error: NEWSREC_DATABASE_URL or --database-url is required", file=sys.stderr)
        return 2
    connection = connect(parse_database_url(args.database_url))
    try:
        campaign_ids = seed_demo_sponsored(connection)
    finally:
        connection.close()
    print(json.dumps({"campaign_ids": campaign_ids, "status": "seeded"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
