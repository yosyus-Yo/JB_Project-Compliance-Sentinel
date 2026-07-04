# Spec — OpenTelemetry / LangSmith Wire

> PDF 지정주제 2 우선순위 #5. 관측성 보강 (PDF "모니터링" 명시 부재이나 운영 안정성).

## 1. 목적

Compliance Sentinel의 워크플로우 trace(`state.trace`)와 LLM 호출(`state.llm_calls`)을 **OpenTelemetry** 표준 + **LangSmith**로 export하여 외부 dashboard에서 관측 가능하게 한다. PDF "심의 지연" + "심의 품질 편차" (line 80) 운영 모니터링.

## 2. 현황

- `state.trace`: list[dict] (각 node 호출 추적)
- `state.llm_calls`: list[dict] (model/cost/latency 포함)
- `audit_log`: JSONL (단일 audit_log_id 단위)
- **외부 telemetry export 부재** — 모두 in-memory + local audit only

## 3. 범위

### In Scope (MVP)

- OpenTelemetry span 생성 (각 trace node가 span)
- env: `OTEL_EXPORTER_OTLP_ENDPOINT` 설정 시 자동 export, 없으면 no-op
- LangSmith integration (env: `LANGSMITH_API_KEY` 시 활성)
- span attributes: audit_log_id, approval_status, risk_level, board_diagnostics summary
- 비용/latency metric: 각 LLM 호출별

### Out of Scope

- 자체 dashboard UI (Grafana/Jaeger는 사용자 인프라)
- 다중 서비스 trace context propagation (단일 서비스 가정)
- alerting 규칙 (별도 spec)

## 4. Acceptance Criteria

| AC | 내용 | 검증 |
|---|---|---|
| AC-OTEL-001 | `telemetry.py` 신규 모듈 + `init_tracer()` / `span()` helper | unit test |
| AC-OTEL-002 | env 부재 시 no-op (회귀 0 보장) | env clearance test |
| AC-OTEL-003 | OTEL endpoint 설정 시 trace 자동 export (mock collector 검증) | integration test |
| AC-OTEL-004 | span attributes: audit_log_id / approval_status / risk_level / disagreement_score | mock collector 검증 |
| AC-OTEL-005 | LangSmith 활성 시 LLM 호출별 trace 노출 | env test |
| AC-OTEL-006 | 기존 123 tests 회귀 없이 통과 | pytest |
| AC-OTEL-007 | OpenTelemetry SDK 의존성이 optional (env 없으면 import 안 함) | dependency check |

## 5. 의존 변경

- 신규: `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp` (optional `[telemetry]` extra)
- 신규: `langsmith` (optional `[langsmith]` extra)
- 변경: `marketing_workflow.py` analyze() 진입/종료 span 생성
- 변경: `llm_client.py` LLM 호출 wrap span

## 6. 위험 / 완화

| 위험 | 완화 |
|---|---|
| OTEL SDK 무거움 → import 시 지연 | optional extra, lazy import |
| OTLP endpoint 실패 시 작업 중단 | exporter failure → silent fallback (sentry 등 별도) |
| LangSmith key leak | env에서만 로드, code hardcoding 금지 |
| trace attributes에 민감정보 포함 | PII redaction 후만 노출 (redacted_content 사용) |

## 7. Phase 분해

- **Phase A** (2 task): `telemetry.py` 모듈 + env-based init + no-op fallback
- **Phase B** (2 task): marketing_workflow + llm_client span 통합
- **Phase C** (1 task): LangSmith integration (선택)
- **Phase D** (2 task): integration test (mock collector) + 문서

## 8. 예상 작업 시간

**합계: 1-2시간** (단순 wire)

## 9. Definition of Done

1. AC 7건 충족
2. `pytest -q` 회귀 통과 (env 없는 환경에서)
3. mock OTLP collector로 span 1건 수신 확인
4. scorecard + delegation-board 갱신

## 10. 검증 수준

| 주장 | 수준 | 근거 |
|---|---|---|
| `state.trace` / `state.llm_calls` 존재 | [검증됨] | models.py:131 trace, marketing_workflow에서 llm_calls 추가 |
| audit_log JSONL append-only | [검증됨] | audit.py 구조 |
| OpenTelemetry Python SDK 표준 | [검증됨] | 공식 OTEL CNCF 프로젝트 |
| LangSmith Python client 존재 | [검증됨] | langsmith pypi 패키지 (LangChain ecosystem) |
| 1-2시간 작업 시간 | [추정] | 단순 wire, SDK 학습 비용 가변 |
| env-based no-op 기본값 적정성 | [추정] | 회귀 차단 우선 — 활성화는 운영 환경에서만 |
