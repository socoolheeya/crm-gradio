import json
from pathlib import Path

import pytest

from crm.loader import flatten_record, validate_dataset


DATASET = Path("shopping_mall_crm_behavior_sample_1000.json")


def test_dataset_has_exactly_1000_valid_records():
    records = validate_dataset(json.loads(DATASET.read_text(encoding="utf-8")))
    assert len(records) == 1000


def test_flatten_record_preserves_analysis_fields():
    record = json.loads(DATASET.read_text(encoding="utf-8"))["records"][0]
    row = flatten_record(record)
    assert row["event_id"] == "EVT_000001"
    assert row["customer_id"] == "CUST_0180"
    assert row["product_category"] == "생활용품"
    assert row["crm_tags"] == ["캠페인반응", "휴면위험", "할인민감"]


def test_validation_identifies_missing_event_id():
    with pytest.raises(ValueError, match="record 1.*event_id"):
        validate_dataset({"record_count": 1, "records": [{}]})
