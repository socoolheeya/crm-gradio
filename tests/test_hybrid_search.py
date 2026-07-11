import pytest

from crm.hybrid_search import (
    SearchHit,
    bm25_search,
    expand_queries,
    hybrid_retrieve,
    normalize_expansions,
    rrf_fuse,
    tokenize_korean,
)


DOCUMENTS = [
    {"entity_type": "crm_tag", "entity_name": "휴면위험", "content": "CRM 태그: 휴면위험", "source_count": 10},
    {"entity_type": "campaign_name", "entity_name": "VIP 재구매 혜택", "content": "캠페인명: VIP 재구매 혜택", "source_count": 5},
    {"entity_type": "product_category", "entity_name": "생활용품", "content": "상품 카테고리: 생활용품", "source_count": 8},
]


def test_korean_tokenizer_includes_word_and_bigrams():
    tokens = tokenize_korean("생활 용품")
    assert "생활" in tokens
    assert "생활" in tokens
    assert "활용" in tokens


def test_bm25_ranks_exact_entity_first():
    hits = bm25_search("휴면위험", DOCUMENTS, limit=3)
    assert hits[0].entity_name == "휴면위험"
    assert hits[0].bm25_score > 0


def test_rrf_merges_duplicate_entity_and_keeps_diagnostics():
    keyword = SearchHit("crm_tag", "휴면위험", "CRM 태그: 휴면위험", 10, bm25_score=3.0)
    vector = SearchHit("crm_tag", "휴면위험", "CRM 태그: 휴면위험", 10, vector_score=0.8)
    fused = rrf_fuse([[keyword], [vector]], limit=5)
    assert len(fused) == 1
    assert fused[0].bm25_score == 3.0
    assert fused[0].vector_score == 0.8
    assert fused[0].rrf_score == pytest.approx(2 / 61)


def test_expansions_remove_blank_duplicates_and_original():
    assert normalize_expansions("휴면 고객", ["", "휴면 고객", "재활성화 쿠폰", "재활성화 쿠폰"]) == [
        "휴면 고객", "재활성화 쿠폰"
    ]


def test_expander_failure_falls_back_to_original_query():
    def broken(_query):
        raise RuntimeError("API unavailable")

    assert expand_queries("휴면 고객", broken) == ["휴면 고객"]


def test_hybrid_retrieval_searches_every_expanded_query():
    calls = []

    def vector_searcher(query, limit):
        calls.append((query, limit))
        return [SearchHit("crm_tag", "휴면위험", "CRM 태그: 휴면위험", 10, vector_score=0.9)]

    hits, queries = hybrid_retrieve(
        "휴면 고객",
        DOCUMENTS,
        vector_searcher,
        expander=lambda _query: ["재활성화 쿠폰"],
        limit=3,
    )
    assert queries == ["휴면 고객", "재활성화 쿠폰"]
    assert calls == [("휴면 고객", 3), ("재활성화 쿠폰", 3)]
    assert hits[0].entity_name == "휴면위험"
    assert set(hits[0].matched_queries) == {"재활성화 쿠폰", "휴면 고객"}
