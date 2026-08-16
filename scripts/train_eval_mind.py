from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq
from scipy.sparse import csr_matrix
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.repositories.mmr import (  # noqa: E402
    ItemSimilarity,
    MMRCandidate,
    hybrid_item_similarity,
    rerank_mmr,
)
from backend.app.repositories.ranker import (  # noqa: E402
    FEATURE_SCHEMA_VERSION,
    RANKER_FEATURE_COLUMNS,
)

COMPARISON_RANKING_METRICS = (
    "recall@5",
    "recall@10",
    "ndcg@5",
    "ndcg@10",
    "mrr",
    "category_diversity@10",
)
PAIRED_BOOTSTRAP_ITERATIONS = 2_000
PAIRED_BOOTSTRAP_SEED = 42
MMR_MAX_RECALL_DROP = 0.005
DEFAULT_MMR_PENALTIES = (
    0.0,
    0.0025,
    0.005,
    0.01,
    0.015,
    0.02,
    0.025,
    0.03,
    0.04,
    0.05,
    0.075,
    0.1,
    0.2,
    0.3,
    0.5,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_mmr_penalties(value: str) -> tuple[float, ...]:
    penalties = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    if not penalties:
        raise argparse.ArgumentTypeError("MMR penalty grid cannot be empty")
    if any(penalty < 0 for penalty in penalties):
        raise argparse.ArgumentTypeError("MMR penalties must be non-negative")
    return tuple(dict.fromkeys(penalties))


def _request_split(
    requests: pd.DataFrame,
    train_ratio: float,
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    ordered = requests.sort_values(["event_ts", "request_id"], kind="stable").reset_index(drop=True)
    cutoff_index = max(1, min(round(len(ordered) * train_ratio), len(ordered) - 1))
    cutoff_ts = int(ordered.iloc[cutoff_index]["event_ts"])
    train = ordered[ordered["event_ts"] < cutoff_ts].copy()
    test = ordered[ordered["event_ts"] >= cutoff_ts].copy()
    if train.empty or test.empty:
        raise RuntimeError("Global chronological request split produced an empty partition")
    return train, test, cutoff_ts


def _request_group_sizes(frame: pd.DataFrame) -> list[int]:
    request_ids = frame["request_id"].astype(str).tolist()
    if not request_ids:
        return []

    group_sizes: list[int] = []
    completed_requests: set[str] = set()
    current_request = request_ids[0]
    current_size = 0
    for request_id in request_ids:
        if request_id != current_request:
            completed_requests.add(current_request)
            if request_id in completed_requests:
                raise ValueError(
                    f"Request {request_id!r} appears in multiple non-contiguous groups"
                )
            group_sizes.append(current_size)
            current_request = request_id
            current_size = 0
        current_size += 1
    group_sizes.append(current_size)

    if sum(group_sizes) != len(frame):
        raise RuntimeError("Request group sizes do not preserve the frame row count")
    return group_sizes


def _read_impressions(
    path: Path,
    request_ids: list[str],
    *,
    columns: list[str],
) -> pd.DataFrame:
    if not request_ids:
        return pd.DataFrame(columns=columns)
    table = ds.dataset(path, format="parquet").to_table(
        columns=columns,
        filter=ds.field("request_id").isin(request_ids),
    )
    return table.to_pandas()


def _item_counts(frame: pd.DataFrame) -> tuple[Counter[int], Counter[int]]:
    impressions = Counter(int(value) for value in frame["article_id"])
    clicks = Counter(int(value) for value in frame.loc[frame["clicked"].astype(bool), "article_id"])
    return impressions, clicks


def _request_profiles(
    requests: pd.DataFrame,
    article_category: dict[int, int],
) -> tuple[dict[str, dict[int, float]], dict[str, int]]:
    profiles: dict[str, dict[int, float]] = {}
    history_lengths: dict[str, int] = {}
    for row in requests.itertuples(index=False):
        history = [int(value) for value in row.history_article_ids]
        counts = Counter(
            article_category[article_id] for article_id in history if article_id in article_category
        )
        total = sum(counts.values())
        profiles[str(row.request_id)] = (
            {topic_id: count / total for topic_id, count in counts.items()} if total else {}
        )
        history_lengths[str(row.request_id)] = len(history)
    return profiles, history_lengths


def _build_features(
    impressions: pd.DataFrame,
    requests: pd.DataFrame,
    articles: pd.DataFrame,
    *,
    initial_impressions: Counter[int],
    initial_clicks: Counter[int],
    default_topic_weights: dict[int, float],
    update_counts: bool,
) -> pd.DataFrame:
    article_context = articles[
        [
            "article_id",
            "category_topic_id",
            "first_seen_train_ts",
        ]
    ].copy()
    frame = impressions.merge(article_context, on="article_id", how="left", validate="many_to_one")
    frame = frame.sort_values(
        ["event_ts", "request_id", "candidate_position"],
        kind="stable",
    ).reset_index(drop=True)
    request_profiles, history_lengths = _request_profiles(
        requests,
        {
            int(row.article_id): int(row.category_topic_id)
            for row in article_context.itertuples(index=False)
        },
    )
    impression_counts = Counter(initial_impressions)
    click_counts = Counter(initial_clicks)
    prior_impressions: list[int] = []
    prior_clicks: list[int] = []
    personalized: list[float] = []
    defaults: list[float] = []
    behavior_scores: list[float] = []
    alphas: list[float] = []
    for row in frame.itertuples(index=False):
        article_id = int(row.article_id)
        request_id = str(row.request_id)
        category_topic_id = int(row.category_topic_id)
        prior_impressions.append(impression_counts[article_id])
        prior_clicks.append(click_counts[article_id])
        profile = request_profiles.get(request_id, {})
        personalized.append(profile.get(category_topic_id, 0.0))
        defaults.append(default_topic_weights.get(category_topic_id, 0.0))
        history_length = history_lengths.get(request_id, 0)
        behavior_scores.append(float(history_length))
        alphas.append(0.1 + (history_length / (history_length + 30.0)) * 0.85)
        if update_counts:
            impression_counts[article_id] += 1
            click_counts[article_id] += int(bool(row.clicked))

    prior_impression_array = np.asarray(prior_impressions, dtype=np.float64)
    prior_click_array = np.asarray(prior_clicks, dtype=np.float64)
    hot = prior_click_array * 10.0 + prior_impression_array
    personalized_array = np.asarray(personalized)
    default_array = np.asarray(defaults)
    alpha_array = np.asarray(alphas)
    first_seen = frame["first_seen_train_ts"].fillna(frame["event_ts"]).astype(np.int64)
    age_hours = np.maximum(
        0.0,
        (frame["event_ts"].astype(np.int64) - first_seen) / 3600.0,
    )
    features = pd.DataFrame(
        {
            "user_id": frame["user_id"].astype(np.int64),
            "article_id": frame["article_id"].astype(np.int64),
            "request_id": frame["request_id"].astype(str),
            "event_ts": frame["event_ts"].astype(np.int64),
            "label": frame["clicked"].astype(np.int8),
            "base_score": hot / (hot + 100.0),
            "personalized_topic_score": personalized_array,
            "default_topic_score": default_array,
            "topic_match_score": (
                alpha_array * personalized_array + (1.0 - alpha_array) * default_array
            ),
            "query_recall_boost": 0.0,
            "user_behavior_score": np.asarray(behavior_scores),
            "user_topic_count": [
                len(request_profiles.get(str(request_id), {})) for request_id in frame["request_id"]
            ],
            "article_hot_score": hot,
            "article_click_count": prior_click_array,
            "article_impression_count": prior_impression_array,
            "article_age_hours": age_hours,
            "article_has_picture": 0,
            "article_has_video": 0,
            "article_is_high_value": 0,
            "article_is_editor_recommended": 0,
            "source_is_preferred": 0,
        }
    )
    return features


def _train_als(
    clicked: pd.DataFrame,
    output_dir: Path,
    *,
    factors: int,
    iterations: int,
    normalized_fingerprint: str,
    cutoff_ts: int,
) -> tuple[Any, dict[int, int], dict[int, int], list[int], list[int]]:
    from implicit.als import AlternatingLeastSquares

    user_ids = sorted({int(value) for value in clicked["user_id"]})
    item_ids = sorted({int(value) for value in clicked["article_id"]})
    user_map = {user_id: index for index, user_id in enumerate(user_ids)}
    item_map = {article_id: index for index, article_id in enumerate(item_ids)}
    matrix = csr_matrix(
        (
            np.ones(len(clicked), dtype=np.float32),
            (
                [user_map[int(value)] for value in clicked["user_id"]],
                [item_map[int(value)] for value in clicked["article_id"]],
            ),
        ),
        shape=(len(user_ids), len(item_ids)),
    )
    model = AlternatingLeastSquares(
        factors=factors,
        iterations=iterations,
        regularization=0.05,
        random_state=42,
        use_gpu=False,
    )
    model.fit(matrix)
    user_embeddings = model.user_factors.astype(np.float32)
    item_embeddings = model.item_factors.astype(np.float32)

    import faiss

    index = faiss.IndexFlatIP(item_embeddings.shape[1])
    index.add(item_embeddings)
    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / "als_user_embeddings.npy", user_embeddings)
    np.save(output_dir / "als_item_embeddings.npy", item_embeddings)
    faiss.write_index(index, str(output_dir / "faiss_index.bin"))
    (output_dir / "als_user_id_map.json").write_text(
        json.dumps(
            {
                "index_to_id": user_ids,
                "id_to_index": {str(key): value for key, value in user_map.items()},
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "als_item_id_map.json").write_text(
        json.dumps(
            {
                "index_to_id": item_ids,
                "id_to_index": {str(key): value for key, value in item_map.items()},
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "als_meta.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "dataset": "MIND-small",
                "normalized_fingerprint": normalized_fingerprint,
                "similarity": "inner_product",
                "factors": factors,
                "users": len(user_ids),
                "items": len(item_ids),
                "positive_interactions": int(matrix.nnz),
                "training_cutoff_ts": cutoff_ts,
                "id_map_fingerprint": hashlib.sha256(
                    json.dumps(
                        {"users": user_ids, "items": item_ids},
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return model, user_map, item_map, user_ids, item_ids


def _als_scores(
    frame: pd.DataFrame,
    model: Any,
    user_map: dict[int, int],
    item_map: dict[int, int],
) -> np.ndarray:
    scores = np.zeros(len(frame), dtype=np.float64)
    for index, row in enumerate(frame.itertuples(index=False)):
        user_index = user_map.get(int(row.user_id))
        item_index = item_map.get(int(row.article_id))
        if user_index is not None and item_index is not None:
            scores[index] = float(
                np.dot(model.user_factors[user_index], model.item_factors[item_index])
            )
    return scores


def _build_item_cosine_similarity(
    item_embeddings: np.ndarray,
    item_map: dict[int, int],
) -> ItemSimilarity:
    norms = np.linalg.norm(item_embeddings, axis=1)

    def similarity(left_news_id: str, right_news_id: str) -> float | None:
        left_index = item_map.get(int(left_news_id[1:]))
        right_index = item_map.get(int(right_news_id[1:]))
        if left_index is None or right_index is None:
            return None
        denominator = float(norms[left_index] * norms[right_index])
        if denominator <= 0.0:
            return None
        score = float(
            np.dot(item_embeddings[left_index], item_embeddings[right_index]) / denominator
        )
        return float(np.clip(score, -1.0, 1.0))

    return similarity


def _ranking_metrics(
    frame: pd.DataFrame,
    scores: np.ndarray,
    article_category: dict[int, int],
    *,
    article_topics: dict[int, frozenset[int]] | None = None,
    als_similarity: ItemSimilarity | None = None,
    mmr_similarity_penalty: float | None = None,
    mmr_top_k: int = 10,
) -> dict[str, float | int]:
    if mmr_similarity_penalty is not None and als_similarity is None:
        raise ValueError("MMR metrics require an ALS similarity callback")

    scored = frame[["request_id", "article_id", "label"]].copy()
    scored["score"] = scores
    totals = Counter()
    request_count = 0
    diversity: list[int] = []
    topic_coverage: list[int] = []
    intra_list_similarity: list[float] = []
    for _request_id, rows in scored.groupby("request_id", sort=False):
        positives = int(rows["label"].sum())
        if positives <= 0:
            continue
        base_ordered = rows.sort_values(["score", "article_id"], ascending=[False, True])
        if mmr_similarity_penalty is None:
            ordered = base_ordered
        else:
            candidates = [
                MMRCandidate(
                    news_id=f"N{int(row.article_id)}",
                    relevance=float(row.score),
                    topic_ids=(
                        article_topics.get(int(row.article_id), frozenset())
                        if article_topics is not None
                        else frozenset()
                    ),
                    value=index,
                )
                for index, row in base_ordered.iterrows()
            ]
            selected = rerank_mmr(
                candidates,
                limit=min(mmr_top_k, len(candidates)),
                similarity_penalty=mmr_similarity_penalty,
                als_similarity=als_similarity,
            )
            selected_indices = [row.value for row in selected]
            ordered = pd.concat(
                [
                    base_ordered.loc[selected_indices],
                    base_ordered.drop(index=selected_indices),
                ]
            )
        labels = ordered["label"].astype(int).tolist()
        request_count += 1
        for k in (5, 10):
            top = labels[:k]
            totals[f"recall@{k}"] += sum(top) / positives
            dcg = sum(label / math.log2(index + 2) for index, label in enumerate(top))
            ideal = sum(1.0 / math.log2(index + 2) for index in range(min(positives, k)))
            totals[f"ndcg@{k}"] += dcg / ideal if ideal else 0.0
        first_positive = next(
            (index + 1 for index, label in enumerate(labels) if label),
            None,
        )
        totals["mrr"] += 1.0 / first_positive if first_positive else 0.0
        diversity.append(
            len(
                {
                    article_category.get(int(article_id))
                    for article_id in ordered["article_id"].head(10)
                }
            )
        )
        if article_topics is not None:
            top_article_ids = [int(article_id) for article_id in ordered["article_id"].head(10)]
            topic_coverage.append(
                len(
                    {
                        topic_id
                        for article_id in top_article_ids
                        for topic_id in article_topics.get(article_id, frozenset())
                    }
                )
            )
            if als_similarity is not None:
                pair_similarities = [
                    hybrid_item_similarity(
                        f"N{left_article_id}",
                        article_topics.get(left_article_id, frozenset()),
                        f"N{right_article_id}",
                        article_topics.get(right_article_id, frozenset()),
                        als_similarity=als_similarity,
                    )
                    for left_index, left_article_id in enumerate(top_article_ids)
                    for right_article_id in top_article_ids[left_index + 1 :]
                ]
                intra_list_similarity.append(
                    sum(pair_similarities) / len(pair_similarities) if pair_similarities else 0.0
                )
    if request_count == 0:
        return {"requests": 0, "request_failures": 0}
    metrics: dict[str, float | int] = {
        "requests": request_count,
        "recall@5": round(totals["recall@5"] / request_count, 6),
        "recall@10": round(totals["recall@10"] / request_count, 6),
        "ndcg@5": round(totals["ndcg@5"] / request_count, 6),
        "ndcg@10": round(totals["ndcg@10"] / request_count, 6),
        "mrr": round(totals["mrr"] / request_count, 6),
        "category_diversity@10": round(mean(diversity), 6),
        "request_failures": 0,
    }
    if topic_coverage:
        metrics["topic_coverage@10"] = round(mean(topic_coverage), 6)
    if intra_list_similarity:
        metrics["hybrid_intra_list_similarity@10"] = round(
            sum(intra_list_similarity) / len(intra_list_similarity),
            6,
        )
    return metrics


def mean(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _select_mmr_penalty(
    baseline: dict[str, float | int],
    sweep: list[dict[str, Any]],
    *,
    max_recall_drop: float = MMR_MAX_RECALL_DROP,
) -> dict[str, Any] | None:
    baseline_recall = float(baseline["recall@10"])
    baseline_coverage = float(baseline["topic_coverage@10"])
    baseline_similarity = float(baseline["hybrid_intra_list_similarity@10"])
    eligible = []
    for row in sweep:
        penalty = float(row["similarity_penalty"])
        metrics = row["metrics"]
        recall = float(metrics["recall@10"])
        coverage = float(metrics["topic_coverage@10"])
        similarity = float(metrics["hybrid_intra_list_similarity@10"])
        diversity_improved = (
            similarity < baseline_similarity - 1e-9 or coverage > baseline_coverage + 1e-9
        )
        if penalty > 0.0 and recall >= baseline_recall - max_recall_drop and diversity_improved:
            eligible.append(row)
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda row: (
            float(row["metrics"]["hybrid_intra_list_similarity@10"]),
            -float(row["metrics"]["topic_coverage@10"]),
            -float(row["metrics"]["recall@10"]),
            float(row["similarity_penalty"]),
        ),
    )


def _request_ranking_metric_frame(
    frame: pd.DataFrame,
    scores: np.ndarray,
    article_category: dict[int, int],
) -> pd.DataFrame:
    scored = frame[["request_id", "article_id", "label"]].copy()
    scored["score"] = scores
    records: list[dict[str, float | str]] = []
    for request_id, rows in scored.groupby("request_id", sort=False):
        positives = int(rows["label"].sum())
        if positives <= 0:
            continue
        ordered = rows.sort_values(["score", "article_id"], ascending=[False, True])
        labels = ordered["label"].astype(int).tolist()
        record: dict[str, float | str] = {"request_id": str(request_id)}
        for k in (5, 10):
            top = labels[:k]
            record[f"recall@{k}"] = sum(top) / positives
            dcg = sum(label / math.log2(index + 2) for index, label in enumerate(top))
            ideal = sum(1.0 / math.log2(index + 2) for index in range(min(positives, k)))
            record[f"ndcg@{k}"] = dcg / ideal if ideal else 0.0
        first_positive = next(
            (index + 1 for index, label in enumerate(labels) if label),
            None,
        )
        record["mrr"] = 1.0 / first_positive if first_positive else 0.0
        record["category_diversity@10"] = float(
            len(
                {
                    article_category.get(int(article_id))
                    for article_id in ordered["article_id"].head(10)
                }
            )
        )
        records.append(record)
    return pd.DataFrame.from_records(
        records,
        columns=["request_id", *COMPARISON_RANKING_METRICS],
    )


def _paired_bootstrap_confidence_intervals(
    pointwise: pd.DataFrame,
    lambdarank: pd.DataFrame,
    *,
    iterations: int = PAIRED_BOOTSTRAP_ITERATIONS,
    confidence_level: float = 0.95,
    seed: int = PAIRED_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    if iterations <= 0:
        raise ValueError("Bootstrap iterations must be positive")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("Bootstrap confidence level must be between zero and one")

    paired = pointwise.merge(
        lambdarank,
        on="request_id",
        how="inner",
        suffixes=("_pointwise", "_lambdarank"),
        validate="one_to_one",
    )
    if len(paired) != len(pointwise) or len(paired) != len(lambdarank):
        raise RuntimeError("Objective comparison request metrics are not fully paired")
    if paired.empty:
        raise RuntimeError("Objective comparison has no request metrics to bootstrap")

    deltas = np.column_stack(
        [
            paired[f"{metric}_lambdarank"].to_numpy(dtype=np.float64)
            - paired[f"{metric}_pointwise"].to_numpy(dtype=np.float64)
            for metric in COMPARISON_RANKING_METRICS
        ]
    )
    bootstrap_means = np.empty((iterations, len(COMPARISON_RANKING_METRICS)))
    random = np.random.default_rng(seed)
    batch_size = 64
    for start in range(0, iterations, batch_size):
        stop = min(start + batch_size, iterations)
        indices = random.integers(
            0,
            len(paired),
            size=(stop - start, len(paired)),
        )
        bootstrap_means[start:stop] = deltas[indices].mean(axis=1)

    alpha = (1.0 - confidence_level) / 2.0
    lower_bounds, upper_bounds = np.quantile(
        bootstrap_means,
        [alpha, 1.0 - alpha],
        axis=0,
    )
    delta_intervals: dict[str, dict[str, float | str]] = {}
    for index, metric in enumerate(COMPARISON_RANKING_METRICS):
        lower_bound = float(lower_bounds[index])
        upper_bound = float(upper_bounds[index])
        stable_direction = (
            "increase"
            if lower_bound > 0.0
            else "decrease"
            if upper_bound < 0.0
            else "not_established"
        )
        delta_intervals[metric] = {
            "mean_delta": round(float(deltas[:, index].mean()), 6),
            "lower_bound": round(lower_bound, 6),
            "upper_bound": round(upper_bound, 6),
            "stable_direction": stable_direction,
        }
    return {
        "method": "paired nonparametric bootstrap over requests",
        "request_pairs": len(paired),
        "iterations": iterations,
        "confidence_level": confidence_level,
        "seed": seed,
        "delta_intervals": delta_intervals,
    }


def _comparison_interpretation(
    metric_deltas: dict[str, float],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    intervals = bootstrap["delta_intervals"]
    primary = intervals["ndcg@10"]
    primary_direction = primary["stable_direction"]
    if primary_direction == "increase":
        conclusion = (
            "LambdaRank established a positive paired NDCG@10 delta for this fixed "
            "dataset, feature schema, sample, and hyperparameter configuration."
        )
    elif primary_direction == "decrease":
        conclusion = (
            "LambdaRank established a negative paired NDCG@10 delta for this fixed "
            "dataset, feature schema, sample, and hyperparameter configuration."
        )
    else:
        conclusion = (
            "The paired NDCG@10 interval includes zero, so this experiment does not "
            "establish a stable winner under the fixed configuration."
        )
    tradeoffs = {
        metric: {
            "observed_delta": metric_deltas[metric],
            "observed_direction": (
                "increase"
                if metric_deltas[metric] > 0.0
                else "decrease"
                if metric_deltas[metric] < 0.0
                else "tie"
            ),
            "paired_interval": [
                intervals[metric]["lower_bound"],
                intervals[metric]["upper_bound"],
            ],
            "stable_direction": intervals[metric]["stable_direction"],
        }
        for metric in COMPARISON_RANKING_METRICS
        if metric != "ndcg@10"
    }
    return {
        "primary_metric": "ndcg@10",
        "primary_observed_delta": metric_deltas["ndcg@10"],
        "primary_paired_interval": [
            primary["lower_bound"],
            primary["upper_bound"],
        ],
        "primary_stable_direction": primary_direction,
        "tradeoffs": tradeoffs,
        "conclusion": conclusion,
        "deployment_implication": (
            "Keep the online artifact unchanged; these scores are offline ranking evidence "
            "and LambdaRank output is not a calibrated click probability."
        ),
    }


def _candidate_recall(
    frame: pd.DataFrame,
    model: Any,
    user_map: dict[int, int],
    item_ids: list[int],
    *,
    k: int = 50,
) -> tuple[float, float]:
    import faiss

    item_embeddings = model.item_factors.astype(np.float32)
    index = faiss.IndexFlatIP(item_embeddings.shape[1])
    index.add(item_embeddings)
    relevant_by_request = {
        request_id: set(rows.loc[rows["label"] == 1, "article_id"].astype(int))
        for request_id, rows in frame.groupby("request_id")
    }
    user_by_request = frame.groupby("request_id")["user_id"].first().astype(int).to_dict()
    cache: dict[int, set[int]] = {}
    recalls = []
    known_requests = 0
    for request_id, relevant in relevant_by_request.items():
        if not relevant:
            continue
        user_id = user_by_request[request_id]
        user_index = user_map.get(user_id)
        if user_index is None:
            continue
        known_requests += 1
        if user_id not in cache:
            _distances, indices = index.search(
                model.user_factors[user_index].astype(np.float32).reshape(1, -1),
                min(k, len(item_ids)),
            )
            cache[user_id] = {
                item_ids[int(index_value)] for index_value in indices[0] if index_value >= 0
            }
        recalls.append(len(relevant & cache[user_id]) / len(relevant))
    coverage = known_requests / max(len(relevant_by_request), 1)
    return (mean(recalls), coverage)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate MIND recommendation models.")
    parser.add_argument(
        "--normalized-dir",
        type=Path,
        default=ROOT / "build" / "mind_normalized",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "build" / "mind_models",
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=ROOT / "docs" / "metrics" / "mind_recommendation.json",
    )
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--max-train-requests", type=int, default=20_000)
    parser.add_argument("--max-eval-requests", type=int, default=10_000)
    parser.add_argument("--factors", type=int, default=32)
    parser.add_argument("--als-iterations", type=int, default=10)
    parser.add_argument("--lgb-estimators", type=int, default=120)
    parser.add_argument(
        "--mmr-penalties",
        type=_parse_mmr_penalties,
        default=DEFAULT_MMR_PENALTIES,
        help="Comma-separated MMR similarity penalties to evaluate.",
    )
    parser.add_argument(
        "--compare-lgb-objectives",
        action="store_true",
        help="Compare the pointwise classifier with LambdaRank on the same request split.",
    )
    parser.add_argument(
        "--comparison-output",
        type=Path,
        default=ROOT / "docs" / "metrics" / "mind_lgb_objective_comparison.json",
    )
    args = parser.parse_args()
    started = time.perf_counter()

    normalized_manifest = _load_json(args.normalized_dir / "normalization_manifest.json")
    articles = pq.read_table(args.normalized_dir / "articles.parquet").to_pandas()
    requests = pq.read_table(args.normalized_dir / "requests_train.parquet").to_pandas()
    train_requests, test_requests, cutoff_ts = _request_split(
        requests,
        args.train_ratio,
    )
    train_ids = train_requests["request_id"].astype(str).tolist()
    test_ids = test_requests["request_id"].astype(str).tolist()
    sampled_train = train_requests.tail(args.max_train_requests)
    sampled_test = test_requests.head(args.max_eval_requests)
    sampled_train_ids = sampled_train["request_id"].astype(str).tolist()
    sampled_test_ids = sampled_test["request_id"].astype(str).tolist()
    prefix_ids = train_ids[: max(0, len(train_ids) - len(sampled_train_ids))]

    clicked_all = _read_impressions(
        args.normalized_dir / "impressions_train.parquet",
        train_ids,
        columns=["request_id", "user_id", "article_id", "clicked"],
    )
    clicked_train = clicked_all[clicked_all["clicked"].astype(bool)].copy()
    als_started = time.perf_counter()
    model, user_map, item_map, _user_ids, item_ids = _train_als(
        clicked_train,
        args.output_dir,
        factors=args.factors,
        iterations=args.als_iterations,
        normalized_fingerprint=str(normalized_manifest["normalized_fingerprint"]),
        cutoff_ts=cutoff_ts,
    )
    als_duration = time.perf_counter() - als_started

    prefix = _read_impressions(
        args.normalized_dir / "impressions_train.parquet",
        prefix_ids,
        columns=["article_id", "clicked"],
    )
    prefix_impressions, prefix_clicks = _item_counts(prefix)
    train_impressions = _read_impressions(
        args.normalized_dir / "impressions_train.parquet",
        sampled_train_ids,
        columns=[
            "request_id",
            "user_id",
            "event_ts",
            "candidate_position",
            "article_id",
            "clicked",
        ],
    )
    test_impressions = _read_impressions(
        args.normalized_dir / "impressions_train.parquet",
        sampled_test_ids,
        columns=[
            "request_id",
            "user_id",
            "event_ts",
            "candidate_position",
            "article_id",
            "clicked",
        ],
    )
    train_total_impressions, train_total_clicks = _item_counts(clicked_all)
    article_category = {
        int(row.article_id): int(row.category_topic_id) for row in articles.itertuples(index=False)
    }
    article_topics = {
        int(row.article_id): frozenset(
            {
                int(row.category_topic_id),
                int(row.subcategory_topic_id),
            }
        )
        for row in articles.itertuples(index=False)
    }
    als_item_similarity = _build_item_cosine_similarity(
        model.item_factors.astype(np.float32),
        item_map,
    )
    category_article_counts = Counter(article_category.values())
    total_category_articles = sum(category_article_counts.values()) or 1
    default_topic_weights = {
        int(topic_id): count / total_category_articles
        for topic_id, count in category_article_counts.items()
    }

    train_features = _build_features(
        train_impressions,
        sampled_train,
        articles,
        initial_impressions=prefix_impressions,
        initial_clicks=prefix_clicks,
        default_topic_weights=default_topic_weights,
        update_counts=True,
    )
    test_features = _build_features(
        test_impressions,
        sampled_test,
        articles,
        initial_impressions=train_total_impressions,
        initial_clicks=train_total_clicks,
        default_topic_weights=default_topic_weights,
        update_counts=False,
    )
    feature_columns = list(RANKER_FEATURE_COLUMNS)
    lgb_common_params = {
        "n_estimators": args.lgb_estimators,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_child_samples": 50,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "random_state": 42,
        "verbosity": -1,
    }
    classifier_config = {
        "objective": "binary",
        **lgb_common_params,
    }
    lgb_started = time.perf_counter()
    classifier = lgb.LGBMClassifier(**classifier_config)
    classifier.fit(train_features[feature_columns], train_features["label"])
    lgb_duration = time.perf_counter() - lgb_started
    probabilities = classifier.predict_proba(test_features[feature_columns])[:, 1]
    pointwise = {
        "roc_auc": round(float(roc_auc_score(test_features["label"], probabilities)), 6),
        "pr_auc": round(
            float(average_precision_score(test_features["label"], probabilities)),
            6,
        ),
        "log_loss": round(float(log_loss(test_features["label"], probabilities)), 6),
    }
    ranker_config: dict[str, Any] | None = None
    ranker_duration: float | None = None
    ranker_scores: np.ndarray | None = None
    train_group_sizes: list[int] = []
    test_group_sizes: list[int] = []
    comparison: dict[str, Any] | None = None
    if args.compare_lgb_objectives:
        train_group_sizes = _request_group_sizes(train_features)
        test_group_sizes = _request_group_sizes(test_features)
        ranker_config = {
            "objective": "lambdarank",
            "metric": "ndcg",
            **lgb_common_params,
        }
        ranker_started = time.perf_counter()
        ranker = lgb.LGBMRanker(**ranker_config)
        ranker.fit(
            train_features[feature_columns],
            train_features["label"],
            group=train_group_sizes,
        )
        ranker_duration = time.perf_counter() - ranker_started
        ranker_scores = ranker.predict(test_features[feature_columns])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.output_dir / "lgb_ranker_v1.txt"
    classifier.booster_.save_model(str(model_path))
    data_fingerprint = hashlib.sha256(
        pd.util.hash_pandas_object(
            train_features[
                ["user_id", "article_id", "request_id", "event_ts", "label", *feature_columns]
            ],
            index=False,
        ).values.tobytes()
    ).hexdigest()
    (args.output_dir / "lgb_ranker_v1_meta.json").write_text(
        json.dumps(
            {
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "dataset": "MIND-small",
                "normalized_fingerprint": normalized_manifest["normalized_fingerprint"],
                "features": feature_columns,
                "model_path": model_path.name,
                "data_fingerprint": data_fingerprint,
                "training_cutoff_ts": cutoff_ts,
                "train_requests": len(sampled_train_ids),
                "eval_requests": len(sampled_test_ids),
                "train_samples": len(train_features),
                "eval_samples": len(test_features),
                "pointwise_metrics": pointwise,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    popularity_scores = np.asarray(
        [
            train_total_clicks[int(article_id)] * 10 + train_total_impressions[int(article_id)]
            for article_id in test_features["article_id"]
        ],
        dtype=np.float64,
    )
    manual_scores = (
        test_features["base_score"].to_numpy() + test_features["topic_match_score"].to_numpy()
    )
    als_raw = _als_scores(test_features, model, user_map, item_map)
    als_normalized = 1.0 / (1.0 + np.exp(-np.clip(als_raw, -20.0, 20.0)))
    ranking_metric_context = {
        "article_topics": article_topics,
        "als_similarity": als_item_similarity,
    }
    arms = {
        "popularity": _ranking_metrics(
            test_features,
            popularity_scores,
            article_category,
            **ranking_metric_context,
        ),
        "category_profile_manual": _ranking_metrics(
            test_features,
            manual_scores,
            article_category,
            **ranking_metric_context,
        ),
        "als_recall_manual": _ranking_metrics(
            test_features,
            manual_scores + als_normalized * 0.15,
            article_category,
            **ranking_metric_context,
        ),
        "als_recall_lightgbm": _ranking_metrics(
            test_features,
            probabilities + als_normalized * 0.15,
            article_category,
            **ranking_metric_context,
        ),
        "lightgbm": _ranking_metrics(
            test_features,
            probabilities,
            article_category,
            **ranking_metric_context,
        ),
    }
    mmr_sweep = [
        {
            "similarity_penalty": penalty,
            "metrics": (
                arms["lightgbm"]
                if penalty == 0.0
                else _ranking_metrics(
                    test_features,
                    probabilities,
                    article_category,
                    mmr_similarity_penalty=penalty,
                    **ranking_metric_context,
                )
            ),
        }
        for penalty in args.mmr_penalties
    ]
    baseline_mmr_metrics = arms["lightgbm"]
    for row in mmr_sweep:
        row_metrics = row["metrics"]
        recall_delta = float(row_metrics["recall@10"]) - float(baseline_mmr_metrics["recall@10"])
        coverage_delta = float(row_metrics["topic_coverage@10"]) - float(
            baseline_mmr_metrics["topic_coverage@10"]
        )
        similarity_delta = float(row_metrics["hybrid_intra_list_similarity@10"]) - float(
            baseline_mmr_metrics["hybrid_intra_list_similarity@10"]
        )
        row["recall@10_delta_vs_lightgbm"] = round(recall_delta, 6)
        row["topic_coverage@10_delta_vs_lightgbm"] = round(coverage_delta, 6)
        row["hybrid_intra_list_similarity@10_delta_vs_lightgbm"] = round(
            similarity_delta,
            6,
        )
        row["recall_guardrail_pass"] = recall_delta >= -MMR_MAX_RECALL_DROP
        row["diversity_improved"] = similarity_delta < 0.0 or coverage_delta > 0.0
    selected_mmr = _select_mmr_penalty(arms["lightgbm"], mmr_sweep)
    if selected_mmr is not None:
        arms["lightgbm_mmr"] = {
            **selected_mmr["metrics"],
            "similarity_penalty": selected_mmr["similarity_penalty"],
        }
        mmr_conclusion = (
            "Selected an MMR penalty that improved offline list diversity while keeping "
            f"Recall@10 within {MMR_MAX_RECALL_DROP:.3f} absolute of LightGBM."
        )
    else:
        mmr_conclusion = (
            "No positive MMR penalty both improved the declared diversity metrics and "
            f"kept Recall@10 within {MMR_MAX_RECALL_DROP:.3f} absolute of LightGBM."
        )
    if ranker_scores is not None and ranker_config is not None and ranker_duration is not None:
        ranker_ranking = _ranking_metrics(
            test_features,
            ranker_scores,
            article_category,
        )
        pointwise_ranking = arms["lightgbm"]
        if ranker_ranking["requests"] != pointwise_ranking["requests"]:
            raise RuntimeError("Objective comparison evaluated different request counts")
        pointwise_metrics = {
            metric: float(pointwise_ranking[metric]) for metric in COMPARISON_RANKING_METRICS
        }
        lambdarank_metrics = {
            metric: float(ranker_ranking[metric]) for metric in COMPARISON_RANKING_METRICS
        }
        metric_deltas = {
            metric: round(lambdarank_metrics[metric] - pointwise_metrics[metric], 6)
            for metric in COMPARISON_RANKING_METRICS
        }
        pointwise_request_metrics = _request_ranking_metric_frame(
            test_features,
            probabilities,
            article_category,
        )
        lambdarank_request_metrics = _request_ranking_metric_frame(
            test_features,
            ranker_scores,
            article_category,
        )
        for metric in COMPARISON_RANKING_METRICS:
            if (
                round(float(pointwise_request_metrics[metric].mean()), 6)
                != pointwise_metrics[metric]
            ):
                raise RuntimeError(f"Pointwise per-request {metric} does not match aggregate")
            if (
                round(float(lambdarank_request_metrics[metric].mean()), 6)
                != lambdarank_metrics[metric]
            ):
                raise RuntimeError(f"LambdaRank per-request {metric} does not match aggregate")
        bootstrap = _paired_bootstrap_confidence_intervals(
            pointwise_request_metrics,
            lambdarank_request_metrics,
        )
        comparison = {
            "dataset": "MIND-small",
            "normalized_fingerprint": normalized_manifest["normalized_fingerprint"],
            "data_fingerprint": data_fingerprint,
            "split": {
                "strategy": "global chronological request holdout inside train",
                "train_ratio": args.train_ratio,
                "training_cutoff_ts": cutoff_ts,
                "all_train_requests": len(train_ids),
                "all_test_requests": len(test_ids),
                "sampled_train_requests": len(sampled_train_ids),
                "sampled_test_requests": len(sampled_test_ids),
            },
            "feature_schema": {
                "version": FEATURE_SCHEMA_VERSION,
                "columns": feature_columns,
            },
            "samples": {
                "train_rows": len(train_features),
                "test_rows": len(test_features),
                "train_request_groups": len(train_group_sizes),
                "test_request_groups": len(test_group_sizes),
                "train_group_rows": sum(train_group_sizes),
                "test_group_rows": sum(test_group_sizes),
            },
            "models": {
                "pointwise_classifier": {
                    "class": "LGBMClassifier",
                    "config": classifier_config,
                    "training_seconds": round(lgb_duration, 3),
                },
                "lambdarank": {
                    "class": "LGBMRanker",
                    "config": ranker_config,
                    "training_seconds": round(ranker_duration, 3),
                },
            },
            "ranking_metrics": {
                "pointwise_classifier": {
                    "requests": int(pointwise_ranking["requests"]),
                    **pointwise_metrics,
                },
                "lambdarank": {
                    "requests": int(ranker_ranking["requests"]),
                    **lambdarank_metrics,
                },
            },
            "delta_lambdarank_minus_pointwise": metric_deltas,
            "paired_bootstrap": bootstrap,
            "interpretation": _comparison_interpretation(metric_deltas, bootstrap),
            "comparison_contract": {
                "same_train_features": True,
                "same_test_features": True,
                "same_feature_columns": True,
                "same_sampled_requests": True,
                "shared_hyperparameters": lgb_common_params,
                "test_used_for_training_or_tuning": False,
                "lambdarank_score_semantics": "ranking score, not calibrated click probability",
            },
        }

    candidate_recall, known_request_coverage = _candidate_recall(
        test_features,
        model,
        user_map,
        item_ids,
    )
    for arm_name in ("als_recall_manual", "als_recall_lightgbm"):
        arms[arm_name]["candidate_recall@50"] = round(candidate_recall, 6)
        arms[arm_name]["known_user_request_coverage"] = round(
            known_request_coverage,
            6,
        )

    strongest_baseline = max(
        float(arms["popularity"].get("recall@10", 0.0)),
        float(arms["category_profile_manual"].get("recall@10", 0.0)),
    )
    ml_recall = float(arms["als_recall_lightgbm"].get("recall@10", 0.0))
    lightgbm_recall = float(arms["lightgbm"].get("recall@10", 0.0))
    conclusion = (
        "ALS-adjusted LightGBM exceeded both LightGBM alone and the strongest tested "
        "baseline on sampled chronological Recall@10."
        if ml_recall > strongest_baseline and ml_recall > lightgbm_recall
        else (
            "LightGBM exceeded the strongest tested baseline, but ALS did not add a "
            "measurable sampled Recall@10 gain."
            if lightgbm_recall > strongest_baseline
            else (
                "The staged system made retrieval and ranking measurable; the tested "
                "model did not establish a reliable lift over the strongest baseline."
            )
        )
    )
    dev_requests = pq.read_table(args.normalized_dir / "requests_dev.parquet").to_pandas()
    dev_known_user_coverage = float(dev_requests["user_id"].isin(user_map).mean())
    sampled_dev = dev_requests.head(args.max_eval_requests)
    dev_impressions = _read_impressions(
        args.normalized_dir / "impressions_dev.parquet",
        sampled_dev["request_id"].astype(str).tolist(),
        columns=[
            "request_id",
            "user_id",
            "event_ts",
            "candidate_position",
            "article_id",
            "clicked",
        ],
    )
    dev_features = _build_features(
        dev_impressions,
        sampled_dev,
        articles,
        initial_impressions=train_total_impressions,
        initial_clicks=train_total_clicks,
        default_topic_weights=default_topic_weights,
        update_counts=False,
    )
    dev_manual_scores = (
        dev_features["base_score"].to_numpy() + dev_features["topic_match_score"].to_numpy()
    )
    unknown_mask = ~dev_features["user_id"].isin(user_map).to_numpy()
    dev_unknown = dev_features[unknown_mask].copy()
    dev_unknown_scores = dev_manual_scores[unknown_mask]
    metrics = {
        "dataset": "MIND-small",
        "normalized_fingerprint": normalized_manifest["normalized_fingerprint"],
        "split": {
            "strategy": "global chronological request holdout inside train",
            "training_cutoff_ts": cutoff_ts,
            "all_train_requests": len(train_ids),
            "all_test_requests": len(test_ids),
            "sampled_train_requests": len(sampled_train_ids),
            "sampled_test_requests": len(sampled_test_ids),
            "request_leakage": 0,
        },
        "als": {
            "factors": args.factors,
            "iterations": args.als_iterations,
            "known_user_request_coverage": round(known_request_coverage, 6),
            "official_dev_known_user_coverage": round(dev_known_user_coverage, 6),
            "unknown_user_behavior": "return no collaborative candidates",
        },
        "official_dev_cold_start": {
            "sampled_requests": int(sampled_dev["request_id"].nunique()),
            "unknown_user_requests": int(dev_unknown["request_id"].nunique()),
            "content_category_fallback": _ranking_metrics(
                dev_unknown,
                dev_unknown_scores,
                article_category,
                **ranking_metric_context,
            ),
        },
        "mmr": {
            "formula": "final_score - similarity_penalty * max_similarity_to_selected",
            "baseline_arm": "lightgbm",
            "online_experiment_arm": "lgb_plus_als_plus_search_mmr",
            "max_absolute_recall@10_drop": MMR_MAX_RECALL_DROP,
            "penalty_sweep": mmr_sweep,
            "selected_similarity_penalty": (
                selected_mmr["similarity_penalty"] if selected_mmr is not None else None
            ),
            "selected_metrics": (selected_mmr["metrics"] if selected_mmr is not None else None),
            "evidence_boundary": (
                "MMR is evaluated as a reranker over real exposed candidates. "
                "This does not establish end-to-end candidate recall or online CTR lift."
            ),
            "conclusion": mmr_conclusion,
        },
        "ranking_arms": arms,
        "pointwise": pointwise,
        "system": {
            "als_training_seconds": round(als_duration, 3),
            "lightgbm_training_seconds": round(lgb_duration, 3),
            "total_pipeline_seconds": round(time.perf_counter() - started, 3),
            "artifact_size_bytes": sum(
                path.stat().st_size for path in args.output_dir.iterdir() if path.is_file()
            ),
        },
        "intent_metrics": "docs/metrics/mind_intent_mechanism.json",
        "limitations": [
            "LightGBM uses a deterministic request sample for tractable local training.",
            "MIND has no observed search logs; intent mechanism evidence is reported separately.",
            "Official dev is primarily a cold-start surface and is not presented as a known-user ALS benchmark.",
            "Article age uses first appearance in selected MIND impressions, not publication time.",
        ],
        "conclusion": conclusion,
    }
    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_output.write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if comparison is not None:
        args.comparison_output.parent.mkdir(parents=True, exist_ok=True)
        args.comparison_output.write_text(
            json.dumps(comparison, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        f"wrote {args.metrics_output}; Recall@10={ml_recall:.6f}; "
        f"known coverage={known_request_coverage:.4f}"
    )
    print(
        "MMR selected penalty="
        + (
            f"{float(selected_mmr['similarity_penalty']):.2f}"
            if selected_mmr is not None
            else "none"
        )
    )
    if comparison is not None:
        print(f"wrote {args.comparison_output}")


if __name__ == "__main__":
    main()
