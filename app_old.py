from enum import Enum
from typing import List, TypedDict, Annotated
from pydantic import BaseModel, Field
from decimal import Decimal
import ast
import re

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_community.tools import QuerySQLDatabaseTool
from langchain_community.utilities import SQLDatabase
from langchain_core.tools import tool


from langgraph.graph import StateGraph, START, END

import gradio as gr


##################################################################
# 환경 설정 / 데이터베이스 연결
##################################################################
from dotenv import load_dotenv
load_dotenv()

db = SQLDatabase.from_uri("sqlite:///etf_database.db")

##################################################################
# 고유명사 DB 검색
##################################################################

def query_as_list(db, query):
    res = db.run(query)
    res = [el for sub in ast.literal_eval(res) for el in sub if el]
    res = [re.sub(r"\b\d+\b", "", string).strip() for string in res]
    return list(set(res))

etfs = query_as_list(db, "SELECT DISTINCT 종목명 FROM ETFs")
fund_managers = query_as_list(db, "SELECT DISTINCT 운용사 FROM ETFs")
underlying_assets = query_as_list(db, "SELECT DISTINCT 기초지수 FROM ETFs")

# 임베딩 모델 생성
embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

# 임베딩 벡터 저장소 생성
vector_store = InMemoryVectorStore(embeddings)

# ETF 종목명과 운용사를 임베딩 벡터로 변환
_ = vector_store.add_texts(etfs + fund_managers + underlying_assets)
retriever = vector_store.as_retriever(search_kwargs={"k": 20})

# 검색 프롬프트 생성
description = (
    "Use to look up values to filter on. Input is an approximate spelling "
    "of the proper noun, output is valid proper nouns. Use the noun most "
    "similar to the search."
)

# 검색 도구 생성 - 하이브리드 검색기 사용
@tool("search_proper_nouns")
def entity_retriever_tool(query: str) -> str:
    """
    Use to look up values to filter on. Input is an approximate spelling 
    of the proper noun, output is valid proper nouns. Use the noun most 
    similar to the search.
    """
    docs = retriever.invoke(query)
    return "\n\n".join([doc.page_content for doc in docs])

##################################################################
# 상태 정보 타입 정의
##################################################################
class State(TypedDict):
    question: str           # 사용자 입력 질문
    user_profile: dict     # 사용자 프로필 정보
    query: str             # 생성된 SQL 쿼리
    candidates: list       # 후보 ETF 목록
    rankings: list         # 순위가 매겨진 ETF 목록
    explanation: str       # 추천 이유 설명
    final_answer: str      # 최종 추천 답변



