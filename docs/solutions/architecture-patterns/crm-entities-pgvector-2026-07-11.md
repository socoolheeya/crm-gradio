---
title: Store structured CRM entities as vectors beside relational events
date: 2026-07-11
category: architecture-patterns
module: crm-entity-vectors
problem_type: architecture_pattern
component: database
severity: medium
applies_when:
  - Structured CRM fields need semantic search without a separate vector database
  - Existing PostgreSQL data must survive a switch to a pgvector-enabled image
  - External embedding calls must not leave partially synchronized rows
tags: [pgvector, postgresql, crm, embeddings, semantic-search, idempotent-import]
---

# Store structured CRM entities as vectors beside relational events

## Context

The CRM database already held 1,000 relational behavior events. Product names, categories, campaigns, regions, traffic sources, CRM tags, and customer segments also needed semantic search. A separate vector service would add unnecessary infrastructure and complicate joins back to CRM facts.

The implementation had to preserve the existing Docker volume, prevent duplicate entities on repeated loads, and avoid partial database state when OpenAI embedding requests fail.

## Guidance

Use pgvector in the same PostgreSQL database and keep relational and vector concerns in separate tables:

- `crm_events` remains the source of structured behavioral facts.
- `crm_entities` stores one row per `(entity_type, entity_name)` with its source frequency, contextual text, metadata, and `VECTOR(1536)` embedding.

Switching from the standard PostgreSQL 17 container image to the matching `pgvector/pgvector:0.8.4-pg17` image does not require deleting the named volume. Recreate only the container and verify the relational row count immediately afterward. Never use `docker compose down -v` for this migration.

Extract entities deterministically with explicit SQL columns and `unnest(crm_tags)`. This is preferable to LLM extraction for structured values because entity boundaries and provenance are already known. Add Korean type context before embedding, for example `상품 카테고리: 생활용품`, so semantically similar labels from different fields remain distinguishable.

Generate all embedding batches before opening the write transaction. Validate that each response has exactly 1536 values, then synchronize the table in one transaction. A unique constraint on `(entity_type, entity_name)` and a cosine HNSW index provide repeatability and efficient nearest-neighbor search.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE crm_entities (
  entity_type TEXT NOT NULL,
  entity_name TEXT NOT NULL,
  content TEXT NOT NULL,
  source_count INTEGER NOT NULL,
  metadata JSONB NOT NULL,
  embedding VECTOR(1536) NOT NULL,
  UNIQUE (entity_type, entity_name)
);
CREATE INDEX ON crm_entities USING hnsw (embedding vector_cosine_ops);
```

## Why This Matters

One PostgreSQL instance can use ACID transactions, relational joins, backups, and vector similarity together. Deterministic extraction makes the 97 stored entities auditable: 50 products, 10 categories, 7 campaigns, 10 regions, 8 traffic sources, 6 CRM tags, and 6 segments. Repeating the load retained 97 unique rows and every vector remained 1536-dimensional.

Embedding first and writing second prevents an API failure from clearing or partially updating the production entity set. Explicit type context improves search relevance without relying on an LLM to infer schema semantics.

## When to Apply

- The source data already lives in PostgreSQL and vector results must join to relational facts
- The entity vocabulary is derived from known structured columns
- Dataset size does not justify operating a separate vector service
- Embeddings are refreshed in batches and must be synchronized atomically

## Examples

```bash
UV_CACHE_DIR=.uv-cache uv run python -m crm.entity_vectors load
UV_CACHE_DIR=.uv-cache uv run python -m crm.entity_vectors search "휴면 고객 할인 캠페인" --limit 5
```

The verified semantic query returned campaign and dormancy-related entities. Database checks showed 1,000 unchanged CRM events, 97 entity rows, 97 unique keys, and 1536 dimensions for every embedding.

```sql
SELECT count(*),
       count(DISTINCT (entity_type, entity_name)),
       min(vector_dims(embedding)),
       max(vector_dims(embedding))
FROM crm_entities;
```

## Related

- [CRM entity vector-store design](../../superpowers/specs/2026-07-11-crm-entity-vector-store-design.md)
- [CRM entity vector-store implementation plan](../../superpowers/plans/2026-07-11-crm-entity-vector-store.md)
- [Deterministic CRM recommendations](deterministic-crm-recommendations-postgresql-2026-07-11.md)
