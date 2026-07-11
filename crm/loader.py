import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from crm.db import create_db_engine


def _required(record: dict, path: str, index: int | None = None) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            label = f"record {index}" if index is not None else "record"
            raise ValueError(f"{label}: missing {path}")
        value = value[part]
    return value


def validate_dataset(payload: dict) -> list[dict]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    if payload.get("record_count") != len(records):
        raise ValueError("record_count does not match records length")
    seen: set[str] = set()
    for index, record in enumerate(records, 1):
        event_id = _required(record, "event_id", index)
        _required(record, "event_time", index)
        _required(record, "customer.customer_id", index)
        _required(record, "event.event_type", index)
        if event_id in seen:
            raise ValueError(f"record {index}: duplicate event_id {event_id}")
        seen.add(event_id)
    return records


def flatten_record(record: dict) -> dict:
    customer, session, event = record["customer"], record["session"], record["event"]
    product, cart, order = record["product"], record["cart"], record["order"]
    campaign, crm = record["campaign"], record["crm"]
    return {
        "event_id": record["event_id"], "event_time": datetime.fromisoformat(record["event_time"]),
        "customer_id": customer["customer_id"], "age_group": customer.get("age_group"),
        "gender": customer.get("gender"), "region": customer.get("region"),
        "membership_grade": customer.get("membership_grade"), "is_new_customer": bool(customer.get("is_new_customer")),
        "session_id": session.get("session_id"), "channel": session.get("channel"),
        "traffic_source": session.get("traffic_source"), "device_type": session.get("device_type"),
        "event_type": event["event_type"], "page_stay_seconds": event.get("page_stay_seconds"),
        "search_keyword": event.get("search_keyword"), "product_id": product.get("product_id"),
        "product_name": product.get("product_name"), "product_category": product.get("category"),
        "product_price": product.get("price"), "discount_rate": product.get("discount_rate", 0),
        "discounted_price": product.get("discounted_price"), "cart_item_count": cart.get("cart_item_count", 0),
        "quantity": cart.get("quantity", 0), "order_id": order.get("order_id"),
        "order_amount": order.get("order_amount", 0), "is_purchase": bool(order.get("is_purchase")),
        "campaign_name": campaign.get("campaign_name"), "coupon_used": bool(campaign.get("coupon_used")),
        "coupon_downloaded": bool(campaign.get("coupon_downloaded")),
        "previous_purchase_count": crm.get("previous_purchase_count", 0),
        "days_since_last_purchase": crm.get("days_since_last_purchase"),
        "crm_tags": crm.get("tags") or [], "estimated_segment": crm.get("estimated_segment"),
    }


def initialize_schema(engine: Engine) -> None:
    sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with engine.begin() as connection:
        for statement in sql.split(";"):
            if statement.strip():
                connection.execute(text(statement))


def load_json(engine: Engine, path: Path) -> int:
    records = validate_dataset(json.loads(path.read_text(encoding="utf-8")))
    rows = [flatten_record(record) for record in records]
    initialize_schema(engine)
    columns = list(rows[0])
    insert = text(
        f"INSERT INTO crm_events ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)}) "
        f"ON CONFLICT (event_id) DO UPDATE SET "
        + ", ".join(f"{c}=EXCLUDED.{c}" for c in columns if c != "event_id")
    )
    with engine.begin() as connection:
        connection.execute(insert, rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load CRM behavior JSON into PostgreSQL")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(f"{load_json(create_db_engine(), args.path)} rows processed")


if __name__ == "__main__":
    main()
