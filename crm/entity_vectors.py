import argparse
import json
from dataclasses import dataclass
from typing import Iterable, Protocol

from dotenv import load_dotenv
from sqlalchemy import Engine, text

from crm.db import create_db_engine
from crm.loader import initialize_schema


TYPE_LABELS = {
    "product_name": "상품명",
    "product_category": "상품 카테고리",
    "campaign_name": "캠페인명",
    "region": "지역",
    "traffic_source": "유입 경로",
    "crm_tag": "CRM 태그",
    "estimated_segment": "고객 세그먼트",
}


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class Entity:
    entity_type: str
    entity_name: str
    source_count: int

    @property
    def content(self) -> str:
        return f"{TYPE_LABELS[self.entity_type]}: {self.entity_name}"


def rows_to_entities(rows: Iterable[dict]) -> list[Entity]:
    entities = {
        (str(row["entity_type"]), str(row["entity_name"]).strip()): int(row["source_count"])
        for row in rows
        if row.get("entity_name") and str(row["entity_name"]).strip()
    }
    return [Entity(kind, name, count) for (kind, name), count in sorted(entities.items())]


EXTRACT_SQL = """
WITH entities AS (
    SELECT 'product_name' AS entity_type, product_name AS entity_name FROM crm_events
    UNION ALL SELECT 'product_category', product_category FROM crm_events
    UNION ALL SELECT 'campaign_name', campaign_name FROM crm_events
    UNION ALL SELECT 'region', region FROM crm_events
    UNION ALL SELECT 'traffic_source', traffic_source FROM crm_events
    UNION ALL SELECT 'estimated_segment', estimated_segment FROM crm_events
    UNION ALL SELECT 'crm_tag', unnest(crm_tags) FROM crm_events
)
SELECT entity_type, btrim(entity_name) AS entity_name, count(*) AS source_count
FROM entities
WHERE entity_name IS NOT NULL AND btrim(entity_name) <> ''
GROUP BY entity_type, btrim(entity_name)
ORDER BY entity_type, entity_name
"""


def extract_entities(engine: Engine) -> list[Entity]:
    with engine.connect() as connection:
        rows = connection.execute(text(EXTRACT_SQL)).mappings()
        return rows_to_entities(rows)


def _vector_literal(values: list[float]) -> str:
    if len(values) != 1536:
        raise ValueError(f"embedding must contain 1536 dimensions, got {len(values)}")
    return "[" + ",".join(str(float(value)) for value in values) + "]"


def store_entity_vectors(engine: Engine | None, entities: list[Entity], embedder: Embedder, batch_size: int = 100) -> int:
    embedded: list[dict] = []
    for offset in range(0, len(entities), batch_size):
        batch = entities[offset:offset + batch_size]
        vectors = embedder.embed_documents([entity.content for entity in batch])
        if len(vectors) != len(batch):
            raise ValueError("embedding response count does not match entity count")
        for entity, vector in zip(batch, vectors, strict=True):
            embedded.append({
                "entity_type": entity.entity_type,
                "entity_name": entity.entity_name,
                "content": entity.content,
                "source_count": entity.source_count,
                "metadata": json.dumps({"type_label": TYPE_LABELS[entity.entity_type]}, ensure_ascii=False),
                "embedding": _vector_literal(vector),
            })
    if engine is None:
        return len(embedded)
    initialize_schema(engine)
    statement = text("""
        INSERT INTO crm_entities (entity_type, entity_name, content, source_count, metadata, embedding)
        VALUES (:entity_type, :entity_name, :content, :source_count, CAST(:metadata AS jsonb), CAST(:embedding AS vector))
        ON CONFLICT (entity_type, entity_name) DO UPDATE SET
          content = EXCLUDED.content,
          source_count = EXCLUDED.source_count,
          metadata = EXCLUDED.metadata,
          embedding = EXCLUDED.embedding,
          updated_at = now()
    """)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM crm_entities"))
        if embedded:
            connection.execute(statement, embedded)
    return len(embedded)


def _openai_embedder():
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model="text-embedding-3-small", dimensions=1536)


def load(engine: Engine, embedder: Embedder) -> int:
    initialize_schema(engine)
    return store_entity_vectors(engine, extract_entities(engine), embedder)


def search(engine: Engine, embedder: Embedder, query: str, limit: int = 10) -> list[dict]:
    vector = _vector_literal(embedder.embed_query(query))
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT entity_type, entity_name, content, source_count,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM crm_entities
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """), {"embedding": vector, "limit": limit}).mappings()
        return [dict(row) for row in rows]


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Store and search CRM entity embeddings")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("load")
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    engine, embedder = create_db_engine(), _openai_embedder()
    if args.command == "load":
        print(f"{load(engine, embedder)} entities stored")
    else:
        for row in search(engine, embedder, args.query, args.limit):
            print(f"{row['similarity']:.4f}\t{row['entity_type']}\t{row['entity_name']}\t{row['source_count']}")


if __name__ == "__main__":
    main()
