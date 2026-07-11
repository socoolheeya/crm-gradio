# CRM 고유명사 벡터 저장 설계

## 목표

기존 `shopping_mall_crm` PostgreSQL과 `crm_events` 1,000건을 유지하면서 CRM 분석에 필요한 고유명사를 추출하고 pgvector 임베딩으로 저장한다.

## 접근 방식

세 가지 방식 중 명시적 컬럼 추출을 사용한다.

- 명시적 컬럼 추출: 값의 의미와 출처가 명확하고 결과가 결정론적이다. 이 설계의 선택안이다.
- LLM 고유명사 추출: 자유 텍스트에는 유용하지만 현재 구조화 데이터에는 비용과 결과 변동성이 불필요하다.
- 전체 이벤트 문서 임베딩: 구현은 단순하지만 개별 상품·캠페인·태그 검색 정밀도가 낮다.

## 추출 범위

`crm_events`에서 NULL과 빈 문자열을 제외하고 다음 값을 중복 제거한다.

- `product_name`: 상품명
- `product_category`: 상품 카테고리
- `campaign_name`: 캠페인명
- `region`: 지역
- `traffic_source`: 유입 경로
- `crm_tags` 배열 원소: CRM 태그
- `estimated_segment`: 고객 세그먼트

## 저장 구조

동일한 `shopping_mall_crm` 데이터베이스에 pgvector 확장을 활성화하고 `crm_entities` 테이블을 만든다.

- `entity_type`, `entity_name`: 엔터티 종류와 원문
- `content`: 임베딩 입력에 사용한 한국어 문장
- `source_count`: 이벤트에서 등장한 횟수
- `metadata JSONB`: 타입별 부가 정보
- `embedding VECTOR(1536)`: `text-embedding-3-small` 임베딩
- `created_at`, `updated_at`: 생성 및 갱신 시각

`(entity_type, entity_name)`을 고유 키로 사용하고 upsert로 반복 적재를 멱등하게 만든다. 코사인 검색용 HNSW 인덱스를 생성한다.

## 데이터 흐름

1. PostgreSQL Docker 이미지를 PostgreSQL 17 호환 pgvector 이미지로 변경한다.
2. 기존 볼륨을 유지한 채 컨테이너만 재생성한다.
3. `CREATE EXTENSION IF NOT EXISTS vector`를 실행한다.
4. `crm_events`에서 고유 엔터티와 등장 횟수를 조회한다.
5. OpenAI `text-embedding-3-small`로 최대 1536차원 임베딩을 배치 생성한다.
6. `crm_entities`에 upsert하고 삭제된 엔터티는 현재 추출 결과와 동기화한다.
7. 코사인 유사도 검색을 검증한다.

## 오류 및 안전성

- 기존 PostgreSQL 볼륨을 삭제하지 않는다. `docker compose down -v`는 사용하지 않는다.
- OpenAI 키를 로그나 DB에 저장하지 않는다.
- 임베딩 API 실패 시 트랜잭션을 롤백해 부분 적재를 방지한다.
- 빈 값과 중복 값은 저장하지 않는다.
- 기존 `crm_events`, `app_old.py`, `etf_database.db`는 수정하지 않는다.

## 검증

- 기존 `crm_events`가 1,000행인지 확인한다.
- `vector` 확장이 활성화됐는지 확인한다.
- 추출된 엔터티 수와 타입별 수를 확인한다.
- `(entity_type, entity_name)` 중복이 0인지 확인한다.
- 모든 행의 임베딩 차원이 1536인지 확인한다.
- 적재를 두 번 실행해도 행 수가 동일한지 확인한다.
- 대표 한국어 검색어로 코사인 유사도 상위 결과를 확인한다.
- 전체 Python 테스트와 컴파일을 실행한다.
