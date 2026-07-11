---
title: Deterministic behavior-based CRM recommendations over PostgreSQL events
date: 2026-07-11
category: architecture-patterns
module: crm-recommendations
problem_type: architecture_pattern
component: assistant
severity: medium
applies_when:
  - Nested behavioral event JSON must support explainable customer recommendations
  - Recommendation results must remain available when an LLM is unavailable
  - Existing application and database artifacts must remain unchanged
tags: [crm, postgresql, recommendations, gradio, deterministic-scoring, json-import]
---

# Deterministic behavior-based CRM recommendations over PostgreSQL events

## Context

A shopping-mall CRM prototype needed to turn 1,000 nested synthetic behavior events into customer-specific product and campaign recommendations. The existing ETF application and SQLite database were protected originals, and recommendation decisions needed to be reproducible even without an OpenAI API key.

The main implementation risks were accidental changes to protected files, duplicate imports, an LLM becoming the untestable decision maker, and local verification failing because the sandbox could not access the normal uv cache, Docker socket, or localhost PostgreSQL.

## Guidance

Flatten each immutable event into one typed PostgreSQL row keyed by `event_id`. Import with `INSERT ... ON CONFLICT (event_id) DO UPDATE` inside a transaction so repeated runs preserve an exact event count.

Keep recommendation selection in a pure Python module. Assign explicit weights to observable events, add bounded recency/category/discount adjustments, normalize the score to 0–100, and use a stable product ID tie-breaker. Derive the CRM action from ordered rules such as cart abandonment, unused coupon, dormancy, new-customer onboarding, and VIP cross-selling. An LLM may rewrite the explanation but must not change the selected recommendation or score.

Keep I/O boundaries separate:

- `crm/loader.py` validates and imports JSON.
- `crm/repository.py` owns bound-parameter SQL queries.
- `crm/recommendations.py` contains deterministic scoring and message fallback.
- `app.py` builds Gradio lazily so module import does not require a live database.

Protect user-owned originals before implementation:

```bash
shasum -a 256 app_old.py etf_database.db > /tmp/crm-protected-before.sha256
# after implementation
shasum -a 256 -c /tmp/crm-protected-before.sha256
```

Use the project-local uv cache and module-form pytest invocation in restricted environments:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests -q
```

Calling `uv run pytest` directly did not put the repository package on `sys.path` in this environment. Calling `python -m pytest` did. Docker and localhost PostgreSQL access also required approved execution outside the filesystem sandbox; a healthy container alone did not prove that a sandboxed Python process could reach port 5432.

## Why This Matters

Deterministic scoring makes every recommendation explainable, testable, and stable across runs. PostgreSQL upserts make the seed workflow safe to repeat. Lazy database initialization lets tests import and inspect the Gradio application without infrastructure. Hash checks turn a promise not to touch legacy artifacts into verifiable evidence.

These boundaries also localize failures: JSON validation errors do not affect the UI, DB connection failures do not leak credentials, and OpenAI outages do not disable core recommendations.

## When to Apply

- Small or medium behavioral datasets where auditability matters more than model sophistication
- CRM prototypes that need product, channel, and campaign-action recommendations
- Projects that seed PostgreSQL from versioned JSON fixtures
- Migrations or rewrites where legacy files must remain byte-for-byte unchanged
- Agent environments with restricted cache, Docker socket, or localhost access

## Examples

An event sequence containing `add_to_cart` without purchase selects a cart-abandonment reminder. A customer tagged `휴면위험` and `할인민감` receives a reactivation coupon, with discounted products receiving a candidate bonus. Both decisions continue to work without any LLM call.

Verification should cover the complete boundary:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests -q
UV_CACHE_DIR=.uv-cache uv run python -m compileall -q app.py crm tests
docker compose exec -T db psql -U crm_user -d shopping_mall_crm \
  -tAc "SELECT count(*), count(DISTINCT event_id), count(DISTINCT customer_id) FROM crm_events"
shasum -a 256 -c /tmp/crm-protected-before.sha256
```

## Related

- [Behavior-based CRM design](../../superpowers/specs/2026-07-11-behavior-crm-recommendation-design.md)
- [Behavior-based CRM implementation plan](../../superpowers/plans/2026-07-11-behavior-crm-recommendation.md)
