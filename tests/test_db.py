from crm.db import create_db_engine, get_database_url


def test_default_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert get_database_url().endswith("@localhost:5432/shopping_mall_crm")


def test_explicit_database_url_wins():
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    assert engine.url.drivername == "sqlite+pysqlite"
