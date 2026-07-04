# 심의 중 7단계 실시간 Loader — LangGraph astream 설계

> **목표**: 심의가 진행되는 동안 UI가 "지금 어느 단계(노드)를 실행 중인지" 실시간 표시.
> **경로**: A안 — LangGraph 활성화 + astream_events 스트리밍 (사용자 선택 2026-06-04).
> **상태**: 설계 확정, 단계별 구현 대기.

## 확인된 현재 구조 (검증됨)

| 항목 | 현재 | 근거 |
|------|------|------|
| langgraph 버전 | 0.5.0 (astream_events 지원) | `importlib.metadata` |
| LangGraph 그래프 | marketing_langgraph_adapter.py 8노드 (선형) | StateGraph add_node 8 |
| engine.py 그래프 호출 | `graph.invoke(...)` (동기, 일괄) | engine.py:84,100 |
| LangGraph 활성화 | `USE_LANGGRAPH=1` opt-in (현재 OFF) | api.py / server.ts |
| worker 심의 엔드포인트 | `@app.post("/review")` (JSON 일괄) | api.py:83 |
| server.ts 심의 | `app.post('/api/review')` → worker fetch → JSON | server.ts:461 |
| 스트리밍 (astream/SSE) | **전혀 없음** | grep 0건 |

## 3계층 스트리밍 아키텍처

```
[Python worker] engine.py astream_events()
  → 8노드 진입/완료 이벤트 방출 (on_chain_start / on_chain_end)
  → FastAPI StreamingResponse (SSE) : @app.post("/review/stream")
       ↓ (text/event-stream)
[server.ts] /api/review/stream — worker SSE를 프론트로 relay
       ↓ (text/event-stream)
[프론트] WorkflowSteps.tsx — EventSource 구독 → 현재 노드 하이라이트
```

## 노드 → UI 7단계 매핑

LangGraph 8노드를 UI 표시 단계로 매핑 (final_report는 완료 표시):
| # | LangGraph 노드 | UI 단계 라벨 |
|---|---|---|
| 1 | content_intake | 콘텐츠 입력·정규화 |
| 2 | understand_content | 언어·상품유형 분류 |
| 3 | memory_review | 과거 사례·법률 RAG 조회 |
| 4 | llm_advisory_board | 6인 자문 보드 심의 |
| 5 | synthesize | 종합 판정 |
| 6 | independent_validation | 독립 검증 |
| 7 | human_review_gate | 사람 검토 판정 |
| (완료) | final_report | 보고서 생성 |

## 태스크 분해 (5단계, 각 단계 검증 후 진행)

### T1 — engine.py astream streaming 함수
- **파일**: `src/compliance_sentinel/engine.py`
- **작업**: `async def astream_review_events(input_text)` 추가 — `graph.astream_events(..., version="v2")`로 노드 `on_chain_start`/`on_chain_end` 이벤트를 `{node, status}` dict로 yield. 기존 `invoke` 경로는 유지(fallback).
- **검증**: deterministic_mode 또는 mock LLM으로 8노드 이벤트가 순서대로 yield되는지 확인 (LLM 비용 없이 노드 전이만).

### T2 — worker SSE 엔드포인트
- **파일**: `src/compliance_sentinel/api.py`
- **작업**: `@app.post("/review/stream")` — `StreamingResponse(media_type="text/event-stream")`로 T1의 이벤트를 `data: {json}\n\n` 형식 방출. 마지막에 final_report를 `event: result`로 전송.
- **검증**: `curl -N` 으로 SSE 이벤트 스트림 확인.

### T3 — server.ts SSE relay
- **파일**: `compliance-sentinel/server.ts`
- **작업**: `app.post('/api/review/stream')` — worker `/review/stream` SSE를 프론트로 파이프(relay). `res.setHeader('Content-Type','text/event-stream')` + worker 응답 스트림 pipe.
- **검증**: `curl -N http://localhost:3000/api/review/stream` 이벤트 확인.

### T4 — 프론트 EventSource 수신
- **파일**: `compliance-sentinel/src/components/WorkflowSteps.tsx` + 호출처(App.tsx)
- **작업**: 심의 시작 시 EventSource(또는 fetch ReadableStream)로 `/api/review/stream` 구독 → `node` 이벤트 수신 시 해당 단계 하이라이트, `result` 이벤트 시 완료 + 결과 표시.
- **검증**: 브라우저에서 jb-test-ad.md 재심의 → 단계가 실시간으로 하나씩 활성화되는지 육안 확인.

### T5 — 활성화 + 통합 테스트
- **작업**: `USE_LANGGRAPH=1` 설정 (server.ts dev 환경) + 전체 플로우 통합 테스트. astream 실패 시 기존 invoke/deterministic fallback 보존 확인.
- **검증**: 실제 심의 1회 + loader 동작 + 결과 정확성 동시 확인.

## 리스크 / 주의

- **준법 critical**: 심의 결과 정확성이 최우선. 스트리밍은 "표시"만 추가, 심의 로직 불변 보장.
- **fallback 보존**: astream 실패 시 기존 invoke/deterministic로 자동 복귀 (engine.py 기존 설계 유지).
- **async 전환**: engine.py가 동기 구조라 streaming 함수는 별도 async 경로로 추가 (기존 sync invoke 불변).
- **비용**: astream도 동일 LLM 호출 (8 calls). 스트리밍이 비용 추가 아님 (표시만).
- **검증 난이도**: T4는 브라우저 육안 확인 필요 (자동 테스트 어려움).

## 진행 원칙

- 각 태스크(T1~T5) **완료+검증 후** 다음 단계 (SUCCESS_PATTERN #12 마이크로 분해).
- T1~T3(백엔드)은 curl로 검증 가능, T4(프론트)는 브라우저 확인.
- 준법 로직(심의 결과)은 일절 변경하지 않음 — 스트리밍 표시 레이어만 추가.
