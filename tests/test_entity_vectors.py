from pathlib import Path

import pytest

from crm.entity_vectors import Entity, rows_to_entities, store_entity_vectors


def test_vector_schema_has_unique_key_and_1536_dimensions():
    schema = Path("crm/schema.sql").read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in schema
    assert "embedding VECTOR(1536)" in schema
    assert "UNIQUE (entity_type, entity_name)" in schema


def test_rows_to_entities_sorts_and_preserves_counts():
    rows = [
        {"entity_type": "product_name", "entity_name": "수납 박스", "source_count": 4},
        {"entity_type": "crm_tag", "entity_name": "휴면위험", "source_count": 8},
    ]
    entities = rows_to_entities(rows)
    assert [(e.entity_type, e.entity_name, e.source_count) for e in entities] == [
        ("crm_tag", "휴면위험", 8),
        ("product_name", "수납 박스", 4),
    ]


def test_content_contains_type_context():
    entity = Entity("product_category", "생활용품", 10)
    assert entity.content == "상품 카테고리: 생활용품"


class WrongDimensionEmbedder:
    def embed_documents(self, texts):
        return [[0.1, 0.2] for _ in texts]


def test_store_rejects_wrong_embedding_dimensions():
    with pytest.raises(ValueError, match="1536"):
        store_entity_vectors(None, [Entity("region", "서울", 1)], WrongDimensionEmbedder())
