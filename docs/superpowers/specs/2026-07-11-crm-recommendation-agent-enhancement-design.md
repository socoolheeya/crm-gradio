# 행동 기반 CRM 추천 에이전트 고도화 설계

## 목표

자연어 캠페인 요청을 분석해 대상 고객을 찾고, 고객별 상품·CRM 액션·채널을 행동 데이터로 랭킹하며, 실행 가능한 구조화 리포트를 생성한다. ETF 추천 노트북의 프로필 분석, Text2SQL, 후보 랭킹, 설명 생성, LangGraph 워크플로우 패턴을 CRM 도메인에 적용한다.

## 노트북에서 채택하는 패턴

- 사용자 요청을 Pydantic 구조화 출력으로 분석
- 하이브리드 고유명사 검색 결과를 Text2SQL 프롬프트에 주입
- 후보 검색과 랭킹을 별도 단계로 분리
- 최종 추천을 검증 가능한 구조화 출력과 Markdown으로 제공
- LangGraph 상태에 단계별 산출물을 보관
- Gradio에서 자연어 입력과 최종 추천 리포트를 제공

노트북의 SQLite, 인메모리 벡터 저장소, LLM 단독 랭킹은 사용하지 않는다. 현재 PostgreSQL, pgvector, BM25/RRF, 결정론적 추천 엔진을 유지한다.

## CRM 요청 모델

`CampaignRequest` 구조화 출력은 다음 필드를 가진다.

- `objective`: 재활성화, 전환, 교차판매, 재구매, 신규 고객 활성화, 일반 추천
- `target_description`: 사용자가 요청한 대상 설명
- `membership_grades`, `regions`, `segments`, `crm_tags`: 명시적 대상 필터
- `preferred_categories`, `excluded_categories`: 상품 카테고리 조건
- `days_since_last_purchase_min`: 휴면 기간 하한
- `customer_limit`: 대상 고객 수, 기본 10, 최대 100
- `recommendations_per_customer`: 고객별 추천 수, 기본 3, 최대 5
- `requested_channel`: app, web, email 또는 자동 선택

LLM 구조화 분석이 실패하면 키워드 기반 기본 요청을 만들고 원문을 보존한다.

## 상태와 그래프

`CRMRecommendationState`는 다음 데이터를 단계별로 저장한다.

- `question`
- `campaign_request`
- `expanded_queries`, `entity_hits`, `entity_info`
- `customer_query`, `customer_query_explanation`
- `candidate_customers`, `candidate_events`
- `recommendations`
- `campaign_report`, `final_markdown`
- `errors`

그래프 흐름:

1. `analyze_campaign_request`: 자연어 요청을 구조화한다.
2. `retrieve_entities`: BM25 + pgvector + 검색어 확장으로 실제 DB 값을 찾는다.
3. `write_customer_query`: `crm_events`만 대상으로 읽기 전용 고객 후보 SQL을 생성한다.
4. `execute_customer_query`: SQL 검증 후 후보 고객 ID와 요약을 조회한다.
5. `rank_recommendations`: 고객별 실제 이벤트와 카탈로그를 기존 결정론적 엔진에 전달한다.
6. `build_campaign_report`: 구조화된 고객 추천과 집계 요약을 만든다.
7. `generate_explanation`: LLM이 결정된 추천을 변경하지 않고 한국어 설명과 캠페인 메시지만 다듬는다.

후보가 없거나 단계가 실패하면 오류 상태로 종료하고 안전한 사용자 메시지를 반환한다.

## 후보 검색

Text2SQL은 `crm_events`만 조회하며 다음 제약을 적용한다.

- 단일 `SELECT` 또는 `WITH ... SELECT`만 허용
- 고객 ID가 결과에 반드시 포함
- `SELECT *` 금지
- 최대 고객 수 100
- 사용자 조건과 하이브리드 검색에서 확인된 정확한 엔터티명 사용
- 데이터 변경, DDL, COPY, 다중 문장 금지

LLM SQL이 실패하면 구조화된 `CampaignRequest`로 안전한 파라미터 바인딩 fallback SQL을 실행한다.

## 랭킹과 추천

LLM은 추천 점수를 결정하지 않는다. 기존 행동 가중치, 최근성, 카테고리 선호, 할인 민감도, 구매 여부, CRM 태그를 사용한다. 캠페인 목적은 결정론적 보정값으로만 반영한다.

- 재활성화: 휴면 기간, 휴면위험, 쿠폰 반응 가점
- 전환: 장바구니, 찜, 상품 조회 후 미구매 가점
- 교차판매: 구매 카테고리와 연관된 미구매 카테고리 가점
- 재구매: 구매 이력과 이전 구매 횟수 가점
- 신규 활성화: 신규 고객과 첫 구매 미완료 가점

각 결과는 고객 ID, 우선순위, 고객 요약, 추천 상품/카테고리, 추천 점수, CRM 액션, 채널, 행동 근거, 발송 메시지를 포함한다.

## 캠페인 리포트

구조화된 리포트는 다음을 포함한다.

- 캠페인 목표와 대상 조건
- 후보 고객 수와 최종 추천 고객 수
- 우선순위 고객 목록
- 고객별 최대 3개 추천
- 추천 액션과 채널 분포
- 행동 근거
- 예상 실행 메시지
- 데이터 한계와 운영 주의사항
- 생성 SQL 및 확장 검색어

Markdown 리포트와 JSON 직렬화 가능한 구조를 동시에 제공한다.

## Gradio

새 `캠페인 추천 에이전트` 탭을 추가한다.

- 자연어 캠페인 요청 입력
- 실행 예제 버튼
- 분석된 요청 조건 표시
- 후보 SQL 표시
- 고객별 추천 테이블
- 최종 Markdown 리포트
- 단계별 오류 안내

기존 고객별 추천, 하이브리드 검색, CRM SQL 에이전트 탭은 유지한다.

## 검증

- 캠페인 요청 구조화 및 fallback 단위 테스트
- 고객 수와 추천 수 경계값 검증
- 읽기 전용 SQL 및 고객 ID 필수 검증
- 후보 없음과 LLM 장애 경로 테스트
- 캠페인 목적별 결정론적 랭킹 테스트
- 추천 필수 필드와 0~100 점수 검증
- LangGraph 노드와 상태 전이 테스트
- Markdown/JSON 출력 테스트
- Gradio 탭 import 테스트
- 실제 PostgreSQL과 OpenAI를 사용한 대표 캠페인 질문 end-to-end 검증
- 전체 테스트, Python 컴파일, DB 행 수, 원본 해시 검증

## 범위 제외

- 실제 메시지 발송
- 추천 성과 학습과 온라인 모델 업데이트
- 협업 필터링 모델 학습
- 사용자 인증과 캠페인 승인 워크플로우
- Compound 문서 생성
