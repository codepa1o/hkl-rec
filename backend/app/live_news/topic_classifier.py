from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
TAXONOMY_PATH = ROOT / "config/live_topics.json"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
GENERAL_TOPIC = 1000014


def normalize_input(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def input_hash(title: str, summary: str) -> str:
    return hashlib.sha256(
        (normalize_input(title) + "\n" + normalize_input(summary)).encode("utf-8")
    ).hexdigest()


def load_taxonomy() -> dict[str, Any]:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@dataclass(frozen=True)
class TopicAssignment:
    topic_id: int
    score: float
    semantic_score: float
    lexical_score: float


class TopicClassifier:
    def __init__(self, *, model_dir: Path | None = None, encoder: Any = None) -> None:
        self.config = load_taxonomy()
        self.version = (
            self.config["version"]
            + ":"
            + hashlib.sha256(TAXONOMY_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]
        )
        self.topics = self.config["topics"][:-1]
        if encoder is None:
            directory = model_dir or ROOT / "build/live_topic_model"
            manifest = json.loads((directory / "model_manifest.json").read_text())
            if manifest["revision"] != MODEL_REVISION:
                raise ValueError("Live topic model revision mismatch")
            required = {
                "model.safetensors",
                "config.json",
                "tokenizer.json",
                "modules.json",
                "1_Pooling/config.json",
            }
            if not required.issubset(manifest["sha256"]):
                raise ValueError("Live topic model manifest is incomplete")
            for name, expected in manifest["sha256"].items():
                if not (directory / name).resolve().is_relative_to(directory.resolve()):
                    raise ValueError("Invalid model manifest path")
                with (directory / name).open("rb") as handle:
                    if hashlib.file_digest(handle, "sha256").hexdigest() != expected:
                        raise ValueError(f"Live topic model checksum mismatch: {name}")
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["USE_TF"] = "0"
            os.environ["USE_TORCH"] = "1"
            import torch
            from sentence_transformers import SentenceTransformer

            torch.set_num_threads(2)
            torch.use_deterministic_algorithms(True)
            encoder = SentenceTransformer(str(directory), device="cpu", local_files_only=True)
            encoder.max_seq_length = 256
            encoder.eval()
        self.encoder = encoder
        descriptions = ["query: " + text for t in self.topics for text in t["descriptions"]]
        vectors = self._encode(descriptions).reshape(len(self.topics), 2, -1).mean(axis=1)
        self.prototypes = self._unit(vectors)

    @staticmethod
    def _unit(vectors: Any) -> Any:
        return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)

    def _encode(self, texts: list[str]) -> Any:
        return self._unit(
            np.asarray(
                self.encoder.encode(
                    texts,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                    batch_size=16,
                ),
                dtype=np.float32,
            )
        )

    def classify_many(self, articles: list[tuple[str, str]]) -> list[list[TopicAssignment]]:
        if not articles:
            return []
        cleaned = [(normalize_input(t), normalize_input(s)) for t, s in articles]
        vectors = self._encode(["query: " + text for row in cleaned for text in row])
        result = []
        for index, (title, summary) in enumerate(cleaned):
            weight = self.config["title_weight"] if summary else 1.0
            similarity = (
                weight * vectors[2 * index] + (1 - weight) * vectors[2 * index + 1]
            ) @ self.prototypes.T
            text = (title + " " + summary).casefold()
            assignments = []
            for topic, semantic in zip(self.topics, similarity, strict=True):
                hits = sum(
                    bool(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text))
                    if word.isascii()
                    else word in text
                    for word in topic["keywords"]
                )
                lexical = min(1.0, hits / 2)
                semantic = min(1.0, max(0.0, float(semantic)))
                score = (
                    self.config["semantic_weight"] * semantic
                    + (1 - self.config["semantic_weight"]) * lexical
                )
                assignments.append(
                    TopicAssignment(topic["topic_id"], round(score, 6), round(semantic, 6), lexical)
                )
            assignments.sort(key=lambda x: (-x.score, x.topic_id))
            best = assignments[0].score
            selected = [
                x
                for x in assignments
                if x.score >= self.config["threshold"]
                and best - x.score <= self.config["secondary_margin"]
            ][: self.config["maximum_topics"]]
            if not title or not selected:
                selected = [TopicAssignment(GENERAL_TOPIC, 0.0, 0.0, 0.0)]
            result.append(selected)
        return result
