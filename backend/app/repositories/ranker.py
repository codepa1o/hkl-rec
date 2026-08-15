"""LightGBM 在线排序器——加载模型并批量为候选项评分。

单例模型在首次调用时加载；只读推理是线程安全的。

在 postgres.py 评分循环中的用法：
    from backend.app.repositories.ranker import build_feature_vector, score_candidates

    features = [build_feature_vector(...) for candidate in candidates]
    scores = score_candidates(features)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import lightgbm as lgb

from backend.app.config import environment_value

_MODEL: lgb.Booster | None = None
_FEATURE_ORDER: list[str] = []
_METADATA: dict[str, Any] = {}
_MODEL_SIGNATURE: tuple[int, int] | None = None
FEATURE_SCHEMA_VERSION = 4
RANKER_FEATURE_COLUMNS = (
    "base_score",
    "personalized_topic_score",
    "default_topic_score",
    "topic_match_score",
    "query_recall_boost",
    "user_behavior_score",
    "user_topic_count",
    "article_hot_score",
    "article_click_count",
    "article_impression_count",
    "article_age_hours",
    "article_has_picture",
    "article_has_video",
    "article_is_high_value",
    "article_is_editor_recommended",
    "source_is_preferred",
)


def load_model(model_dir: str | None = None) -> lgb.Booster | None:
    global _MODEL, _FEATURE_ORDER, _METADATA, _MODEL_SIGNATURE
    base = Path(model_dir or environment_value("NEWSREC_MODEL_DIR") or "build/mind_models")
    model_path = base / "lgb_ranker_v1.txt"
    meta_path = base / "lgb_ranker_v1_meta.json"

    if not model_path.exists() or not meta_path.exists():
        return None  # 模型尚未训练，调用方应使用回退方案

    signature = (model_path.stat().st_mtime_ns, meta_path.stat().st_mtime_ns)
    if _MODEL is not None and signature == _MODEL_SIGNATURE:
        return _MODEL

    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    features = metadata.get("features", [])
    if metadata.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        return None
    if features != list(RANKER_FEATURE_COLUMNS):
        return None

    _MODEL = lgb.Booster(model_file=str(model_path))
    _FEATURE_ORDER = features
    _METADATA = metadata
    _MODEL_SIGNATURE = signature
    return _MODEL


def loaded_model_metadata() -> dict[str, Any]:
    load_model()
    return dict(_METADATA)


def score_candidates(feature_dicts: list[dict[str, float]]) -> list[float] | None:
    """返回每个候选记录的预测点击概率。

    模型文件尚未训练时返回 None；调用方应回退到手工评分。
    """
    model = load_model()
    if model is None:
        return None

    if not feature_dicts:
        return []

    if _FEATURE_ORDER:
        # 严格保持与训练时一致的列顺序
        rows = [[row.get(col, 0.0) for col in _FEATURE_ORDER] for row in feature_dicts]
    else:
        cols = list(feature_dicts[0].keys())
        rows = [[row.get(col, 0.0) for col in cols] for row in feature_dicts]

    raw_scores = model.predict(rows)
    return [float(score) for score in raw_scores]


def build_feature_dict(
    *,
    article_row: dict[str, Any],
    topic_ids: set[int],
    topic_weight_map: dict[int, float],
    default_topic_weight_map: dict[int, float],
    query_topic_scores: dict[int, float],
    alpha: float,
    max_hot_score: float,
    now_ts: float | None = None,
    user_behavior_score: float = 0.0,
    user_topic_count: int = 0,
    article_hot_score: float | None = None,
    article_click_count: int | None = None,
    article_impression_count: int | None = None,
) -> dict[str, float]:
    """构建一个与训练特征列匹配的特征字典。

    此处与规范化 MIND 的特征构建器保持一致，确保在线推理与训练对齐。
    """
    import time as _time

    hot = (
        float(article_hot_score)
        if article_hot_score is not None
        else float(article_row.get("hot_score") or 0)
    )
    personalized = sum(topic_weight_map.get(tid, 0.0) for tid in topic_ids)
    default_ts = sum(default_topic_weight_map.get(tid, 0.0) for tid in topic_ids)
    topic_match = alpha * personalized + (1.0 - alpha) * default_ts
    query_boost = sum(query_topic_scores.get(tid, 0.0) for tid in topic_ids)
    create_ts = int(article_row.get("create_ts") or 0)
    if now_ts is None:
        now_ts = _time.time()
    age_hours = max(0.0, (now_ts - create_ts) / 3600.0) if create_ts > 0 else 0.0

    return {
        "base_score": round(hot / (hot + 100.0), 6) if hot > 0 else 0.0,
        "personalized_topic_score": round(personalized, 6),
        "default_topic_score": round(default_ts, 6),
        "topic_match_score": round(topic_match, 6),
        "query_recall_boost": round(query_boost, 6),
        "user_behavior_score": round(user_behavior_score, 6),
        "user_topic_count": int(user_topic_count),
        "article_hot_score": round(hot, 6),
        "article_click_count": (
            int(article_click_count)
            if article_click_count is not None
            else int(article_row.get("click_count") or 0)
        ),
        "article_impression_count": (
            int(article_impression_count)
            if article_impression_count is not None
            else int(article_row.get("impression_count") or 0)
        ),
        "article_age_hours": round(age_hours, 2),
        "article_has_picture": int(article_row.get("has_picture") or 0),
        "article_has_video": int(article_row.get("has_video") or 0),
        "article_is_high_value": int(article_row.get("is_high_value") or 0),
        "article_is_editor_recommended": int(article_row.get("is_editor_recommended") or 0),
        "source_is_preferred": int(article_row.get("is_excellent_answerer") or 0),
    }
