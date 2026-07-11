# CRM Hybrid Retriever Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Search CRM entities with Korean BM25, pgvector semantic similarity, optional LLM query expansion, and deterministic RRF fusion in CLI and Gradio.

**Architecture:** `crm/hybrid_search.py` owns tokenization, BM25 ranking, expansion fallback, vector retrieval, and RRF. `app.py` calls the same service lazily so import and unit tests require neither PostgreSQL nor OpenAI.

**Tech Stack:** Python 3.12, rank-bm25, PostgreSQL 17, pgvector 0.8.4, OpenAI embeddings, Gradio 5, pytest

## Global Constraints

- Keep `crm_events` 1,000 rows and `crm_entities` 97 rows unchanged.
- Preserve `app_old.py` and `etf_database.db` byte-for-byte.
- Query expansion failure must fall back to the original query.
- Use RRF with `k=60` and stable tie-breaking.
- Never use `rg`.
- Do not run `ce-compound` for this task.
- Compile and test successfully before completion.

---

### Task 1: Korean BM25 and RRF Core

**Files:**
- Create: `crm/hybrid_search.py`
- Create: `tests/test_hybrid_search.py`
- Modify: `pyproject.toml`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `tokenize_korean(text)`, `bm25_search(query, documents, limit)`, `rrf_fuse(result_lists, k=60, limit=10)`.

- [ ] Write tests asserting `생활용품` produces word and character-bigram tokens, exact entity names rank first, duplicate entities fuse into one row, and ties sort by type/name.
- [ ] Run `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_hybrid_search.py -q`; expect missing-module failure.
- [ ] Add `rank-bm25>=0.2.2` and implement the smallest immutable `SearchHit` model and the three functions.
- [ ] Run the focused test; expect all cases to pass.

### Task 2: Query Expansion and Hybrid Service

**Files:**
- Modify: `crm/hybrid_search.py`
- Modify: `tests/test_hybrid_search.py`

**Interfaces:**
- Produces: `normalize_expansions(query, expansions, limit=3)`, `HybridRetriever.search(query, limit=10)`, and CLI entry point.

- [ ] Add failing tests for blank/duplicate expansion removal, expander exception fallback, BM25/vector invocation for every query, and score diagnostics.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement an injected expander/embedder, DB entity loading, existing pgvector cosine query, and RRF across every `(query, retriever)` list.
- [ ] Add OpenAI default expansion with structured output and fallback to `[original_query]`.
- [ ] Run focused tests; expect all to pass.

### Task 3: Gradio Integration and Verification

**Files:**
- Modify: `app.py`
- Modify: `README.md`
- Modify: `tests/test_app.py`

**Interfaces:**
- Produces: a “하이브리드 검색” tab showing expanded queries and fused results.

- [ ] Add a failing app test that inspects the Blocks configuration for the hybrid tab label without connecting to DB.
- [ ] Add query input, limit control, search button, expansion display, and result table with BM25/vector/RRF diagnostics.
- [ ] Document `python -m crm.hybrid_search "휴면 고객 할인" --limit 10`.
- [ ] Run the live CLI and verify results for a representative Korean query.
- [ ] Run `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests -q`, compileall, Compose validation, DB row-count checks, and protected-file hash checks.
