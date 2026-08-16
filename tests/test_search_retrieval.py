from __future__ import annotations

import pytest

from backend.app.search_retrieval import (
    BM25Index,
    HybridSearchConfig,
    LexicalBaselineIndex,
    RetrievalHit,
    SearchDocument,
    build_hybrid_search_result,
    lexical_document_score,
    lexical_search_terms,
    reciprocal_rank_fusion,
    tokenize_search_text,
)


def test_tokenization_and_lexical_terms_are_deterministic():
    assert tokenize_search_text("  NFL's Week-11: Winners!  ") == [
        "nfl's",
        "week",
        "11",
        "winners",
    ]
    assert lexical_search_terms("  football   tactics  ") == [
        "football tactics",
        "football",
        "tactics",
    ]


def test_lexical_score_matches_existing_title_and_abstract_weights():
    document = SearchDocument(
        news_id="N1",
        headline="Football tactics explained",
        abstract="A guide to defensive football formations.",
    )

    assert lexical_document_score(document, "football tactics") == pytest.approx(7 / 9)


def test_bm25_prefers_repeated_title_match_and_has_stable_tiebreak():
    documents = [
        SearchDocument(news_id="N20", headline="Football tactics", abstract=""),
        SearchDocument(news_id="N10", headline="Football tactics", abstract=""),
        SearchDocument(news_id="N30", headline="Football", abstract="Celebrity news"),
    ]

    hits = BM25Index(documents).search("football tactics", limit=3)

    assert [hit.news_id for hit in hits] == ["N10", "N20", "N30"]
    assert hits[0].score == pytest.approx(hits[1].score)
    assert hits[1].score > hits[2].score


def test_lexical_baseline_preserves_alias_then_article_fallback_behavior():
    documents = [
        SearchDocument(
            news_id="N10",
            headline="NFL defensive tactics",
            abstract="Coaches explain football formations.",
            topic_ids=(14, 250),
            category="sports",
            subcategory="football_nfl",
        ),
        SearchDocument(
            news_id="N20",
            headline="College football preview",
            abstract="A new season begins.",
            topic_ids=(14, 248),
            category="sports",
            subcategory="football_ncaa",
        ),
    ]
    index = LexicalBaselineIndex(documents)

    alias = index.search("football_nfl", limit=10)
    article = index.search("defensive tactics", limit=10)

    assert alias is not None
    assert alias.query_key == "250"
    assert alias.source == "display_exact"
    assert [hit.news_id for hit in alias.hits] == ["N10"]
    assert article is not None
    assert article.query_key == "14"
    assert article.source == "article_text"
    assert article.hits[0].news_id == "N10"


def test_reciprocal_rank_fusion_combines_channels_and_preserves_scores():
    bm25_hits = [
        RetrievalHit(news_id="N1", score=4.0, rank=1),
        RetrievalHit(news_id="N2", score=3.0, rank=2),
    ]
    dense_hits = [
        RetrievalHit(news_id="N2", score=0.9, rank=1),
        RetrievalHit(news_id="N3", score=0.8, rank=2),
    ]

    hits = reciprocal_rank_fusion(
        bm25_hits,
        dense_hits,
        bm25_weight=1.0,
        dense_weight=1.0,
        rrf_k=10,
        limit=3,
    )

    assert [hit.news_id for hit in hits] == ["N2", "N1", "N3"]
    assert hits[0].bm25_score == 3.0
    assert hits[0].dense_score == 0.9
    assert hits[0].bm25_rank == 2
    assert hits[0].dense_rank == 1


def test_reciprocal_rank_fusion_rejects_zero_weights():
    with pytest.raises(ValueError, match="at least one"):
        reciprocal_rank_fusion(
            [],
            [],
            bm25_weight=0.0,
            dense_weight=0.0,
            limit=10,
        )


def test_hybrid_acceptance_uses_each_channels_top_evidence():
    result = build_hybrid_search_result(
        [RetrievalHit(news_id="N1", score=25.0, rank=1)],
        [RetrievalHit(news_id="N2", score=0.6, rank=1)],
        config=HybridSearchConfig(
            bm25_weight=2.0,
            dense_weight=1.0,
            min_dense_score=0.5,
            min_bm25_score=100.0,
        ),
        limit=2,
    )

    assert result.hits[0].news_id == "N1"
    assert result.hits[0].dense_score == 0.0
    assert result.top_dense_score == pytest.approx(0.6)
    assert result.accepted is True