##################################################################
# 사용자 프로필 분석
##################################################################
class RiskTolerance(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate" 
    AGGRESSIVE = "aggressive"

class InvestmentHorizon(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"

class InvestmentProfile(BaseModel):
    risk_tolerance: RiskTolerance = Field(
        description="투자자의 위험 성향 (conservative/moderate/aggressive)"
    )
    investment_horizon: InvestmentHorizon = Field(
        description="투자 기간 (short/medium/long)"
    )
    investment_goal: str = Field(
        description="투자의 주요 목적 설명"
    )
    preferred_sectors: List[str] = Field(
        description="선호하는 투자 섹터 목록"
    )
    excluded_sectors: List[str] = Field(
        description="투자를 원하지 않는 섹터 목록"
    )
    monthly_investment: int = Field(
        description="월 투자 가능 금액 (원)"
    )


# 사용자 프로필 분석 프롬프트
PROFILE_TEMPLATE= """
사용자의 질문을 분석하여 투자 프로필을 생성해주세요.

사용자 질문: {question}
"""

profile_prompt = ChatPromptTemplate.from_template(PROFILE_TEMPLATE)

# 사용자 프로필 분석 모델 생성
llm = ChatOpenAI(model="gpt-4.1-mini")
profile_llm = llm.with_structured_output(InvestmentProfile)

# 사용자 프로필 분석 함수
def analyze_profile(state: State) -> dict:
    """사용자 질문을 분석하여 투자 프로필 생성"""
    prompt = profile_prompt.invoke({"question": state["question"]})
    response = profile_llm.invoke(prompt)
    return {"user_profile": dict(response)}


##################################################################
# SQL 쿼리 생성
##################################################################

# SQL Query Generation Template
QUERY_TEMPLATE = """
Given an input question and investment profile, create a syntactically correct {dialect} query to run. Unless specified, limit your query to at most {top_k} results. Order the results by most relevant columns based on the investment profile.

Never query for all columns from a specific table, only ask for relevant columns given the question and investment criteria.

Pay attention to use only the column names you can see in the schema description. Be careful to not query for columns that do not exist. Also, pay attention to which column is in which table.

Available tables:
{table_info}

Entity relationships:
{entity_info}

## Matching Guidelines
- Use exact matches when comparing entity names
- Check for historical name variations if available
- Apply case-sensitive matching for official names
- Handle both Korean and English entity names when present

Investment Profile:
{user_profile}

Question: {input}

## Constraints
1. Use only existing columns
2. Query only necessary columns (no SELECT *)
3. Follow correct table relationships
4. Consider performance and indexing
"""

# SQL Query Generation Prompt Template
query_prompt_template = ChatPromptTemplate.from_template(QUERY_TEMPLATE)

# SQL Query Output
class QueryOutput(TypedDict):
    """Generated SQL query."""
    query: Annotated[str, ..., "Syntactically valid SQL query."]
    explanation: Annotated[str, ..., "Query explanation and selection criteria (in 한국어)"]


def write_query(state: State):
    """Generate SQL query to fetch information."""
    prompt = query_prompt_template.invoke(
        {
            "dialect": db.dialect,
            "top_k": 10,
            "table_info": db.get_table_info(),
            "input": state["question"],
            "entity_info": entity_retriever_tool.invoke(state["question"]),
            "user_profile": state["user_profile"],
        }
    )
    structured_llm = ChatOpenAI(model="gpt-4.1").with_structured_output(QueryOutput)
    result = structured_llm.invoke(prompt)
    return {"query": result["query"], "explanation": result["explanation"]}


##################################################################
# 후보 ETF 검색
##################################################################

def execute_query(state: State) -> dict:
    """SQL 쿼리 실행하여 후보 ETF 검색"""
    execute_query_tool = QuerySQLDatabaseTool(db=db)
    results = execute_query_tool.invoke(state["query"])
    return {"candidates": results}

##################################################################
# ETF 순위 매기기
##################################################################

RANKING_TEMPLATE = """
Rank the following ETF candidates based on the user's investment profile and return the top 3(three) ETFs.
Consider these factors when ranking:

1. 수익률
2. 변동성
3. 순자산총액
4. 총보수
5. User Profile matching score

User Profile:
{user_profile}

Candidate ETFs:
{candidates}

Table Info:
(table_info)
"""

# ETF Ranking Prompt Template
ranking_prompt = ChatPromptTemplate.from_template(RANKING_TEMPLATE)

# ETF Ranking Output
class ETFRanking(TypedDict):
    """Individual ETF ranking result"""
    rank: Annotated[int, ..., "Ranking position (1-5)"]
    etf_code: Annotated[str, ..., "ETF 종목코드 (6-digit)"]
    etf_name: Annotated[str, ..., "ETF 종목명"]
    score: Annotated[float, ..., "Composite score (0-100)"]
    ranking_reason: Annotated[str, ..., "Explanation for the ranking (in 한국어)"]

class ETFRankingResult(TypedDict):
    """Ranked ETFs"""
    rankings: List[ETFRanking]

# ETF Ranking Function
def rank_etfs(state: State) -> dict:
    """Rank ETF candidates based on user's investment profile"""
    prompt = ranking_prompt.invoke(
        {
            "user_profile": state["user_profile"],
            "candidates": state["candidates"],
        }
    )
    structured_llm = ChatOpenAI(model="gpt-4.1").with_structured_output(ETFRankingResult)
    results = structured_llm.invoke(prompt)

    return {"rankings": results}



##################################################################
# 추천 이유 설명
##################################################################

EXPLANATION_TEMPLATE = """
Please provide a comprehensive explanation for the recommended ETFs based on the user's investment profile.


[RECOMMENDATION EXPLANATION (Examples)]
1. ETF Characteristics
   - Investment strategy and approach
   - Historical performance overview
   - Fee structure and efficiency
   - Underlying assets and diversification

2. Profile Fit Analysis
   - Alignment with risk tolerance
   - Match with investment horizon
   - Sector preference compatibility
   - Investment goal contribution

3. Portfolio Construction
   - Recommended allocation percentages
   - Diversification benefits
   - Rebalancing considerations
   - Implementation strategy

4. Risk Considerations
   - Market risk factors
   - Specific ETF risks
   - Economic scenario impacts
   - Monitoring requirements

--------------------------------------------

[User Profile]
{user_profile}

[Selected ETFs]
{rankings}
"""

# 추천 설명 프롬프트
explanation_prompt = ChatPromptTemplate.from_template(EXPLANATION_TEMPLATE)


# 추천 설명 출력 스키마
class ETFRecommendation(BaseModel):
    """Individual ETF recommendation details"""
    etf_code: str = Field(..., description="ETF 종목코드 (6-digit)")
    etf_name: str = Field(..., description="ETF 종목명")
    allocation: Decimal = Field(..., description="Recommended allocation % (0-100)")
    description: str = Field(..., description="ETF description and investment strategy (in 한국어)")
    key_points: List[str] = Field(..., description="Key investment points (in 한국어)")
    risks: List[str] = Field(..., description="Risk factors to consider (in 한국어)")

class RecommendationExplanation(BaseModel):
    """ETF recommendation explanation with markdown formatting"""
    overview: str = Field(..., description="Overall strategy explanation (in 한국어)")
    recommendations: List[ETFRecommendation] = Field(..., description="ETF details")
    considerations: List[str] = Field(..., description="Important considerations (in 한국어)")

    # 마크다운 포맷으로 출력
    def to_markdown(self) -> str:
        """Convert explanation to markdown format"""
        markdown = [
            "# ETF 포트폴리오 추천",
            "",
            "## 투자 전략 개요",
            self.overview,
            "",
            "## 추천 ETF 포트폴리오",
            ""
        ]
        
        # 포트폴리오 구성 비율
        markdown.extend([
            "| ETF | 종목코드 | 추천비중 |",
            "|-----|----------|----------|"
        ])
        
        for rec in self.recommendations:
            markdown.append(
            f"| {rec.etf_name} | {rec.etf_code} | {rec.allocation}% |"
            )
        
        # ETF 상세 설명
        markdown.append("\n## ETF 상세 설명\n")
        
        for rec in self.recommendations:
            markdown.extend([
                f"### {rec.etf_name} ({rec.etf_code})",
                rec.description,
                "",
                "**주요 투자 포인트:**",
                "".join([f"\n* {point}" for point in rec.key_points]),
                "",
                "**투자 위험:**",
            "".join([f"\n* {risk}" for risk in rec.risks]),
            ""
            ])
        
        # 투자 리스크 고려사항
        markdown.extend([
            "## 투자 시 고려사항",
            "".join([f"\n* {item}" for item in self.considerations]),
            ""
        ])
        
        return "\n".join(markdown)


# 추천 설명 생성 함수
def generate_explanation(state: dict) -> dict:
    """Generate structured ETF recommendation explanation"""
    # 프롬프트 생성
    prompt = explanation_prompt.invoke({
        "rankings": state["rankings"],
        "user_profile": state["user_profile"]
    })

    # 구조화된 출력 생성
    structured_llm = llm.with_structured_output(RecommendationExplanation)
    response = structured_llm.invoke(prompt)

    return {"final_answer": {
        "explanation": response.model_dump(), 
        "markdown": response.to_markdown()
    }}


##################################################################
# ETF 추천 봇 - 상태 그래프 생성
##################################################################

# 상태 그래프 생성
graph_builder = StateGraph(State)

graph_builder.add_node("analyze_profile", analyze_profile)
graph_builder.add_node("write_query", write_query)
graph_builder.add_node("execute_query", execute_query)
graph_builder.add_node("rank_etfs", rank_etfs)
graph_builder.add_node("generate_explanation", generate_explanation)

graph_builder.add_edge(START, "analyze_profile")
graph_builder.add_edge("analyze_profile", "write_query")
graph_builder.add_edge("write_query", "execute_query")
graph_builder.add_edge("execute_query", "rank_etfs")
graph_builder.add_edge("rank_etfs", "generate_explanation")
graph_builder.add_edge("generate_explanation", END)

graph = graph_builder.compile()


##################################################################
# ETF 추천 봇 - 메인 함수
##################################################################

def process_message(message: str) -> str:

    try:
        etf_recommendation = graph.invoke(
            {"question": message}
        )
        return etf_recommendation["final_answer"]["markdown"]
    
    except Exception as e:
        return f"""
# 오류가 발생했습니다
죄송합니다. 요청을 처리하는 중에 문제가 발생했습니다.

오류 내용: {str(e)}

다시 시도해주시거나, 질문을 다른 방식으로 작성해주세요.
"""

    
def answer_invoke(message: str, history: List) -> str:
    return process_message(message)   # 메시지 처리 함수 호출 - 대화 이력 미사용

# Create Gradio interface
demo = gr.ChatInterface(
    fn=answer_invoke,
    title="맞춤형 ETF 추천 어시스턴트",
    description="""
    투자 성향과 목표에 맞는 ETF를 추천해드립니다.
    
    다음과 같은 정보를 포함하여 질문해주세요:
    - 투자 목적
    - 투자 기간
    - 위험 성향
    - 선호/제외 섹터
    - 월 투자 가능 금액
    
    예시) "월 100만원 정도를 3년 이상 장기 투자하고 싶고, IT와 헬스케어 섹터를 선호합니다. 
          보수적인 투자를 선호하며, 담배 관련 기업은 제외하고 싶습니다."
    """,
    examples=[
        """20대 후반의 대학생입니다. 
    월 50만원 정도를 1년 이상 장기 투자하고 싶고,
    환율과 금리에 관심이 있습니다.
    고위험 고수익을 추구하며, ESG 요소도 고려하고 싶습니다.
    적합한 ETF를 추천해주세요."""
    ],
    # type="messages",
)

# 인터페이스 실행
if __name__ == "__main__":
    demo.launch()