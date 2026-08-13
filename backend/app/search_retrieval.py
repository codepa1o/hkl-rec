from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")


@dataclass(frozen=True)
class SearchDocument:
    article_id: int
    headline: str
    abstract: str
    topic_ids: tuple[int, ...] = ()
    category: str = ""
    subcategory: str = ""


@dataclass(frozen=True)
class RetrievalHit:
    article_id: int
    score: float
    rank: int


@dataclass(frozen=True)
class HybridHit:
    article_id: int
    bm25_score: float
    dense_score: float
    fusion_score: float
    bm25_rank: int | None
    dense_rank: int | None


@dataclass(frozen=True)
class HybridSearchConfig:
    bm25_weight: float = 1.0
    dense_weight: float = 1.0
    rrf_k: int = 60
    candidate_k: int = 50
    min_dense_score: float = 0.4
    min_dense_score_with_bm25: float = 0.28
    min_bm25_score: float = 20.0
    min_fusion_margin: float = 0.002

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> HybridSearchConfig:
        return cls(
            bm25_weight=float(value.get("bm25_weight", 1.0)),
            dense_weight=float(value.get("dense_weight", 1.0)),
            rrf_k=int(value.get("rrf_k", 60)),
            candidate_k=int(value.get("candidate_k", 50)),
            min_dense_score=float(value.get("min_dense_score", 0.4)),
            min_dense_score_with_bm25=float(value.get("min_dense_score_with_bm25", 0.28)),
            min_bm25_score=float(value.get("min_bm25_score", 20.0)),
            min_fusion_margin=float(value.get("min_fusion_margin", 0.002)),
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "bm25_weight": self.bm25_weight,
            "dense_weight": self.dense_weight,
            "rrf_k": self.rrf_k,
            "candidate_k": self.candidate_k,
            "min_dense_score": self.min_dense_score,
            "min_dense_score_with_bm25": self.min_dense_score_with_bm25,
            "min_bm25_score": self.min_bm25_score,
            "min_fusion_margin": self.min_fusion_margin,
        }


@dataclass(frozen=True)
class HybridSearchResult:
    accepted: bool
    hits: tuple[HybridHit, ...]
    top_dense_score: float
    top_bm25_score: float
    fusion_margin: float


@dataclass(frozen=True)
class LexicalResolution:
    query_key: str
    source: str
    hits: tuple[RetrievalHit, ...]


class SearchEncoder(Protocol):
    def encode(
        self,
        sentences: str | list[str],
        *,
        batch_size: int = 32,
        show_progress_bar: bool = False,
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = True,
    ) -> Any: ...


class SearchArtifactError(RuntimeError):
    pass


def normalize_search_text(value: str) -> str:
    return " ".join(value.lower().split())


def tokenize_search_text(value: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_search_text(value))


def lexical_search_terms(query_text: str) -> list[str]:
    normalized = normalize_search_text(query_text)
    tokens = [token for token in normalized.split() if len(token) >= 3][:5]
    return list(dict.fromkeys(term for term in (normalized, *tokens) if len(term) >= 3))


def lexical_document_score(document: SearchDocument, query_text: str) -> float:
    terms = lexical_search_terms(query_text)
    if not terms:
        return 0.0
    headline = normalize_search_text(document.headline)
    abstract = normalize_search_text(document.abstract)
    score = sum(
        (2.0 if term in headline else 0.0) + (1.0 if term in abstract else 0.0) for term in terms
    )
    return score / (3.0 * len(terms))


def lexical_retrieve(
    documents: list[SearchDocument],
    query_text: str,
    *,
    limit: int,
) -> list[RetrievalHit]:
    scored = [
        (lexical_document_score(document, query_text), document.article_id)
        for document in documents
    ]
    ordered = sorted(
        ((score, article_id) for score, article_id in scored if score > 0),
        key=lambda row: (-row[0], row[1]),
    )
    return [
        RetrievalHit(article_id=article_id, score=score, rank=rank)
        for rank, (score, article_id) in enumerate(ordered[:limit], start=1)
    ]


def document_embedding_text(document: SearchDocument) -> str:
    return " ".join(
        part
        for part in (
            f"title: {document.headline.strip()}" if document.headline.strip() else "",
            f"abstract: {document.abstract.strip()}" if document.abstract.strip() else "",
            f"category: {document.category.strip()}" if document.category.strip() else "",
            (
                f"subcategory: {document.subcategory.strip()}"
                if document.subcategory.strip()
                else ""
            ),
        )
        if part
    )


