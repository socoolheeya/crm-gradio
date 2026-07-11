# Behavior-Based CRM Recommendation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load 1,000 shopping-mall behavior events into PostgreSQL and provide deterministic customer/product/CRM-action recommendations through a new Gradio application.

**Architecture:** Docker Compose runs PostgreSQL, while a focused loader validates and upserts flattened JSON events into `crm_events`. A repository returns typed event rows, a pure recommendation module scores products and selects CRM actions, and `app.py` renders customer and campaign views while keeping optional LLM analysis behind a read-only SQL guard.

**Tech Stack:** Python 3.12, PostgreSQL 17, Docker Compose, SQLAlchemy 2, psycopg 3, Gradio 5, pytest, LangChain/OpenAI (optional natural-language analysis)

## Global Constraints

- Preserve `app_old.py` and `etf_database.db` byte-for-byte.
- Never use `rg`; use `find`, `grep`, and `sed` for repository searches.
- Store one JSON record per `crm_events` row and keep exactly 1,000 rows after repeated imports.
- Keep recommendation selection deterministic; an LLM may explain but must not decide scores.
- Permit only one read-only `SELECT` or `WITH ... SELECT` statement in natural-language analysis.
- Keep recommendations usable without an OpenAI API key.
- Do not commit database passwords or API keys.
- Compile and test successfully before completion.

---

## File Map

- `compose.yaml`: PostgreSQL service, persistent volume, port, and healthcheck.
- `.env.example`: non-secret local configuration template.
- `pyproject.toml`, `requirements.txt`: runtime and test dependencies.
- `crm/__init__.py`: package boundary.
- `crm/db.py`: engine construction and connection error boundary.
- `crm/schema.sql`: table and index definitions.
- `crm/loader.py`: JSON validation, flattening, schema setup, and idempotent upsert.
- `crm/repository.py`: typed customer/event queries used by UI and recommender.
- `crm/recommendations.py`: pure scoring, action selection, evidence, and fallback message.
- `crm/sql_guard.py`: read-only SQL validation.
- `app.py`: new CRM Gradio application; imports the focused modules above.
- `tests/test_loader.py`: flattening and import validation tests.
- `tests/test_recommendations.py`: behavior scoring and action-selection tests.
- `tests/test_sql_guard.py`: allowed and rejected SQL tests.
- `tests/test_app.py`: import and UI callback fallback tests.

### Task 1: PostgreSQL Runtime and Connection Boundary

**Files:**
- Create: `compose.yaml`
- Create: `.env.example`
- Create: `crm/__init__.py`
- Create: `crm/db.py`
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `DATABASE_URL` from the process environment.
- Produces: `get_database_url() -> str` and `create_db_engine(database_url: str | None = None) -> sqlalchemy.Engine`.

- [ ] **Step 1: Record protected-file hashes**

Run:

```bash
shasum -a 256 app_old.py etf_database.db > /tmp/crm-protected-before.sha256
```

Expected: two SHA-256 lines are written without modifying either file.

- [ ] **Step 2: Write failing connection configuration tests**

Create `tests/test_db.py` with tests that clear `DATABASE_URL`, assert the local PostgreSQL default URL, and assert that an explicit argument overrides the environment:

```python
from crm.db import create_db_engine, get_database_url


def test_default_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert get_database_url() == "postgresql+psycopg://crm_user:crm_password@localhost:5432/shopping_mall_crm"


def test_explicit_database_url_wins():
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    assert engine.url.drivername == "sqlite+pysqlite"
```

- [ ] **Step 3: Run the tests and verify failure**

Run: `uv run pytest tests/test_db.py -v`

Expected: FAIL because `crm.db` does not exist.

- [ ] **Step 4: Add dependencies and minimal DB implementation**

Add `sqlalchemy>=2.0`, `psycopg[binary]>=3.2`, and `pytest>=8.0` to `pyproject.toml`; mirror runtime dependencies in `requirements.txt`. Implement `crm/db.py`:

```python
import os
from sqlalchemy import Engine, create_engine

DEFAULT_DATABASE_URL = "postgresql+psycopg://crm_user:crm_password@localhost:5432/shopping_mall_crm"


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_db_engine(database_url: str | None = None) -> Engine:
    return create_engine(database_url or get_database_url(), pool_pre_ping=True)
```

