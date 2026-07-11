from typing import Any

from sqlalchemy import Engine, text


class CRMRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list_customers(self, filters: dict[str, str] | None = None) -> list[dict]:
        filters = filters or {}
        clauses, params = [], {}
        for key in ("estimated_segment", "membership_grade", "region"):
            if filters.get(key):
                clauses.append(f"{key} = :{key}")
                params[key] = filters[key]
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = text("SELECT customer_id, max(membership_grade) membership_grade, max(region) region, "
                   "max(estimated_segment) estimated_segment, max(event_time) last_event_time "
                   f"FROM crm_events{where} GROUP BY customer_id ORDER BY customer_id")
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).mappings()]

    def get_customer_events(self, customer_id: str) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM crm_events WHERE customer_id=:id ORDER BY event_time DESC"), {"id": customer_id})
            return [dict(row) for row in rows.mappings()]

    def get_catalog_events(self) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM crm_events WHERE product_id IS NOT NULL"))
            return [dict(row) for row in rows.mappings()]