def search_document_to_dict(document: SearchDocument) -> dict[str, object]:
    return {
        "article_id": document.article_id,
        "headline": document.headline,
        "abstract": document.abstract,
        "topic_ids": list(document.topic_ids),
        "category": document.category,
        "subcategory": document.subcategory,
    }


def search_document_from_dict(value: dict[str, Any]) -> SearchDocument:
    return SearchDocument(
        article_id=int(value["article_id"]),
        headline=str(value.get("headline") or ""),
        abstract=str(value.get("abstract") or ""),
        topic_ids=tuple(int(topic_id) for topic_id in value.get("topic_ids", [])),
        category=str(value.get("category") or ""),
        subcategory=str(value.get("subcategory") or ""),
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_search_documents(path: Path, documents: list[SearchDocument]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for document in documents:
            handle.write(json.dumps(search_document_to_dict(document), sort_keys=True))
            handle.write("\n")


def load_search_documents(path: Path) -> list[SearchDocument]:
    return [
        search_document_from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class LexicalBaselineIndex:
    """混合搜索启用前 MySQL 自由文本搜索路径的离线等价实现。"""

    def __init__(self, documents: list[SearchDocument]) -> None:
        self._documents = tuple(documents)
        aliases: dict[str, set[int]] = defaultdict(set)
        self._topic_documents: dict[int, list[SearchDocument]] = defaultdict(list)
        for document in documents:
            topic_aliases = (
                (document.category, document.topic_ids[0] if document.topic_ids else None),
                (
                    document.subcategory,
                    document.topic_ids[1] if len(document.topic_ids) > 1 else None,
                ),
            )
            for alias, topic_id in topic_aliases:
                normalized_alias = normalize_search_text(alias)
                if normalized_alias and topic_id is not None:
                    aliases[normalized_alias].add(topic_id)
            for topic_id in document.topic_ids:
                self._topic_documents[topic_id].append(document)
        self._aliases = {alias: tuple(sorted(topic_ids)) for alias, topic_ids in aliases.items()}

    def _resolve_alias(
        self,
        query_text: str,
        *,
        exact_only: bool = False,
    ) -> tuple[int, str] | None:
        normalized = normalize_search_text(query_text)
        passes = [
            ("display_exact", lambda alias: alias == normalized),
            ("display_prefix", lambda alias: alias.startswith(normalized)),
            ("display_contains", lambda alias: normalized in alias),
        ]
        if exact_only:
            passes = passes[:1]
        for source, predicate in passes:
            topic_ids = [
                topic_id
                for alias, alias_topic_ids in self._aliases.items()
                if predicate(alias)
                for topic_id in alias_topic_ids
            ]
            if topic_ids:
                return min(topic_ids), source
        return None

    def search_exact_alias(
        self,
        query_text: str,
        *,
        limit: int,
    ) -> LexicalResolution | None:
        alias_resolution = self._resolve_alias(query_text, exact_only=True)
        if alias_resolution is None:
            return None
        topic_id, source = alias_resolution
        hits = tuple(
            RetrievalHit(article_id=document.article_id, score=1.0, rank=rank)
            for rank, document in enumerate(
                sorted(
                    self._topic_documents.get(topic_id, []),
                    key=lambda document: document.article_id,
                )[:limit],
                start=1,
            )
        )
        return LexicalResolution(query_key=str(topic_id), source=source, hits=hits)

    def search(self, query_text: str, *, limit: int) -> LexicalResolution | None:
        alias_resolution = self._resolve_alias(query_text)
        lexical_hits = lexical_retrieve(
            list(self._documents),
            query_text,
            limit=max(limit * 20, 50),
        )
        if alias_resolution is not None:
            topic_id, source = alias_resolution
        else:
            if not lexical_hits:
                return None
            matching_article_ids = {hit.article_id for hit in lexical_hits}
            topic_ids = [
                topic_id
                for document in self._documents
                if document.article_id in matching_article_ids
                for topic_id in document.topic_ids
            ]
            if not topic_ids:
                return None
            topic_id = min(topic_ids)
            source = "article_text"

        scores = {document.article_id: 1.0 for document in self._topic_documents.get(topic_id, [])}
        for hit in lexical_hits:
            scores[hit.article_id] = max(scores.get(hit.article_id, 0.0), hit.score)
        ordered = sorted(scores.items(), key=lambda row: (-row[1], row[0]))
        hits = tuple(
            RetrievalHit(article_id=article_id, score=score, rank=rank)
            for rank, (article_id, score) in enumerate(ordered[:limit], start=1)
        )
        return LexicalResolution(query_key=str(topic_id), source=source, hits=hits)


class BM25Index:
    def __init__(
        self,
        documents: list[SearchDocument],
        *,
        k1: float = 1.5,
        b: float = 0.75,
        title_weight: int = 2,
    ) -> None:
        if k1 <= 0:
            raise ValueError("k1 must be positive")
        if not 0 <= b <= 1:
            raise ValueError("b must be between 0 and 1")
        if title_weight < 1:
            raise ValueError("title_weight must be at least 1")

        self._documents = tuple(documents)
        self._k1 = k1
        self._b = b
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self._document_lengths: list[int] = []
        document_frequencies: Counter[str] = Counter()

        for document_index, document in enumerate(documents):
            title_tokens = tokenize_search_text(document.headline)
            tokens = [
                *(title_tokens * title_weight),
                *tokenize_search_text(document.abstract),
                *tokenize_search_text(document.category),
                *tokenize_search_text(document.subcategory),
            ]
            term_frequencies = Counter(tokens)
            self._document_lengths.append(len(tokens))
            document_frequencies.update(term_frequencies.keys())
            for term, frequency in term_frequencies.items():
                self._postings[term].append((document_index, frequency))

        document_count = len(documents)
        self._average_document_length = (
            sum(self._document_lengths) / document_count if document_count else 0.0
        )
        self._idf = {
            term: math.log(1.0 + (document_count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequencies.items()
        }

    def search(self, query_text: str, *, limit: int) -> list[RetrievalHit]:
        if limit <= 0 or not self._documents:
            return []
        query_terms = list(dict.fromkeys(tokenize_search_text(query_text)))
        scores: dict[int, float] = defaultdict(float)
        average_length = max(self._average_document_length, 1.0)
        for term in query_terms:
            idf = self._idf.get(term)
            if idf is None:
                continue
            for document_index, frequency in self._postings.get(term, []):
                document_length = self._document_lengths[document_index]
                denominator = frequency + self._k1 * (
                    1.0 - self._b + self._b * document_length / average_length
                )
                scores[document_index] += idf * frequency * (self._k1 + 1.0) / denominator

        ordered = sorted(
            scores.items(),
            key=lambda row: (-row[1], self._documents[row[0]].article_id),
        )
        return [
            RetrievalHit(
                article_id=self._documents[document_index].article_id,
                score=score,
                rank=rank,
            )
            for rank, (document_index, score) in enumerate(ordered[:limit], start=1)
        ]


class DenseSearchIndex:
    def __init__(
        self,
        documents: list[SearchDocument],
        *,
        index: Any,
        encoder: SearchEncoder,
        metadata: dict[str, Any],
    ) -> None:
        self._documents = tuple(documents)
        self._index = index
        self._encoder = encoder
        self._metadata = dict(metadata)
        index_size = int(getattr(index, "ntotal", -1))
        if index_size != len(documents):
            raise SearchArtifactError(
                f"dense index contains {index_size} rows for {len(documents)} documents"
            )

    @property
    def documents(self) -> list[SearchDocument]:
        return list(self._documents)

    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    def search(self, query_text: str, *, limit: int) -> list[RetrievalHit]:
        if limit <= 0:
            return []
        vector = np.asarray(
            self._encoder.encode(
                query_text,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            ),
            dtype=np.float32,
        ).reshape(1, -1)
        distances, indices = self._index.search(vector, min(limit, len(self._documents)))
        hits: list[RetrievalHit] = []
        for rank, (distance, index_value) in enumerate(
            zip(distances[0], indices[0], strict=True),
            start=1,
        ):
            if int(index_value) < 0:
                continue
            hits.append(
                RetrievalHit(
                    article_id=self._documents[int(index_value)].article_id,
                    score=float(distance),
                    rank=rank,
                )
            )
        return hits

    @classmethod
    def load(
        cls,
        artifact_dir: Path,
        *,
        expected_source_fingerprint: str | None = None,
        encoder_factory: Callable[[str, str], SearchEncoder] | None = None,
    ) -> DenseSearchIndex:
        documents_path = artifact_dir / "documents.jsonl"
        id_map_path = artifact_dir / "article_id_map.json"
        index_path = artifact_dir / "dense.faiss"
        metadata_path = artifact_dir / "metadata.json"
        required_paths = (documents_path, id_map_path, index_path, metadata_path)
        missing = [path.name for path in required_paths if not path.is_file()]
        if missing:
            raise SearchArtifactError(f"missing search artifact files: {', '.join(missing)}")

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if int(metadata.get("schema_version", 0)) != 1:
            raise SearchArtifactError("unsupported search artifact schema_version")
        if metadata.get("similarity") != "cosine_via_normalized_inner_product":
            raise SearchArtifactError("search artifact similarity must be normalized cosine")
        if (
            expected_source_fingerprint is not None
            and metadata.get("source_fingerprint") != expected_source_fingerprint
        ):
            raise SearchArtifactError("search artifact source fingerprint mismatch")

        expected_hashes = metadata.get("file_sha256")
        if not isinstance(expected_hashes, dict):
            raise SearchArtifactError("search artifact file_sha256 metadata is missing")
        for path in (documents_path, id_map_path, index_path):
            expected_hash = expected_hashes.get(path.name)
            if not expected_hash or file_sha256(path) != expected_hash:
                raise SearchArtifactError(f"search artifact hash mismatch: {path.name}")

        documents = load_search_documents(documents_path)
        id_map = json.loads(id_map_path.read_text(encoding="utf-8"))
        article_ids = [int(value) for value in id_map.get("index_to_article_id", [])]
        if article_ids != [document.article_id for document in documents]:
            raise SearchArtifactError("search artifact article ID map does not match documents")
        if int(metadata.get("document_count", -1)) != len(documents):
            raise SearchArtifactError("search artifact document_count mismatch")

        import faiss

        index = faiss.read_index(str(index_path))
        model_id = str(metadata.get("model_id") or "")
        model_revision = str(metadata.get("model_revision") or "")
        if not model_id or not model_revision:
            raise SearchArtifactError("search artifact model identity is missing")
        if encoder_factory is None:
            encoder_factory = _default_encoder_factory
        encoder = encoder_factory(model_id, model_revision)
        return cls(
            documents,
            index=index,
            encoder=encoder,
            metadata=metadata,
        )


def _default_encoder_factory(model_id: str, model_revision: str) -> SearchEncoder:
    from huggingface_hub.errors import LocalEntryNotFoundError
    from sentence_transformers import SentenceTransformer

    try:
        return cast(
            SearchEncoder,
            SentenceTransformer(
                model_id,
                revision=model_revision,
                local_files_only=True,
            ),
        )
    except (LocalEntryNotFoundError, OSError, ValueError) as exc:
        raise SearchArtifactError(
            f"encoder {model_id}@{model_revision} is not available locally: {exc}"
        ) from exc


class HybridSearchIndex:
    def __init__(
        self,
        dense_index: DenseSearchIndex,
        *,
        config: HybridSearchConfig,
    ) -> None:
        self._dense = dense_index
        self._bm25 = BM25Index(dense_index.documents)
        self._config = config

    @classmethod
    def load(
        cls,
        artifact_dir: Path,
        *,
        expected_source_fingerprint: str | None = None,
        encoder_factory: Callable[[str, str], SearchEncoder] | None = None,
    ) -> HybridSearchIndex:
        dense = DenseSearchIndex.load(
            artifact_dir,
            expected_source_fingerprint=expected_source_fingerprint,
            encoder_factory=encoder_factory,
        )
        config_value = dense.metadata().get("hybrid_config")
        if not isinstance(config_value, dict):
            raise SearchArtifactError("search artifact hybrid_config is missing")
        return cls(dense, config=HybridSearchConfig.from_dict(config_value))

    def metadata(self) -> dict[str, Any]:
        return self._dense.metadata()

    def search(self, query_text: str, *, limit: int) -> HybridSearchResult:
        candidate_k = max(limit, self._config.candidate_k)
        bm25_hits = self._bm25.search(query_text, limit=candidate_k)
        dense_hits = self._dense.search(query_text, limit=candidate_k)
        return build_hybrid_search_result(
            bm25_hits,
            dense_hits,
            config=self._config,
            limit=limit,
        )


def build_hybrid_search_result(
    bm25_hits: list[RetrievalHit],
    dense_hits: list[RetrievalHit],
    *,
    config: HybridSearchConfig,
    limit: int,
) -> HybridSearchResult:
    hits = reciprocal_rank_fusion(
        bm25_hits,
        dense_hits,
        bm25_weight=config.bm25_weight,
        dense_weight=config.dense_weight,
        rrf_k=config.rrf_k,
        limit=limit,
    )
    if not hits:
        return HybridSearchResult(
            accepted=False,
            hits=(),
            top_dense_score=0.0,
            top_bm25_score=0.0,
            fusion_margin=0.0,
        )
    top = hits[0]
    second_score = hits[1].fusion_score if len(hits) > 1 else 0.0
    fusion_margin = top.fusion_score - second_score
    top_dense_score = dense_hits[0].score if dense_hits else 0.0
    top_bm25_score = bm25_hits[0].score if bm25_hits else 0.0
    accepted = top_dense_score >= config.min_dense_score or (
        top_dense_score >= config.min_dense_score_with_bm25
        and top_bm25_score >= config.min_bm25_score
        and fusion_margin >= config.min_fusion_margin
    )
    return HybridSearchResult(
        accepted=accepted,
        hits=tuple(hits),
        top_dense_score=top_dense_score,
        top_bm25_score=top_bm25_score,
        fusion_margin=fusion_margin,
    )


@lru_cache(maxsize=4)
def _load_hybrid_search_index_cached(
    artifact_dir: str,
    expected_source_fingerprint: str | None,
    metadata_mtime_ns: int,
) -> HybridSearchIndex:
    del metadata_mtime_ns
    return HybridSearchIndex.load(
        Path(artifact_dir),
        expected_source_fingerprint=expected_source_fingerprint,
    )


def load_hybrid_search_index(
    artifact_dir: Path,
    *,
    expected_source_fingerprint: str | None = None,
) -> HybridSearchIndex:
    metadata_path = artifact_dir / "metadata.json"
    if not metadata_path.is_file():
        raise SearchArtifactError(f"missing search artifact files: {metadata_path.name}")
    return _load_hybrid_search_index_cached(
        str(artifact_dir.resolve()),
        expected_source_fingerprint,
        metadata_path.stat().st_mtime_ns,
    )


def reciprocal_rank_fusion(
    bm25_hits: list[RetrievalHit],
    dense_hits: list[RetrievalHit],
    *,
    bm25_weight: float = 1.0,
    dense_weight: float = 1.0,
    rrf_k: int = 60,
    limit: int,
) -> list[HybridHit]:
    if bm25_weight < 0 or dense_weight < 0:
        raise ValueError("fusion weights must be non-negative")
    if bm25_weight == 0 and dense_weight == 0:
        raise ValueError("at least one fusion weight must be positive")
    if rrf_k < 1:
        raise ValueError("rrf_k must be positive")
    if limit <= 0:
        return []

    bm25_by_article = {hit.article_id: hit for hit in bm25_hits}
    dense_by_article = {hit.article_id: hit for hit in dense_hits}
    article_ids = bm25_by_article.keys() | dense_by_article.keys()
    fused: list[HybridHit] = []
    for article_id in article_ids:
        bm25_hit = bm25_by_article.get(article_id)
        dense_hit = dense_by_article.get(article_id)
        fusion_score = 0.0
        if bm25_hit is not None:
            fusion_score += bm25_weight / (rrf_k + bm25_hit.rank)
        if dense_hit is not None:
            fusion_score += dense_weight / (rrf_k + dense_hit.rank)
        fused.append(
            HybridHit(
                article_id=article_id,
                bm25_score=bm25_hit.score if bm25_hit is not None else 0.0,
                dense_score=dense_hit.score if dense_hit is not None else 0.0,
                fusion_score=fusion_score,
                bm25_rank=bm25_hit.rank if bm25_hit is not None else None,
                dense_rank=dense_hit.rank if dense_hit is not None else None,
            )
        )

    return sorted(
        fused,
        key=lambda hit: (-hit.fusion_score, hit.article_id),
    )[:limit]
