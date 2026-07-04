# Tasks — OpenTelemetry / LangSmith Wire

> ID prefix: `OTEL-`.

## Phase A — 모듈 + no-op fallback

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| OTEL-001 | `pyproject.toml` `[project.optional-dependencies] telemetry` / `langsmith` 추가 | todo | `pip install -e .[telemetry,langsmith]` 정상 |
| OTEL-002 | `src/compliance_sentinel/telemetry.py` 신규 모듈 | todo | init_tracer / span / langsmith_init 3 함수 |
| OTEL-003 | `init_tracer()` env 기반 (OTEL_EXPORTER_OTLP_ENDPOINT) | todo | env 부재 시 None 반환, 활성 시 Tracer 반환 |
| OTEL-004 | `span(name, **attrs)` context manager | todo | 트레이서 None 시 no-op contextmanager |
| OTEL-005 | opentelemetry SDK lazy import (try/except ImportError) | todo | SDK 미설치 환경에서 import 자체 silent skip |

## Phase B — 통합

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| OTEL-101 | `marketing_workflow.py` analyze() 진입/종료 span | todo | "compliance_review" span 생성, attributes 포함 |
| OTEL-102 | span attributes: audit_log_id, approval_status, risk_level, disagreement_score | todo | mock collector 검증 |
| OTEL-103 | `llm_client.py` call() 진입 span | todo | "llm.call" span + model/prompt_tokens/completion_tokens/cost attribute |
| OTEL-104 | `board.diagnose_board()` span | todo | "board.diagnose" span + disagreement/arbitration attribute |
| OTEL-105 | span attribute에 PII redaction 검증 | todo | state.redacted_text only, raw input 절대 금지 |

## Phase C — LangSmith (선택)

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| OTEL-201 | `langsmith_init()` env 기반 (LANGSMITH_API_KEY) | todo | env 부재 시 None 반환 |
| OTEL-202 | LLM 호출 trace LangSmith export | todo | env 활성 시 LangSmith dashboard에 trace 노출 (수동 검증) |
| OTEL-203 | langsmith 패키지 미설치 silent skip | todo | import 실패 시 silent fallback |

## Phase D — 검증

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| OTEL-301 | `test_init_tracer_returns_none_without_env` | todo | env 부재 시 None |
| OTEL-302 | `test_span_no_op_without_tracer` | todo | 트레이서 None 시 context manager 정상 동작 (예외 없음) |
| OTEL-303 | `test_marketing_workflow_calls_span` | todo | analyze() 실행 시 span 호출 mock 검증 |
| OTEL-304 | `test_span_attributes_pii_redacted` | todo | span attribute에 redacted_content만 (원문 부재) |
| OTEL-305 | integration: mock OTLP collector로 span 수신 | todo | endpoint 설정 → span 1건 수신 확인 |
| OTEL-306 | `test_optional_extra_not_required_for_pytest` | todo | telemetry 미설치 환경에서도 pytest 정상 |
| OTEL-307 | `pytest -q` 회귀 통과 | todo | 123+ + 6 신규 |
| OTEL-308 | `docs/jb-pdf-compliance-scorecard.md` 업데이트 | todo | OTEL/LangSmith integration 명시 |
| OTEL-309 | `handoff/delegation-board.md` 결과 요약 | todo | env 항목에 OTEL_EXPORTER_OTLP_ENDPOINT / LANGSMITH_API_KEY 추가 |

## Deferred

- 자체 dashboard UI (Grafana/Jaeger setup은 사용자 인프라)
- 다중 서비스 trace context propagation
- alerting 규칙 (cost spike, error rate)
- Anthropic Console 비용 추적 통합 (별도 spec)

## Definition of Done

1. AC 7건 충족
2. `pytest -q` 회귀 통과 (env 없는 환경)
3. mock OTLP collector로 span 1건 수신 실측
4. scorecard + delegation-board 갱신
5. 모든 span attribute가 PII redacted (`state.redacted_text` only)
