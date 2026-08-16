from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.app.repositories.mmr import mmr_config
from backend.app.repositories.ranker import build_feature_dict
from scripts.train_eval_mind import (
    COMPARISON_RANKING_METRICS,
    _build_features,
    _paired_bootstrap_confidence_intervals,
    _parse_mmr_penalties,
    _ranking_metrics,
    _request_group_sizes,
    _request_split,
    _select_mmr_penalty,
)


def test_global_request_split_keeps_equal_timestamp_requests_together():
    requests = pd.DataFrame(
        [
            {"request_id": "a", "event_ts": 10},
            {"request_id": "b", "event_ts": 20},
            {"request_id": "c", "event_ts": 20},
            {"request_id": "d", "event_ts": 30},
        ]
    )

    train, test, cutoff = _request_split(requests, 0.5)

    assert cutoff == 20
    assert set(train["request_id"]) == {"a"}
    assert set(test["request_id"]) == {"b", "c", "d"}


def test_request_group_sizes_preserve_contiguous_request_order():
    frame = pd.DataFrame({"request_id": ["a", "a", "b", "c", "c", "c"]})

    assert _request_group_sizes(frame) == [2, 1, 3]


def test_request_group_sizes_reject_non_contiguous_requests():
    frame = pd.DataFrame({"request_id": ["a", "a", "b", "a"]})

    with pytest.raises(ValueError, match="multiple non-contiguous groups"):
        _request_group_sizes(frame)


def test_request_group_sizes_preserve_total_row_count():
    frame = pd.DataFrame({"request_id": ["a", "b", "b", "c"]})

    assert sum(_request_group_sizes(frame)) == len(frame)


def test_paired_bootstrap_confidence_intervals_pair_by_request_id():
    pointwise = pd.DataFrame(
        [
            {"request_id": request_id, **dict.fromkeys(COMPARISON_RANKING_METRICS, 0.0)}
            for request_id in ("a", "b", "c")
        ]
    )
    lambdarank = pd.DataFrame(
        [
            {"request_id": request_id, **dict.fromkeys(COMPARISON_RANKING_METRICS, 1.0)}
            for request_id in ("c", "a", "b")
        ]
    )

    bootstrap = _paired_bootstrap_confidence_intervals(
        pointwise,
        lambdarank,
        iterations=20,
    )

    assert bootstrap["request_pairs"] == 3
    for interval in bootstrap["delta_intervals"].values():
        assert interval == {
            "mean_delta": 1.0,
            "lower_bound": 1.0,
            "upper_bound": 1.0,
            "stable_direction": "increase",
        }


def test_mind_features_use_only_prior_item_counts():
    impressions = pd.DataFrame(
        [
            {
                "request_id": "r1",
                "user_id": 1,
                "event_ts": 100,
                "candidate_position": 0,
                "article_id": 10,
                "clicked": True,
            },
            {
                "request_id": "r2",
                "user_id": 1,
                "event_ts": 200,
                "candidate_position": 0,
                "article_id": 10,
                "clicked": False,
            },
        ]
    )
    requests = pd.DataFrame(
        [
            {"request_id": "r1", "history_article_ids": [10]},
            {"request_id": "r2", "history_article_ids": [10]},
        ]
    )
    articles = pd.DataFrame(
        [
            {
                "article_id": 10,
                "category_topic_id": 7,
                "first_seen_train_ts": 100,
            }
        ]
    )

    features = _build_features(
        impressions,
        requests,
        articles,
        initial_impressions=Counter(),
        initial_clicks=Counter(),
        default_topic_weights={7: 1.0},
        update_counts=True,
    )

    assert list(features["article_impression_count"]) == [0, 1]
    assert list(features["article_click_count"]) == [0, 1]
    assert list(features["label"]) == [1, 0]


def test_runtime_base_score_matches_mind_training_formula():
    features = build_feature_dict(
        article_row={"first_seen_ts": 100},
        topic_ids=set(),
        topic_weight_map={},
        default_topic_weight_map={},
        query_topic_scores={},
        alpha=0.5,
        max_hot_score=1000,
        article_hot_score=100,
        now_ts=3700,
    )

    assert features["base_score"] == 0.5
    assert features["article_age_hours"] == 1.0


