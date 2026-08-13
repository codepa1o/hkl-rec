"""V1 的离线排序指标。

这里只包含纯函数，不访问数据库、HTTP 或配置。scripts/ 中的驱动脚本负责
收集逐事件的预测值/真实值对，并将其传入这些函数。相关测试位于
tests/test_evaluate.py，使用默认的非 MySQL pytest 测试层。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TimeSplit:
    """按时间顺序划分训练集、验证集和测试集的结果。

    `split_ts_train_val` 是最后一个训练事件的 event_ts；`split_ts_val_test`
    是最后一个验证事件的 event_ts（验证集为空时回退到训练集边界）。
    输入为空时二者均为 None。
    """

    train: list[dict[str, Any]]
    val: list[dict[str, Any]]
    test: list[dict[str, Any]]
    split_ts_train_val: int | None
    split_ts_val_test: int | None


def time_split(
    events: Iterable[dict[str, Any]],
    *,
    train_ratio: float = 0.8,
    val_ratio: float = 0.0,
    ts_key: str = "event_ts",
) -> TimeSplit:
    """按 ts_key 对事件排序，再依据累计数量比例切分。

    当 val_ratio == 0.0 时验证集为空，切分退化为仅包含训练集和测试集。
    ts_key 相同时保持稳定排序顺序。
    """
    if train_ratio < 0 or val_ratio < 0 or train_ratio + val_ratio > 1.0:
        raise ValueError("ratios must be in [0,1] and sum to <= 1.0")
    ordered = sorted(events, key=lambda e: int(e[ts_key]))
    n = len(ordered)
    if n == 0:
        return TimeSplit(train=[], val=[], test=[], split_ts_train_val=None, split_ts_val_test=None)
    n_train = min(round(n * train_ratio), n)
    n_val = min(round(n * val_ratio), n - n_train)
    train = ordered[:n_train]
    val = ordered[n_train : n_train + n_val]
    test = ordered[n_train + n_val :]
    split_tv = int(train[-1][ts_key]) if train else None
    split_vt = int(val[-1][ts_key]) if val else split_tv
    return TimeSplit(
        train=train,
        val=val,
        test=test,
        split_ts_train_val=split_tv,
        split_ts_val_test=split_vt,
    )


def recall_at_k(predicted: Sequence[int], relevant: Iterable[int], k: int) -> float:
    """计算 |relevant 与 predicted[:k] 的交集| / |relevant|。

    当 k <= 0 或 `relevant` 为空时返回 0.0。对于每个查询只有一个相关项的评估，
    调用方应传入 `relevant=[article_id]`；命中时返回 1.0，否则返回 0.0，
    对各查询结果取平均即可得到 Hit Rate@K。
    """
    if k <= 0:
        return 0.0
    rel_set = set(relevant)
    if not rel_set:
        return 0.0
    top_k = list(predicted)[:k]
    hits = sum(1 for a in top_k if a in rel_set)
    return hits / len(rel_set)


def ndcg_at_k(predicted: Sequence[int], relevant: Iterable[int], k: int) -> float:
    """计算标准二元增益 NDCG@k。

    对从 1 开始计数的位置，DCG = sum_{i=1..k} rel_i / log2(i + 1)。
    IDCG = sum_{i=1..min(|relevant|, k)} 1 / log2(i + 1)。
    当 k <= 0、`relevant` 为空，或 `predicted[:k]` 中没有相关项时返回 0.0。
    """
    if k <= 0:
        return 0.0
    rel_set = set(relevant)
    if not rel_set:
        return 0.0
    top_k = list(predicted)[:k]
    dcg = sum(1.0 / math.log2(i + 1) for i, a in enumerate(top_k, start=1) if a in rel_set)
    ideal_hits = min(len(rel_set), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def graded_ndcg_at_k(
    predicted: Sequence[int],
    relevance: Mapping[int, float],
    k: int,
) -> float:
    if k <= 0 or not relevance:
        return 0.0
    top_k = list(predicted)[:k]
    dcg = sum(
        (2.0 ** float(relevance.get(article_id, 0.0)) - 1.0) / math.log2(rank + 1)
        for rank, article_id in enumerate(top_k, start=1)
    )
    ideal_gains = sorted(
        (2.0 ** float(value) - 1.0 for value in relevance.values() if value > 0),
        reverse=True,
    )[:k]
    idcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(ideal_gains, start=1))
    return dcg / idcg if idcg > 0 else 0.0


def mrr_at_k(predicted: Sequence[int], relevant: Iterable[int], k: int) -> float:
    if k <= 0:
        return 0.0
    relevant_ids = set(relevant)
    for rank, article_id in enumerate(list(predicted)[:k], start=1):
        if article_id in relevant_ids:
            return 1.0 / rank
    return 0.0
