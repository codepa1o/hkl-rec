from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from backend.app.db.migration import canonical_row, convert_row, migration_table_names
from backend.app.db.schema import metadata


def test_migration_order_respects_foreign_keys_and_covers_all_tables() -> None:
    names = migration_table_names()

    assert set(names) == set(metadata.tables)
    assert names.index("app_user") < names.index("user_account")
    assert names.index("mind_news") < names.index("mind_news_stats")
    assert names.index("mind_catalog_import") < names.index("mind_news_stats")
    assert names.index("sponsored_creative") < names.index("sponsored_delivery")
    assert names.index("sponsored_delivery") < names.index("user_event")


def test_convert_row_adapts_mysql_json_and_tinyint_to_postgres_types() -> None:
    table = metadata.tables["app_user"]
    row = convert_row(
        table,
        {
            "user_id": 7,
            "display_name": "Reader",
            "register_ts": 123,
            "gender": None,
            "login_frequency": None,
            "follower_count": 0,
            "followed_topic_count": 0,
            "answer_count": 0,
            "question_count": 0,
            "comment_count": 0,
            "thanks_received_count": 0,
            "likes_received_count": 0,
            "province": None,
            "city": None,
            "followed_topic_ids_json": "[1, 2]",
            "is_demo_user": 1,
            "source": "mind_small",
        },
    )

    assert row["followed_topic_ids_json"] == [1, 2]
    assert row["is_demo_user"] is True


def test_canonical_row_is_stable_for_cross_database_types() -> None:
    columns = ("amount", "created", "day", "payload")
    left = canonical_row(
        columns,
        {
            "amount": Decimal("1.230000"),
            "created": datetime(2026, 8, 14, 12, 30, 1, 123456),
            "day": date(2026, 8, 14),
            "payload": {"b": [2, 1], "a": True},
        },
    )
    right = canonical_row(
        columns,
        {
            "payload": {"a": True, "b": [2, 1]},
            "day": date(2026, 8, 14),
            "created": datetime(2026, 8, 14, 12, 30, 1, 123456),
            "amount": Decimal("1.230000"),
        },
    )

    assert left == right