def test_mmr_ranking_metrics_improve_topic_coverage_without_recall_loss():
    frame = pd.DataFrame(
        [
            {
                "request_id": "r1",
                "article_id": article_id,
                "label": article_id == 1,
            }
            for article_id in range(1, 12)
        ]
    )
    scores = np.asarray([1.0 - article_id / 100 for article_id in range(1, 12)])
    article_category = {article_id: 1 if article_id <= 10 else 2 for article_id in range(1, 12)}
    article_topics = {
        article_id: frozenset({category}) for article_id, category in article_category.items()
    }
    similarity_pairs: list[tuple[str, str]] = []

    def similarity(left: str, right: str) -> None:
        similarity_pairs.append((left, right))
        return None

    context = {
        "article_topics": article_topics,
        "als_similarity": similarity,
    }

    baseline = _ranking_metrics(
        frame,
        scores,
        article_category,
        **context,
    )
    mmr = _ranking_metrics(
        frame,
        scores,
        article_category,
        mmr_similarity_penalty=0.2,
        **context,
    )

    assert mmr["recall@10"] == baseline["recall@10"]
    assert baseline["topic_coverage@10"] == 1.0
    assert mmr["topic_coverage@10"] == 2.0
    assert float(mmr["hybrid_intra_list_similarity@10"]) < float(
        baseline["hybrid_intra_list_similarity@10"]
    )
    assert similarity_pairs
    assert all(left.startswith("N") and right.startswith("N") for left, right in similarity_pairs)


def test_select_mmr_penalty_enforces_recall_guardrail_then_minimizes_similarity():
    baseline = {
        "recall@10": 0.596,
        "topic_coverage@10": 4.0,
        "hybrid_intra_list_similarity@10": 0.4,
    }
    sweep = [
        {
            "similarity_penalty": 0.1,
            "metrics": {
                "recall@10": 0.596,
                "topic_coverage@10": 5.0,
                "hybrid_intra_list_similarity@10": 0.3,
            },
        },
        {
            "similarity_penalty": 0.2,
            "metrics": {
                "recall@10": 0.593,
                "topic_coverage@10": 4.8,
                "hybrid_intra_list_similarity@10": 0.2,
            },
        },
        {
            "similarity_penalty": 0.3,
            "metrics": {
                "recall@10": 0.590,
                "topic_coverage@10": 6.0,
                "hybrid_intra_list_similarity@10": 0.1,
            },
        },
    ]

    selected = _select_mmr_penalty(baseline, sweep)

    assert selected is not None
    assert selected["similarity_penalty"] == 0.2


def test_parse_mmr_penalties_rejects_empty_or_negative_grid():
    assert _parse_mmr_penalties("0, 0.1, 0.1") == (0.0, 0.1)
    with pytest.raises(argparse.ArgumentTypeError, match="cannot be empty"):
        _parse_mmr_penalties("")
    with pytest.raises(argparse.ArgumentTypeError, match="non-negative"):
        _parse_mmr_penalties("0,-0.1")


def test_online_mmr_penalty_matches_published_selection():
    root = Path(__file__).resolve().parents[1]
    metrics = json.loads(
        (root / "docs" / "metrics" / "mind_recommendation.json").read_text(encoding="utf-8")
    )
    config = mmr_config("lgb_plus_als_plus_search_mmr")

    assert config is not None
    assert config.similarity_penalty == metrics["mmr"]["selected_similarity_penalty"]


def test_published_mmr_evidence_passes_diversity_and_recall_gates():
    root = Path(__file__).resolve().parents[1]
    report = json.loads(
        (root / "docs" / "metrics" / "mind_recommendation.json").read_text(encoding="utf-8")
    )
    baseline = report["ranking_arms"]["lightgbm"]
    selected = report["ranking_arms"]["lightgbm_mmr"]
    max_recall_drop = float(report["mmr"]["max_absolute_recall@10_drop"])

    assert float(selected["recall@10"]) >= float(baseline["recall@10"]) - max_recall_drop
    assert float(selected["category_diversity@10"]) > float(baseline["category_diversity@10"])
    assert float(selected["topic_coverage@10"]) > float(baseline["topic_coverage@10"])
    assert float(selected["hybrid_intra_list_similarity@10"]) < float(
        baseline["hybrid_intra_list_similarity@10"]
    )
