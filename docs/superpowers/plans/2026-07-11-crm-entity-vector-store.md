# CRM Entity Vector Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract unique CRM entities from `crm_events`, embed them with `text-embedding-3-small`, and store them idempotently in the same PostgreSQL database with pgvector.

**Architecture:** Replace only the PostgreSQL container image with the PostgreSQL 17 pgvector image while preserving the named volume. A pure extractor returns typed entity records, and a separate batch embedder/upserter writes `VECTOR(1536)` rows to `crm_entities`.

**Tech Stack:** Python 3.12, PostgreSQL 17, pgvector 0.8.4, OpenAI embeddings, SQLAlchemy 2, psycopg 3, pytest

## Global Constraints

- Preserve the existing Docker volume and all 1,000 `crm_events` rows.
- Never run `docker compose down -v`.
- Preserve `app_old.py` and `etf_database.db` byte-for-byte.
- Extract product names, categories, campaigns, regions, traffic sources, CRM tags, and segments.
- Use `(entity_type, entity_name)` as the unique key and make repeated loads idempotent.
- Do not log or store the OpenAI API key.
- Never use `rg`.
- Compile and test successfully before completion.

---

### Task 1: pgvector Runtime

**Files:**
- Modify: `compose.yaml`
- Modify: `crm/schema.sql`
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Test: `tests/test_entity_vectors.py`

**Interfaces:**
- Consumes: existing PostgreSQL named volume.
- Produces: `vector` extension and `crm_entities` schema with `VECTOR(1536)`.

- [ ] **Step 1: Write the failing schema test**

```python
from pathlib import Path


def test_vector_schema_has_unique_key_and_1536_dimensions():
    schema = Path("crm/schema.sql").read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in schema
    assert "embedding VECTOR(1536)" in schema
    assert "UNIQUE (entity_type, entity_name)" in schema
```

- [ ] **Step 2: Run RED**

Run: `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_entity_vectors.py -q`

Expected: FAIL because the vector schema is absent.

- [ ] **Step 3: Add pgvector runtime and schema**

Change the image to `pgvector/pgvector:0.8.4-pg17`. Add `CREATE EXTENSION IF NOT EXISTS vector`, `crm_entities`, and an HNSW cosine index to `crm/schema.sql`. Add `pgvector>=0.4` to Python dependencies.

- [ ] **Step 4: Run GREEN and recreate without deleting the volume**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_entity_vectors.py -q
docker compose up -d --force-recreate db
docker compose exec -T db psql -U crm_user -d shopping_mall_crm -tAc "SELECT count(*) FROM crm_events"
```

Expected: test passes and SQL prints `1000`.

### Task 2: Entity Extraction and Batch Embedding

**Files:**
- Create: `crm/entity_vectors.py`
- Modify: `tests/test_entity_vectors.py`

**Interfaces:**
- Consumes: repository `Engine` and an embedding client exposing `embed_documents(texts: list[str]) -> list[list[float]]`.
- Produces: `Entity`, `extract_entities(engine) -> list[Entity]`, `store_entity_vectors(engine, entities, embedder, batch_size=100) -> int`.

- [ ] **Step 1: Write failing extraction tests**

```python
def test_rows_to_entities_deduplicates_and_counts_values():
    rows = [
        {"entity_type": "product_name", "entity_name": "수납 박스", "source_count": 4},
        {"entity_type": "crm_tag", "entity_name": "휴면위험", "source_count": 8},
    ]
    entities = rows_to_entities(rows)
    assert [(e.entity_type, e.entity_name, e.source_count) for e in entities] == [
        ("crm_tag", "휴면위험", 8), ("product_name", "수납 박스", 4)
    ]


def test_content_contains_type_context():
    entity = Entity("product_category", "생활용품", 10)
    assert entity.content == "상품 카테고리: 생활용품"
```

- [ ] **Step 2: Run RED**

Run: `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_entity_vectors.py -q`

Expected: FAIL because `crm.entity_vectors` is absent.

- [ ] **Step 3: Implement extraction and storage**

Use a `UNION ALL` query with `unnest(crm_tags)`, `GROUP BY entity_type, entity_name`, and non-empty filtering. Use a frozen `Entity` dataclass with Korean type labels. Embed in batches, require every vector to have 1536 values, and upsert all fields in one transaction. Delete rows whose key is not in the current extracted set only after successful embedding.

- [ ] **Step 4: Run GREEN**

Run: `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_entity_vectors.py -q`

Expected: all vector unit tests pass without DB or network access.

### Task 3: Live Load and Verification

**Files:**
- Modify: `README.md`
- Verify: `crm/entity_vectors.py`

**Interfaces:**
- Consumes: `OPENAI_API_KEY` from `.env` and live PostgreSQL.
- Produces: populated `crm_entities` and a CLI search smoke test.

- [ ] **Step 1: Add CLI and documentation**

Implement `python -m crm.entity_vectors load` using `OpenAIEmbeddings(model="text-embedding-3-small")`, plus `search <query> --limit 10`. Document both commands without exposing secrets.

- [ ] **Step 2: Load twice**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m crm.entity_vectors load
UV_CACHE_DIR=.uv-cache uv run python -m crm.entity_vectors load
```

Expected: both runs report the same stored entity count.

- [ ] **Step 3: Verify database integrity and vector dimensions**

Run:

```bash
docker compose exec -T db psql -U crm_user -d shopping_mall_crm -tAc "SELECT count(*) FROM crm_events; SELECT count(*), count(DISTINCT (entity_type, entity_name)), min(vector_dims(embedding)), max(vector_dims(embedding)) FROM crm_entities;"
```

Expected: `crm_events` remains 1,000; entity total equals unique total; min and max dimensions are 1536.

- [ ] **Step 4: Verify semantic search**

Run: `UV_CACHE_DIR=.uv-cache uv run python -m crm.entity_vectors search "휴면 고객 할인 캠페인" --limit 5`

Expected: five ranked Korean CRM entities with cosine similarity values.

- [ ] **Step 5: Run fresh full verification**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests -q
UV_CACHE_DIR=.uv-cache uv run python -m compileall -q app.py crm tests
docker compose config --quiet
shasum -a 256 -c /tmp/crm-protected-before.sha256
```

Expected: all tests pass, compile and Compose validation exit 0, and both protected files report `OK`.

- [ ] **Step 6: Run Compound closeout**

Run: `/ce-compound mode:headless pgvector CRM entity extraction, OpenAI batch embedding, idempotent storage, preserved relational data, and verification commands`

Expected: a reusable solution doc is written and validated after fresh verification.
