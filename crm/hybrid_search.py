import argparse
import re
from dataclasses import dataclass, replace
from typing import Callable, Iterable

from rank_bm25 import BM25Okapi
from sqlalchemy import Engine, text

from crm.db import create_db_engine
from crm.entity_vectors import _openai_embedder, _vector_literal


@dataclass(frozen=True)
class SearchHit:
    entity_type: str
    entity_name: str
    content: str
    source_count: int
    bm25_score: float = 0.0
    vector_score: float = 0.0
    rrf_score: float = 0.0
    matched_queries: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, str]:
        return self.entity_type, self.entity_name


def tokenize_korean(text: str) -> list[str]:
    normalized = re.sub(r"[^0-9a-zA-Z가-힣]+", " ", text.lower()).strip()
    words = normalized.split()
    compact = "".join(words)
    bigrams = [compact[index:index + 2] for index in range(max(0, len(compact) - 1))]
    return words + bigrams


def _hit(document: dict, **scores: float) -> SearchHit:
    return SearchHit(
        entity_type=str(document["entity_type"]), entity_name=str(document["entity_name"]),
        content=str(document["content"]), source_count=int(document["source_count"]), **scores,
    )


def bm25_search(query: str, documents: list[dict], limit: int = 10) -> list[SearchHit]:
    if not query.strip() or limit < 1 or not documents:
        return []
    corpus = [tokenize_korean(f"{d['entity_type']} {d['entity_name']} {d['content']}") for d in documents]
    scores = BM25Okapi(corpus).get_scores(tokenize_korean(query))
    ranked = sorted(enumerate(scores), key=lambda item: (-float(item[1]), documents[item[0]]["entity_type"], documents[item[0]]["entity_name"]))
    return [_hit(documents[index], bm25_score=float(score)) for index, score in ranked[:limit] if score > 0]


def normalize_expansions(query: str, expansions: Iterable[str], limit: int = 3) -> list[str]:
    original = query.strip()
    if not original:
        raise ValueError("검색어를 입력해 주세요")
    result = [original]
    for expansion in expansions:
        value = expansion.strip()
        if value and value not in result:
            result.append(value)
        if len(result) >= limit + 1:
            break
    return result


def rrf_fuse(result_lists: list[list[SearchHit]], k: int = 60, limit: int = 10) -> list[SearchHit]:
    fused: dict[tuple[str, str], SearchHit] = {}
    queries: dict[tuple[str, str], set[str]] = {}
    for results in result_lists:
        for rank, hit in enumerate(results, 1):
            current = fused.get(hit.key, hit)
            fused[hit.key] = replace(
                current,
                bm25_score=max(current.bm25_score, hit.bm25_score),
                vector_score=max(current.vector_score, hit.vector_score),
                rrf_score=current.rrf_score + 1 / (k + rank),
            )
            queries.setdefault(hit.key, set()).update(hit.matched_queries)
    final = [replace(hit, matched_queries=tuple(sorted(queries.get(key, set())))) for key, hit in fused.items()]
    return sorted(final, key=lambda hit: (-hit.rrf_score, hit.entity_type, hit.entity_name))[:limit]


def expand_queries(query: str, expander: Callable[[str], list[str]] | None = None) -> list[str]:
    if expander is None:
        return normalize_expansions(query, [])
    try:
        return normalize_expansions(query, expander(query))
    except Exception:
        return normalize_expansions(query, [])


def hybrid_retrieve(
    query: str,
    documents: list[dict],
    vector_searcher: Callable[[str, int], list[SearchHit]],
    expander: Callable[[str], list[str]] | None = None,
    limit: int = 10,
) -> tuple[list[SearchHit], list[str]]:
    if limit < 1:
        raise ValueError("limit은 1 이상이어야 합니다")
    queries = expand_queries(query, expander)
    ranked: list[list[SearchHit]] = []
    for search_query in queries:
        ranked.append([replace(hit, matched_queries=(search_query,)) for hit in bm25_search(search_query, documents, limit)])
        ranked.append([replace(hit, matched_queries=(search_query,)) for hit in vector_searcher(search_query, limit)])
    return rrf_fuse(ranked, limit=limit), queries


def load_documents(engine: Engine) -> list[dict]:
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT entity_type, entity_name, content, source_count
            FROM crm_entities ORDER BY entity_type, entity_name
        """)).mappings()
        return [dict(row) for row in rows]


def make_vector_searcher(engine: Engine, embedder) -> Callable[[str, int], list[SearchHit]]:
    def vector_searcher(query: str, limit: int) -> list[SearchHit]:
        vector = _vector_literal(embedder.embed_query(query))
        with engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT entity_type, entity_name, content, source_count,
                       1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM crm_entities
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :limit
            """), {"embedding": vector, "limit": limit}).mappings()
            return [_hit(dict(row), vector_score=float(row["similarity"])) for row in rows]
    return vector_searcher


def make_openai_expander():
    from pydantic import BaseModel, Field
    from langchain_openai import ChatOpenAI

    class ExpandedQueries(BaseModel):
        queries: list[str] = Field(description="원래 의도를 유지하는 한국어 CRM 검색어, 최대 3개")

    model = ChatOpenAI(model="gpt-4.1-mini", temperature=0).with_structured_output(ExpandedQueries)

    def expand(query: str) -> list[str]:
        result = model.invoke(
            "다음 CRM 질문의 동의어, 업무 용어, 관련 캠페인 표현을 사용해 보조 검색어를 최대 3개 생성하세요. "
            f"원문을 반복하지 마세요. 질문: {query}"
        )
        return result.queries[:3]
    return expand


def search_live(query: str, limit: int = 10) -> tuple[list[SearchHit], list[str]]:
    engine = create_db_engine()
    embedder = _openai_embedder()
    return hybrid_retrieve(
        query,
        load_documents(engine),
        make_vector_searcher(engine, embedder),
        make_openai_expander(),
        limit,
    )


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(description="BM25 + pgvector CRM hybrid search")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    hits, queries = search_live(args.query, args.limit)
    print("확장 검색어:", " | ".join(queries))
    for hit in hits:
        print(
            f"{hit.rrf_score:.6f}\tBM25={hit.bm25_score:.4f}\tVECTOR={hit.vector_score:.4f}\t"
            f"{hit.entity_type}\t{hit.entity_name}\t{','.join(hit.matched_queries)}"
        )


if __name__ == "__main__":
    main()
