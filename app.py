from typing import Any

import gradio as gr
from dotenv import load_dotenv

from crm.db import create_db_engine
from crm.recommendations import recommend_for_customer
from crm.repository import CRMRepository

load_dotenv()


def _recommend(repository: CRMRepository, customer_id: str):
    if not customer_id:
        return "고객을 선택해 주세요.", [], ""
    events = repository.get_customer_events(customer_id)
    if not events:
        return "고객 행동 데이터가 없습니다.", [], ""
    recommendations = recommend_for_customer(events, repository.get_catalog_events())
    latest = events[0]
    tags = sorted({tag for e in events for tag in (e.get("crm_tags") or [])})
    summary = (f"### {customer_id}\n- 등급: {latest.get('membership_grade')}\n"
               f"- 세그먼트: {latest.get('estimated_segment')}\n- 이벤트: {len(events)}건\n"
               f"- CRM 태그: {', '.join(tags) or '없음'}")
    table = [[r.product_name, r.category, r.score, r.action, r.channel, " / ".join(r.evidence)] for r in recommendations]
    message = recommendations[0].message if recommendations else "추천 후보가 없습니다."
    return summary, table, message


def build_demo(repository: CRMRepository | None = None) -> gr.Blocks:
    repo = repository
    with gr.Blocks(title="행동 기반 CRM 추천 시스템") as demo:
        gr.Markdown("# 행동 기반 CRM 추천 시스템\n고객 행동을 근거로 상품과 CRM 액션을 추천합니다.")
        with gr.Tab("고객별 추천"):
            customer_id = gr.Textbox(label="고객 ID", placeholder="예: CUST_0180")
            button = gr.Button("추천 분석", variant="primary")
            summary = gr.Markdown()
            result = gr.Dataframe(headers=["추천 상품", "카테고리", "점수", "CRM 액션", "채널", "행동 근거"], interactive=False)
            message = gr.Textbox(label="추천 메시지", lines=3)

            def run(customer: str):
                try:
                    active_repo = repo or CRMRepository(create_db_engine())
                    return _recommend(active_repo, customer.strip())
                except Exception:
                    return "PostgreSQL 연결을 확인하세요. `docker compose up -d db` 후 데이터를 적재해야 합니다.", [], ""

            button.click(run, customer_id, [summary, result, message])
        with gr.Tab("우선 연락 고객"):
            gr.Markdown("고객별 추천 탭에서 고객 행동과 추천 우선순위를 확인할 수 있습니다.")
        with gr.Tab("하이브리드 검색"):
            hybrid_query = gr.Textbox(label="검색 질문", placeholder="예: 휴면 고객 할인 캠페인")
            hybrid_limit = gr.Slider(1, 20, value=10, step=1, label="검색 결과 수")
            hybrid_button = gr.Button("BM25 + 벡터 검색", variant="primary")
            expanded = gr.Textbox(label="원문 및 확장 검색어", interactive=False)
            hybrid_results = gr.Dataframe(
                headers=["타입", "고유명사", "등장 수", "BM25", "벡터 유사도", "RRF", "매칭 검색어"],
                interactive=False,
            )

            def run_hybrid(query: str, limit: int):
                if not query.strip():
                    return "검색어를 입력해 주세요.", []
                try:
                    from crm.hybrid_search import search_live

                    hits, queries = search_live(query.strip(), int(limit))
                    rows = [[
                        hit.entity_type, hit.entity_name, hit.source_count,
                        round(hit.bm25_score, 4), round(hit.vector_score, 4), round(hit.rrf_score, 6),
                        " / ".join(hit.matched_queries),
                    ] for hit in hits]
                    return " | ".join(queries), rows
                except Exception:
                    return "PostgreSQL 및 OpenAI 설정을 확인해 주세요.", []

            hybrid_button.click(run_hybrid, [hybrid_query, hybrid_limit], [expanded, hybrid_results])

        with gr.Tab("CRM SQL 에이전트"):
            agent_question = gr.Textbox(
                label="CRM 분석 질문",
                placeholder="예: 휴면위험 고객이 가장 많이 관심을 보인 상품 카테고리는?",
            )
            agent_button = gr.Button("에이전트 실행", variant="primary")
            agent_answer = gr.Markdown()
            agent_sql = gr.Code(label="생성된 읽기 전용 SQL", language="sql")
            agent_queries = gr.Textbox(label="검색에 사용된 확장어", interactive=False)

            def run_agent(question: str):
                if not question.strip():
                    return "질문을 입력해 주세요.", "", ""
                try:
                    from crm.agent import create_default_agent

                    state = create_default_agent().invoke({"question": question.strip()})
                    return state["answer"], state["query"], " | ".join(state.get("expanded_queries", []))
                except Exception as error:
                    return f"에이전트 실행 오류: {error}", "", ""

            agent_button.click(run_agent, agent_question, [agent_answer, agent_sql, agent_queries])
    return demo


if __name__ == "__main__":
    build_demo().launch()