Create `compose.yaml` with PostgreSQL 17 Alpine, database `shopping_mall_crm`, user `crm_user`, local development password, port `5432`, a named volume, and `pg_isready` healthcheck. Create `.env.example` with the matching `DATABASE_URL` and blank `OPENAI_API_KEY`.

- [ ] **Step 5: Lock dependencies and run tests**

Run: `uv lock && uv run pytest tests/test_db.py -v`

Expected: 2 passed.

- [ ] **Step 6: Validate Compose**

Run: `docker compose config --quiet`

Expected: exit code 0.

- [ ] **Step 7: Commit the runtime boundary**

```bash
git add compose.yaml .env.example pyproject.toml uv.lock requirements.txt crm/__init__.py crm/db.py tests/test_db.py
git commit -m "build: add PostgreSQL runtime for CRM data"
```

### Task 2: Validated, Idempotent JSON Import

**Files:**
- Create: `crm/schema.sql`
- Create: `crm/loader.py`
- Create: `tests/test_loader.py`

**Interfaces:**
- Consumes: `shopping_mall_crm_behavior_sample_1000.json`, `Engine` from Task 1.
- Produces: `flatten_record(record: dict) -> dict`, `validate_dataset(payload: dict) -> list[dict]`, `initialize_schema(engine: Engine) -> None`, and `load_json(engine: Engine, path: Path) -> int`.

- [ ] **Step 1: Write failing validation and flattening tests**

Create tests covering the real first record and malformed input:

```python
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
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/test_loader.py -v`

Expected: FAIL because `crm.loader` does not exist.

- [ ] **Step 3: Implement validation and flattening**

Implement required nested-field checks, ISO datetime parsing, integer/boolean normalization, and exact mappings for all fields listed in the design. `validate_dataset` must compare `record_count` with `len(records)`, reject duplicate/missing event IDs, and return records only after every record passes.

- [ ] **Step 4: Run unit tests**

Run: `uv run pytest tests/test_loader.py -v`

Expected: 3 passed.

- [ ] **Step 5: Define schema and upsert**

Create `crm/schema.sql` with explicit columns, `event_id TEXT PRIMARY KEY`, `event_time TIMESTAMP NOT NULL`, numeric/boolean types, `crm_tags TEXT[] NOT NULL DEFAULT '{}'`, and indexes named `idx_crm_events_customer_time`, `idx_crm_events_event_type`, `idx_crm_events_product`, `idx_crm_events_category`, and `idx_crm_events_purchase`. Implement `load_json` using one transaction and PostgreSQL `INSERT ... ON CONFLICT (event_id) DO UPDATE`.

- [ ] **Step 6: Start PostgreSQL and verify health**

Run: `docker compose up -d db && docker compose ps`

Expected: the `db` service becomes `healthy`.

- [ ] **Step 7: Import twice and verify idempotency**

Run:

```bash
uv run python -m crm.loader shopping_mall_crm_behavior_sample_1000.json
uv run python -m crm.loader shopping_mall_crm_behavior_sample_1000.json
docker compose exec -T db psql -U crm_user -d shopping_mall_crm -tAc "SELECT count(*) FROM crm_events"
```

Expected: each loader run reports 1,000 processed rows and SQL prints `1000`.

- [ ] **Step 8: Commit the importer**

```bash
git add crm/schema.sql crm/loader.py tests/test_loader.py
git commit -m "feat: import CRM behavior events into PostgreSQL"
```

### Task 3: Deterministic Recommendation Engine

**Files:**
- Create: `crm/repository.py`
- Create: `crm/recommendations.py`
- Create: `tests/test_recommendations.py`

**Interfaces:**
- Consumes: flattened event dictionaries returned by `CRMRepository.get_customer_events(customer_id)`.
- Produces: `CustomerSummary`, `Recommendation`, `summarize_customer(events)`, `recommend_for_customer(events, catalog_events, limit=3)`, `select_crm_action(summary)`, and `render_message(summary, recommendation)`.

- [ ] **Step 1: Write failing rule tests**

Use small event factories and assert observable behavior:

