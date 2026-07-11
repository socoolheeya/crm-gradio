from typing import Annotated, Callable, TypedDict

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from crm.db import get_database_url
from crm.hybrid_search import SearchHit, search_live
from crm.sql_guard import validate_read_only_sql


class AgentState(TypedDict, total=False):
    question: str
    expanded_queries: list[str]
    entity_info: str
    query: str
    result: str
    answer: str


class QueryOutput(TypedDict):
    query: Annotated[str, ..., "Syntactically valid read-only PostgreSQL query"]


QUERY_PROMPT = ChatPromptTemplate.from_template("""
Given an input question, create one syntactically correct read-only {dialect} SELECT query.
Unless the user requests a specific count, limit the result to at most {top_k} rows.
Select only relevant columns and never use SELECT *.

Only use the following schema:
{table_info}

Entities found by BM25 + pgvector hybrid retrieval:
{entity_info}

Matching rules:
- Prefer exact entity_name values shown above for filters.
- Use only columns present in the schema.
- Use PostgreSQL syntax.
- Return only a SELECT or WITH ... SELECT query.
- Never generate INSERT, UPDATE, DELETE, DDL, COPY, or multiple statements.

Question: {input}
""")


def format_entity_info(hits: list[SearchHit]) -> str:
    if not hits:
        return "No matching CRM entities found."
    return "\n".join(
        f"- {hit.entity_type}: {hit.entity_name} (count={hit.source_count}, "
        f"BM25={hit.bm25_score:.4f}, VECTOR={hit.vector_score:.4f}, RRF={hit.rrf_score:.6f}, "
        f"queries={', '.join(hit.matched_queries)})"
        for hit in hits
    )


def build_crm_agent(
    db,
    llm,
    entity_search: Callable[[str], tuple[list[SearchHit], list[str]]],
):
    def retrieve_entities(state: AgentState):
        hits, expanded = entity_search(state["question"])
        return {"entity_info": format_entity_info(hits), "expanded_queries": expanded}

    def write_query(state: AgentState):
        prompt = QUERY_PROMPT.invoke({
            "dialect": db.dialect,
            "top_k": 10,
            "table_info": db.get_table_info(["crm_events"]),
            "input": state["question"],
            "entity_info": state["entity_info"],
        })
        result = llm.with_structured_output(QueryOutput).invoke(prompt)
        return {"query": validate_read_only_sql(result["query"])}

    def execute_query(state: AgentState):
        safe_query = validate_read_only_sql(state["query"])
        return {"result": db.run(safe_query)}

    def generate_answer(state: AgentState):
        response = llm.invoke(
            "다음 CRM 분석 질문에 SQL 결과만 근거로 한국어로 답하세요. 수치와 추천 근거를 명확히 설명하세요.\n\n"
            f"질문: {state['question']}\n확장 검색어: {state.get('expanded_queries', [])}\n"
            f"SQL: {state['query']}\nSQL 결과: {state['result']}"
        )
        return {"answer": response.content}

    builder = StateGraph(AgentState)
    builder.add_node("retrieve_entities", retrieve_entities)
    builder.add_node("write_query", write_query)
    builder.add_node("execute_query", execute_query)
    builder.add_node("generate_answer", generate_answer)
    builder.add_edge(START, "retrieve_entities")
    builder.add_edge("retrieve_entities", "write_query")
    builder.add_edge("write_query", "execute_query")
    builder.add_edge("execute_query", "generate_answer")
    builder.add_edge("generate_answer", END)
    return builder.compile()


def create_default_agent():
    from langchain_community.utilities import SQLDatabase

    db = SQLDatabase.from_uri(get_database_url(), include_tables=["crm_events"])
    llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0)
    return build_crm_agent(db, llm, lambda question: search_live(question, limit=10))
