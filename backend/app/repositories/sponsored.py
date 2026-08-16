from __future__ import annotations

from collections.abc import Mapping


def sponsored_score(bid_micros: int, predicted_ctr: float, quality_score: float) -> float:
    return float(bid_micros) * predicted_ctr * quality_score


def expected_spend_micros(bid_micros: int, predicted_ctr: float) -> int:
    return max(1, round(float(bid_micros) * predicted_ctr))


def sponsored_slot_is_reachable(
    *,
    organic_news_ids: set[str],
    already_sponsored_news_ids: set[str],
    candidate_news_id: str,
    slot_position: int,
    sponsored_count: int,
) -> bool:
    required_organic_before = slot_position - 1 - sponsored_count
    remaining_organic_count = len(
        organic_news_ids - already_sponsored_news_ids - {candidate_news_id}
    )
    return remaining_organic_count >= required_organic_before


def blend_fixed_slots[T](
    organic_items: list[T],
    sponsored_by_slot: Mapping[int, T],
    *,
    page_size: int,
) -> list[T]:
    blended: list[T] = []
    organic_index = 0
    for position in range(1, page_size + 1):
        sponsored = sponsored_by_slot.get(position)
        if sponsored is not None:
            blended.append(sponsored)
            continue
        if organic_index >= len(organic_items):
            unreachable_slots = [slot for slot in sponsored_by_slot if slot > position]
            if unreachable_slots:
                raise ValueError(
                    "sponsored slots are unreachable with the available organic inventory"
                )
            break
        blended.append(organic_items[organic_index])
        organic_index += 1
    return blended
