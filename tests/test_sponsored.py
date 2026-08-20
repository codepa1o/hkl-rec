from __future__ import annotations

import pytest

from backend.app.errors import InvalidSponsoredAttributionError
from backend.app.repositories.sponsored import (
    blend_fixed_slots,
    expected_spend_micros,
    sponsored_score,
    sponsored_slot_is_reachable,
)
from backend.app.repositories.sponsored_dao import (
    claim_feed_request,
    load_sponsored_attribution,
    load_sponsored_candidates,
)


class RecordingCursor:
    rowcount = 1

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[dict[str, object]]:
        return []


class RecordingConnection:
    def __init__(self) -> None:
        self.cursor_value = RecordingCursor()

    def cursor(self) -> RecordingCursor:
        return self.cursor_value


def test_sponsored_score_and_expected_spend_are_distinct():
    assert expected_spend_micros(5000, 0.05) == 250
    assert sponsored_score(5000, 0.05, 0.9) == 225.0


def test_fixed_slots_insert_sponsored_items_at_three_and_eight():
    organic = [f"organic-{index}" for index in range(1, 9)]
    blended = blend_fixed_slots(
        organic,
        {3: "sponsored-a", 8: "sponsored-b"},
        page_size=10,
    )

    assert len(blended) == 10
    assert blended[2] == "sponsored-a"
    assert blended[7] == "sponsored-b"
    assert [item for item in blended if item.startswith("organic")] == organic


def test_fixed_slots_degrade_for_short_pages():
    blended = blend_fixed_slots(
        ["organic-1", "organic-2"],
        {3: "sponsored-a", 8: "sponsored-b"},
        page_size=3,
    )

    assert blended == ["organic-1", "organic-2", "sponsored-a"]


def test_unreachable_sponsored_slot_is_rejected_before_reservation():
    assert (
        sponsored_slot_is_reachable(
            organic_news_ids={"N1"},
            already_sponsored_news_ids=set(),
            candidate_news_id="N99",
            slot_position=3,
            sponsored_count=0,
        )
        is False
    )
    with pytest.raises(ValueError, match="unreachable"):
        blend_fixed_slots(["organic-1"], {3: "sponsored-a"}, page_size=3)


def test_feed_request_claim_persists_category_in_request_shape() -> None:
    connection = RecordingConnection()

    claim_feed_request(
        connection,
        request_id="feed-sports",
        user_id=7001,
        page_size=10,
        debug=False,
        include_sponsored=True,
        experiment_arm="default",
        as_of_ts=None,
        category="sports",
    )

    insert_sql, insert_params = connection.cursor_value.executed[0]
    assert "category" in insert_sql
    assert "sports" in insert_params


def test_sponsored_candidates_are_filtered_by_exact_category() -> None:
    connection = RecordingConnection()

    candidates = load_sponsored_candidates(
        connection,
        user_id=7001,
        target_topic_ids=[7],
        now_ts=1_700_000_000,
        category="sports",
    )

    assert candidates == []
    sql, params = connection.cursor_value.executed[0]
    assert "JOIN mind_news AS news" in sql
    assert "news.category = %s" in sql
    assert "sports" in params


@pytest.mark.parametrize(
    "row",
    [
        None,
        {"user_id": 8, "news_id": "N1"},
        {"user_id": 7, "news_id": "N2"},
    ],
)
def test_invalid_sponsored_attribution_is_typed_non_retryable(
    row: dict[str, object] | None,
) -> None:
    class AttributionCursor(RecordingCursor):
        def fetchone(self) -> dict[str, object] | None:
            return row

    class AttributionConnection:
        def cursor(self) -> AttributionCursor:
            return AttributionCursor()

    with pytest.raises(InvalidSponsoredAttributionError):
        load_sponsored_attribution(
            AttributionConnection(),
            delivery_id="delivery-unknown",
            user_id=7,
            news_id="N1",
        )
