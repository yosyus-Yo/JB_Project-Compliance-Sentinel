# References — 구현 시 참조 자료

## 로컬 전략 문서

| 문서 | 참조 포인트 |
|---|---|
| `C:\Users\inhiy\Downloads\jb-fin-ai-strategy-report.html` | 준법자문가 최우선 추천, 판단·행동·검증 3단계, 6인 보드, verifier loop |
| `C:\Users\inhiy\Downloads\jb_finai_winning_strategy.html` | Compliance Sentinel++, ComplyCore/AuditOne/AgentLogs/PolicyMesh 역할 분해 |
| `C:\Users\inhiy\Downloads\jb_finai_reinforcement.html` | LangGraph, Qdrant, Presidio, DeepEval, Phoenix, Promptfoo, AgentCompiler 활용 위치 |

## 공식/1차 출처 우선순위

### LangGraph

- StateGraph, conditional edges, persistence, checkpointing, human-in-the-loop를 확인한다.
- 참조 후보:
  - https://docs.langchain.com/oss/python/langgraph/persistence
  - https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/
  - https://langchain-ai.github.io/langgraph/tutorials/get-started/4-human-in-the-loop/

### 법령정보센터 Open API

- 법령 목록/본문/조문 조회 API를 확인한다.
- API 인증값, `target=law`, 출력 형식 JSON/XML, 검색 범위, 현행법령 본문 조회를 확인한다.
- 참조 후보:
  - https://open.law.go.kr/LSO/openApi/guideList.do
  - https://open.law.go.kr/LSO/openApi/guideResult.do
  - https://open.law.go.kr/main.do

### Qdrant

- hybrid query, named vectors, dense+sparse 검색, RRF/reranking을 확인한다.
- 참조 후보:
  - https://qdrant.tech/documentation/search/hybrid-queries/index.md
  - https://qdrant.tech/documentation/tutorials-and-examples/cloud-inference-hybrid-search
  - https://qdrant.tech/documentation/tutorials-search-engineering/reranking-hybrid-search/

### Microsoft Presidio

- Analyzer/Anonymizer, custom recognizer, anonymization operators를 확인한다.
- 한국형 주민번호/계좌번호/전화번호는 custom recognizer가 필요할 수 있다.
- 참조 후보:
  - https://microsoft.github.io/presidio/anonymizer/
  - https://microsoft.github.io/presidio/samples
  - https://github.com/microsoft/presidio/blob/main/docs/installation.md

### 평가/관측성

- LangSmith 또는 Langfuse: LangGraph trace, node-by-node state diff
- DeepEval: faithfulness, hallucination, answer relevancy, tool correctness
- RAGAS/Phoenix: context precision/recall, faithfulness
- Promptfoo: red-team, prompt injection, fake citation tests

### 참고 법령/규정

- 개인정보보호법
- 신용정보의 이용 및 보호에 관한 법률
- 금융소비자보호법
- 전자금융거래법
- 전자금융감독규정
- 금융광고/상품설명 관련 감독규정 및 가이드라인

### JB 도메인 자료

- 전북은행/광주은행 상품 설명서 및 약관
- JB우리캐피탈 상품/약관
- JB자산운용 상품 자료
- JB금융지주 IR/공시 자료
- 샘플 약관/광고 문구

## 참조 원칙

1. 공식 문서와 원문 법령을 1차 근거로 사용한다.
2. 블로그/요약문은 보조 자료로만 사용한다.
3. 법령 조항은 반드시 원문 조회 또는 canonical local cache로 검증한다.
4. AgentCompiler 성능 수치는 실측 전까지 projected/simulated로 라벨링한다.
