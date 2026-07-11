from crm.agent import build_crm_agent, format_entity_info
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