```python
def test_cart_without_purchase_gets_abandonment_action():
    events = [event("cart_add", category="뷰티", product="클렌징 오일", purchased=False, quantity=1)]
    result = recommend_for_customer(events, events, limit=1)[0]
    assert result.action == "장바구니 이탈 리마인드"
    assert "장바구니" in result.evidence


def test_dormant_discount_customer_gets_discounted_candidate():
    customer_events = [event("product_view", category="식품", tags=["휴면위험", "할인민감"], days_since=120)]
    catalog = [
        event("product_view", product="정가 상품", category="식품", discount=0),
        event("product_view", product="할인 상품", category="식품", discount=30),
    ]
    result = recommend_for_customer(customer_events, catalog, limit=1)[0]
    assert result.product_name == "할인 상품"
    assert result.action == "재활성화 쿠폰"


def test_scores_are_deterministic_and_normalized():
    first = recommend_for_customer(sample_events(), sample_catalog())
    second = recommend_for_customer(sample_events(), sample_catalog())
    assert first == second
    assert all(0 <= item.score <= 100 for item in first)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/test_recommendations.py -v`

Expected: FAIL because recommendation interfaces do not exist.

- [ ] **Step 3: Implement typed summaries and scoring**

Use frozen dataclasses for `CustomerSummary` and `Recommendation`. Implement the approved weights (purchase 5, cart/quantity 4, wishlist 3, view 2, search 2, coupon-on-discount 2), a bounded recency multiplier based on the dataset's maximum event time, repeat-category and preferred-price bonuses, prior-purchase penalty, discount-sensitive bonus, and 0–100 normalization. Break ties by product ID so results are stable.

- [ ] **Step 4: Implement action priority and fallback message**

Implement the approved action ordering, evidence strings derived from actual aggregates, preferred channel from observed channel frequency, segment/grade popular-product fallback for sparse customers, and a Korean template message that needs no LLM.

- [ ] **Step 5: Implement repository queries**

`CRMRepository` receives an `Engine` and exposes `list_customers(filters)`, `get_customer_events(customer_id)`, `get_catalog_events()`, and `get_priority_customers(limit)`. Use SQLAlchemy `text()` with bound parameters and select explicit columns only.

- [ ] **Step 6: Run recommendation tests and a live smoke query**

Run:

```bash
uv run pytest tests/test_recommendations.py -v
uv run python -c "from crm.db import create_db_engine; from crm.repository import CRMRepository; print(len(CRMRepository(create_db_engine()).list_customers({})))"
```

Expected: all tests pass and the smoke query prints a positive customer count.

- [ ] **Step 7: Commit the recommendation core**

```bash
git add crm/repository.py crm/recommendations.py tests/test_recommendations.py
git commit -m "feat: add deterministic CRM recommendation engine"
```

### Task 4: Read-Only Natural-Language Analysis Boundary

**Files:**
- Create: `crm/sql_guard.py`
- Create: `crm/analysis.py`
- Create: `tests/test_sql_guard.py`

**Interfaces:**
- Consumes: candidate SQL text and optional `OPENAI_API_KEY`.
- Produces: `validate_read_only_sql(sql: str) -> str` and `analyze_question(question: str, repository: CRMRepository) -> AnalysisResult`.

- [ ] **Step 1: Write failing SQL guard tests**

```python
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
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/test_sql_guard.py -v`

Expected: FAIL because `crm.sql_guard` does not exist.

- [ ] **Step 3: Implement strict SQL validation**

Strip markdown fences and comments, require exactly one statement, require the first token to be `SELECT` or `WITH`, and reject mutation, DDL, transaction, file, and execution keywords. Apply a statement timeout and a read-only transaction when executing approved SQL.

- [ ] **Step 4: Implement optional analysis service**

When `OPENAI_API_KEY` is absent, return a clear message that natural-language analysis is disabled while rule recommendations remain available. When present, provide only `crm_events` schema to the model, validate generated SQL before execution, cap output rows at 100, and return the generated SQL with a Korean summary.

- [ ] **Step 5: Run guard tests**

Run: `uv run pytest tests/test_sql_guard.py -v`

Expected: all parametrized cases pass.

- [ ] **Step 6: Commit the analysis boundary**

```bash
git add crm/sql_guard.py crm/analysis.py tests/test_sql_guard.py
git commit -m "feat: guard CRM natural-language SQL analysis"
```

### Task 5: New CRM Gradio Application

