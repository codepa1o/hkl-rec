from __future__ import annotations

import math

import pytest

from backend.app.evaluate import (
    TimeSplit,
    graded_ndcg_at_k,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    time_split,
)

# ---------------------------- recall_at_k 测试 ----------------------------


def test_recall_returns_zero_when_relevant_is_empty():
    assert recall_at_k([1, 2, 3], [], k=10) == 0.0


def test_recall_returns_zero_when_k_is_zero():
    assert recall_at_k([1, 2, 3], [1], k=0) == 0.0


def test_recall_single_relevant_hit_at_rank_one():
    assert recall_at_k([1, 2, 3, 4, 5], [1], k=5) == 1.0


def test_recall_single_relevant_hit_at_rank_k():
    assert recall_at_k([9, 8, 7, 6, 5], [5], k=5) == 1.0


def test_recall_single_relevant_miss_at_rank_k_plus_one():
    assert recall_at_k([9, 8, 7, 6, 5, 1], [1], k=5) == 0.0


def test_recall_multiple_relevant_partial_hit():
    # 3 个相关项中有 2 个进入前 5 名
    assert recall_at_k([1, 2, 3, 4, 5], [1, 3, 99], k=5) == pytest.approx(2 / 3)


def test_recall_k_larger_than_predicted_uses_all_predicted():
    assert recall_at_k([1, 2], [1, 2, 3], k=10) == pytest.approx(2 / 3)


# ---------------------------- ndcg_at_k 测试 ----------------------------


def test_ndcg_single_relevant_at_rank_one_is_one():
    assert ndcg_at_k([1, 2, 3], [1], k=3) == pytest.approx(1.0)


def test_ndcg_single_relevant_at_rank_two_is_log_based():
    # 排名为 2 时：DCG = 1/log2(3)，IDCG = 1/log2(2) = 1
    expected = 1.0 / math.log2(3)
    assert ndcg_at_k([9, 5, 3], [5], k=3) == pytest.approx(expected)


def test_ndcg_single_relevant_outside_top_k_is_zero():
    assert ndcg_at_k([9, 8, 7, 6, 5, 1], [1], k=5) == 0.0


def test_ndcg_multiple_relevant_in_ideal_order_is_one():
    # 3 个相关项按理想顺序占据前 3 位时，NDCG = 1.0
    assert ndcg_at_k([1, 2, 3, 99, 100], [1, 2, 3], k=5) == pytest.approx(1.0)


def test_ndcg_returns_zero_when_relevant_empty():
    assert ndcg_at_k([1, 2, 3], [], k=3) == 0.0


def test_ndcg_returns_zero_when_k_is_zero():
    assert ndcg_at_k([1, 2, 3], [1], k=0) == 0.0


def test_graded_ndcg_rewards_highly_relevant_items_first():
    relevance = {1: 2.0, 2: 1.0}

    assert graded_ndcg_at_k([1, 2], relevance, k=2) == pytest.approx(1.0)
    assert graded_ndcg_at_k([2, 1], relevance, k=2) < 1.0


def test_mrr_at_k_uses_first_relevant_rank():
    assert mrr_at_k([9, 8, 3, 2], [2, 3], k=4) == pytest.approx(1 / 3)
    assert mrr_at_k([9, 8, 3, 2], [2, 3], k=2) == 0.0


# ---------------------------- time_split 测试 ----------------------------


def test_time_split_80_20_on_monotonic_ts():
    events = [{"event_ts": i, "n": i} for i in range(1, 101)]
    s = time_split(events, train_ratio=0.8)
    assert isinstance(s, TimeSplit)
    assert len(s.train) == 80
    assert len(s.val) == 0
    assert len(s.test) == 20
    assert s.train[0]["n"] == 1
    assert s.train[-1]["n"] == 80
    assert s.test[0]["n"] == 81
    assert s.split_ts_train_val == 80
    assert s.split_ts_val_test == 80  # 验证集为空，沿用训练集边界


def test_time_split_60_20_20_with_val():
    events = [{"event_ts": i} for i in range(1, 101)]
    s = time_split(events, train_ratio=0.6, val_ratio=0.2)
    assert len(s.train) == 60
    assert len(s.val) == 20
    assert len(s.test) == 20
    assert s.split_ts_train_val == 60
    assert s.split_ts_val_test == 80


def test_time_split_empty_input_returns_empty_split():
    s = time_split([], train_ratio=0.8)
    assert s.train == [] and s.val == [] and s.test == []
    assert s.split_ts_train_val is None
    assert s.split_ts_val_test is None


def test_time_split_sorts_unordered_input():
    events = [{"event_ts": 30}, {"event_ts": 10}, {"event_ts": 20}]
    s = time_split(events, train_ratio=2 / 3)
    assert [e["event_ts"] for e in s.train] == [10, 20]
    assert [e["event_ts"] for e in s.test] == [30]


def test_time_split_rejects_invalid_ratios():
    with pytest.raises(ValueError):
        time_split([], train_ratio=0.6, val_ratio=0.5)  # 比例之和大于 1.0
    with pytest.raises(ValueError):
        time_split([], train_ratio=-0.1)


def test_time_split_respects_custom_ts_key():
    events = [{"t": 3, "i": "c"}, {"t": 1, "i": "a"}, {"t": 2, "i": "b"}]
    s = time_split(events, train_ratio=2 / 3, ts_key="t")
    assert [e["i"] for e in s.train] == ["a", "b"]
    assert [e["i"] for e in s.test] == ["c"]
