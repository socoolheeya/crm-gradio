import pytest

from crm.agent import AgentQueryError, QUERY_PROMPT, build_crm_agent, execute_read_only_query, format_entity_info
from crm.hybrid_search import SearchHit


def test_entity_info_formats_hybrid_diagnostics():
    hit = SearchHit(
        "crm_tag", "휴면위험", "CRM 태그: 휴면위험", 156,
        bm25_score=2.5, vector_score=0.81, rrf_score=0.03,
        matched_queries=("휴면 고객", "재활성화"),
    )
    info = format_entity_info([hit])
    assert "휴면위험" in info
    assert "BM25=2.5000" in info
    assert "VECTOR=0.8100" in info


def test_agent_graph_contains_safe_sql_flow():
    graph = build_crm_agent(db=object(), llm=object(), entity_search=lambda _query: ([], ["질문"]))
    nodes = set(graph.get_graph().nodes)
    assert {"retrieve_entities", "write_query", "execute_query", "generate_answer"} <= nodes


class FailingDatabase:
    def run(self, _query):
        raise RuntimeError("postgresql://admin:secret@database/crm")


def test_execute_read_only_query_reports_validation_error():
    with pytest.raises(AgentQueryError) as captured:
        execute_read_only_query(FailingDatabase(), "DELETE FROM crm_events")

    assert captured.value.stage == "validation"
    assert str(captured.value) == "생성된 SQL이 읽기 전용 정책을 충족하지 않습니다."


def test_execute_read_only_query_hides_database_error_details():
    with pytest.raises(AgentQueryError) as captured:
        execute_read_only_query(FailingDatabase(), "SELECT customer_id FROM crm_events")

    assert captured.value.stage == "execution"
    assert str(captured.value) == "CRM 데이터를 조회하는 중 오류가 발생했습니다."
    assert "secret" not in str(captured.value)


def test_text_to_sql_prompt_contains_accuracy_rules():
    prompt = QUERY_PROMPT.invoke({
        "dialect": "postgresql",
        "top_k": 10,
        "table_info": "crm_events(customer_id, event_time)",
        "entity_info": "No matching CRM entities found.",
        "input": "최근 고객 행동을 알려줘",
    }).to_string()

    assert "customer_id" in prompt
    assert "CURRENT_DATE" in prompt
    assert "GROUP BY" in prompt
    assert "Do not invent" in prompt