**Files:**
- Create: `app.py`
- Create: `tests/test_app.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `CRMRepository`, recommendation interfaces, and optional analysis service.
- Produces: `build_demo(repository: CRMRepository | None = None) -> gr.Blocks`, `load_customer_recommendations(customer_id, filters)`, `load_priority_customers(filters)`, and `answer_analysis_question(question)`.

- [ ] **Step 1: Write failing import and fallback tests**

```python
import importlib


def test_app_import_does_not_connect_to_database():
    module = importlib.import_module("app")
    assert callable(module.build_demo)


def test_build_demo_returns_blocks(fake_repository):
    from app import build_demo
    demo = build_demo(fake_repository)
    assert demo is not None
```

Use a fake repository fixture that returns one customer and deterministic event dictionaries so tests require neither PostgreSQL nor OpenAI.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/test_app.py -v`

Expected: FAIL because the new `app.py` does not exist.

- [ ] **Step 3: Implement the Gradio Blocks UI**

Create tabs for “고객별 추천”, “우선 연락 고객”, and “자연어 CRM 분석”. Provide customer/segment/grade/region controls, customer summary, a recommendation table with up to three rows, evidence and Korean message panels, a priority-customer table, and generated SQL disclosure. Initialize the engine lazily inside `build_demo` or callbacks so importing `app` never requires a running DB.

- [ ] **Step 4: Add safe UI error handling**

Catch SQLAlchemy connection errors at the callback boundary, return a Korean setup instruction without exposing the URL/password, keep rule-based recommendations available without OpenAI, and reject blank customer IDs/questions before executing work.

- [ ] **Step 5: Document setup and usage**

Update `README.md` with exact commands:

```bash
cp .env.example .env
docker compose up -d db
uv run python -m crm.loader shopping_mall_crm_behavior_sample_1000.json
uv run python app.py
```

Document the three tabs, example CRM questions, optional `OPENAI_API_KEY`, verification commands, and destructive warning for `docker compose down -v`.

- [ ] **Step 6: Run application tests and compile**

Run:

```bash
uv run pytest tests/test_app.py -v
uv run python -m compileall -q app.py crm tests
```

Expected: tests pass and compile exits 0.

- [ ] **Step 7: Commit the application**

```bash
git add app.py tests/test_app.py README.md
git commit -m "feat: add behavior-based CRM recommendation app"
```

### Task 6: Full Verification and Closeout

**Files:**
- Verify only; modify implementation files only if a failing check exposes a defect.

**Interfaces:**
- Consumes: all earlier deliverables.
- Produces: fresh test, compile, DB, preservation, and review evidence.

- [ ] **Step 1: Run the complete automated suite**

Run: `uv run pytest -v`

Expected: all tests pass.

- [ ] **Step 2: Run fresh compile verification**

Run: `uv run python -m compileall -q app.py crm tests`

Expected: exit code 0.

- [ ] **Step 3: Verify live PostgreSQL state**

Run:

```bash
docker compose ps
docker compose exec -T db psql -U crm_user -d shopping_mall_crm -tAc "SELECT count(*), count(DISTINCT event_id), count(DISTINCT customer_id) FROM crm_events"
```

Expected: DB is healthy; total and distinct event count are both 1,000; customer count is positive.

- [ ] **Step 4: Verify protected originals**

Run:

```bash
shasum -a 256 -c /tmp/crm-protected-before.sha256
git diff -- app_old.py etf_database.db
```

Expected: both files report `OK`, and `git diff` is empty.

- [ ] **Step 5: Run review and fix verified findings**

Review the complete diff for secret leakage, SQL mutation paths, nondeterministic scoring, import-time DB connections, and accidental changes to protected files. For every valid finding, add a failing regression test, implement the smallest fix, and rerun the affected test plus the full suite.

- [ ] **Step 6: Run Compound closeout after fresh verification**

Run: `/ce-compound mode:headless behavior CRM PostgreSQL import, deterministic recommendations, read-only analysis, protected originals, and verification commands`

Expected: durable mistakes, assumptions, review signals, root causes, prevention checks, relevant files, and verification commands are captured; if no reusable lesson exists, record that explicitly.

- [ ] **Step 7: Report completion**

Report the working features, exact test/compile/DB results, PostgreSQL startup command, app startup command, protected-file hash evidence, and any limitations. Do not claim completion unless every fresh verification command above succeeds.
