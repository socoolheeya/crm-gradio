import pytest

from crm.sql_guard import validate_read_only_sql


@pytest.mark.parametrize("sql", [
    "SELECT customer_id FROM crm_events LIMIT 10",
    "WITH risky AS (SELECT customer_id FROM crm_events) SELECT * FROM risky LIMIT 10",
])
def test_allows_single_read_only_query(sql):
    assert validate_read_only_sql(sql) == sql


@pytest.mark.parametrize("sql", [
    "DELETE FROM crm_events",
    "SELECT 1; DROP TABLE crm_events",
    "UPDATE crm_events SET region = '서울'",
    "COPY crm_events TO '/tmp/data'",
])
def test_rejects_mutation_or_multiple_statements(sql):
    with pytest.raises(ValueError):
        validate_read_only_sql(sql)
