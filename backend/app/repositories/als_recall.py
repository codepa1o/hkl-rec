"""ALS + FAISS 召回通道——为信息流候选项执行在线 ANN 检索。

启动时加载预训练的 ALS 嵌入和 FAISS 索引。冷启动用户（没有交互历史，
因此也没有 ALS 嵌入）返回空结果；调用方应回退到基于内容的召回通道。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from backend.app.config import environment_value


class ALSRecall:
    def __init__(self, build_dir: str | None = None) -> None:
        base = Path(build_dir or environment_value("NEWSREC_MODEL_DIR") or "build/mind_models")
        self._index_path = base / "faiss_index.bin"
        self._user_emb_path = base / "als_user_embeddings.npy"
        self._item_emb_path = base / "als_item_embeddings.npy"
        self._user_map_path = base / "als_user_id_map.json"
        self._item_map_path = base / "als_item_id_map.json"
        self._meta_path = base / "als_meta.json"

        self._user_id_map: dict[int, int] = {}
        self._item_id_map: dict[int, int] = {}
        self._index_to_item: dict[int, int] = {}
        self._item_norms: np.ndarray | None = None
        self._loaded = False
        self._signature: tuple[int, ...] | None = None
        self._metadata: dict[str, object] = {}

    def _ensure_loaded(self) -> None:
        required_paths = (
            self._index_path,
            self._user_emb_path,
            self._item_emb_path,
            self._user_map_path,
            self._item_map_path,
            self._meta_path,
        )
        if not all(path.exists() for path in required_paths):
            return  # 尚未训练，所有调用均不执行任何操作
        signature = tuple(path.stat().st_mtime_ns for path in required_paths)
        if self._loaded and self._signature == signature:
            return

        import faiss

        metadata = json.loads(self._meta_path.read_text(encoding="utf-8"))
        if metadata.get("similarity") != "inner_product":
            return
        self._index = faiss.read_index(str(self._index_path))
        self._user_embeddings = np.load(str(self._user_emb_path))
        self._item_embeddings = np.load(str(self._item_emb_path))

        user_data = json.loads(self._user_map_path.read_text(encoding="utf-8"))
        self._user_id_map = user_data["id_to_index"]
        self._user_id_map = {int(k): v for k, v in self._user_id_map.items()}

        item_data = json.loads(self._item_map_path.read_text(encoding="utf-8"))
        self._index_to_item = {i: int(aid) for i, aid in enumerate(item_data["index_to_id"])}
        self._item_id_map = {
            int(answer_id): int(index) for answer_id, index in item_data["id_to_index"].items()
        }
        self._item_norms = np.linalg.norm(self._item_embeddings, axis=1)

        self._metadata = metadata
        self._signature = signature
        self._loaded = True

    def metadata(self) -> dict[str, object]:
        self._ensure_loaded()
        return dict(self._metadata)

    def get_candidates(
        self,
        user_id: int,
        k: int = 200,
    ) -> list[tuple[int, float]]:
        """返回指定用户的前 k 个 `(answer_id, inner_product_score)`。

        对冷启动用户或尚未构建 ALS 制品的情况返回空列表。
        """
        self._ensure_loaded()
        if not self._loaded or user_id not in self._user_id_map:
            return []

        row_idx = self._user_id_map[user_id]
        user_vec = self._user_embeddings[row_idx].astype("float32").reshape(1, -1)
        distances, indices = self._index.search(user_vec, k)

        results: list[tuple[int, float]] = []
        for dist, idx in zip(distances[0], indices[0], strict=False):
            if idx == -1:
                continue
            answer_id = self._index_to_item.get(int(idx))
            if answer_id is not None:
                results.append((answer_id, float(dist)))
        return results

    def item_cosine_similarity(
        self,
        left_answer_id: int,
        right_answer_id: int,
    ) -> float | None:
        if not self._loaded:
            self._ensure_loaded()
        if not self._loaded or self._item_norms is None:
            return None

        left_index = self._item_id_map.get(left_answer_id)
        right_index = self._item_id_map.get(right_answer_id)
        if left_index is None or right_index is None:
            return None

        denominator = float(self._item_norms[left_index] * self._item_norms[right_index])
        if denominator <= 0.0:
            return None
        similarity = float(
            np.dot(
                self._item_embeddings[left_index],
                self._item_embeddings[right_index],
            )
            / denominator
        )
        return float(np.clip(similarity, -1.0, 1.0))


_ALS: ALSRecall | None = None


def get_als_recall(build_dir: str | None = None) -> ALSRecall:
    global _ALS
    if _ALS is None:
        _ALS = ALSRecall(build_dir)
    return _ALS
