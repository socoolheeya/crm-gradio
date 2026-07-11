# 행동 기반 CRM 추천 시스템

쇼핑몰 행동 이벤트 1,000건을 PostgreSQL에 적재하고 고객별 상품과 CRM 액션을 추천하는 Gradio 앱입니다.

## 실행

```bash
cp .env.example .env
docker compose up -d db
UV_CACHE_DIR=.uv-cache uv run python -m crm.loader shopping_mall_crm_behavior_sample_1000.json
UV_CACHE_DIR=.uv-cache uv run python app.py
```

앱에서 고객 ID(예: `CUST_0180`)를 입력하면 추천 상품, 점수, CRM 액션, 채널, 행동 근거와 메시지를 확인할 수 있습니다. 규칙 기반 추천은 OpenAI API 키 없이 동작합니다.

## CRM 고유명사 벡터 저장

같은 PostgreSQL 안의 `crm_entities` 테이블에 상품명, 카테고리, 캠페인명, 지역, 유입 경로, CRM 태그, 고객 세그먼트를 저장합니다. `.env`에 `OPENAI_API_KEY`가 필요합니다.

```bash
UV_CACHE_DIR=.uv-cache uv run python -m crm.entity_vectors load
UV_CACHE_DIR=.uv-cache uv run python -m crm.entity_vectors search "휴면 고객 할인 캠페인" --limit 5
```

적재 명령은 `(entity_type, entity_name)` 기준으로 동기화되므로 반복 실행해도 중복되지 않습니다. PostgreSQL 컨테이너는 pgvector 이미지를 사용하며 기존 관계형 데이터와 벡터 데이터를 하나의 DB에서 관리합니다.

## BM25 + pgvector 하이브리드 검색

원문과 LLM 확장 검색어를 한국어 BM25와 pgvector 코사인 검색에 각각 전달하고 RRF로 순위를 결합합니다.

```bash
UV_CACHE_DIR=.uv-cache uv run python -m crm.hybrid_search "휴면 고객 할인 캠페인" --limit 10
```

Gradio의 `하이브리드 검색` 탭은 BM25 점수, 벡터 유사도, RRF 점수와 매칭 검색어를 표시합니다. `CRM SQL 에이전트` 탭은 하이브리드 검색 결과를 고유명사 컨텍스트로 사용해 읽기 전용 PostgreSQL 쿼리를 만들고 실행한 뒤 한국어 답변을 생성합니다.

## 검증

```bash
UV_CACHE_DIR=.uv-cache uv run pytest -q
UV_CACHE_DIR=.uv-cache uv run python -m compileall -q app.py crm tests
```

`docker compose down -v`는 PostgreSQL 데이터 볼륨을 영구 삭제하므로 초기화가 꼭 필요한 경우에만 사용하세요.
