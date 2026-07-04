# Plan — OpenTelemetry / LangSmith Wire

> `spec/opentelemetry-wire.md` 의 중간 layer.

## 1. 원칙

1. **env-based no-op default** — env 부재 시 트레이서 비활성, 회귀 0 보장.
2. **lazy import** — opentelemetry SDK는 optional extra (`[telemetry]`).
3. **PII redacted only** — span attributes에 redacted_content만 (원문 금지).
4. **LangSmith optional** — `LANGSMITH_API_KEY` 시 활성, 미설치 시 silent skip.
5. **회귀 무영향** — 기존 trace/llm_calls 구조 그대로 유지, 신규 layer 추가만.

## 2. 목표 구조

```text
src/compliance_sentinel/
├── telemetry.py              # NEW
│   ├─ init_tracer() → Tracer | None
│   ├─ span(name, **attrs) → context manager
│   └─ langsmith_init() → Client | None
├── marketing_workflow.py
│   └─ (수정) analyze() 진입/종료 span 생성
└── llm_client.py
    └─ (수정) call() 진입 span + cost/latency attribute

pyproject.toml
└── [project.optional-dependencies]
    telemetry = ["opentelemetry-api>=1.0", "opentelemetry-sdk>=1.0", "opentelemetry-exporter-otlp>=1.0"]
    langsmith = ["langsmith>=0.1"]
```

## 3. 핵심 데이터 흐름

```text
analyze() 진입
  → telemetry.span("compliance_review",
       audit_log_id, approval_status, risk_level, disagreement_score)
    └─ 내부 LLM 호출
       → telemetry.span("llm.call", model, prompt_tokens, completion_tokens, cost)
    └─ board.diagnose_board()
       → telemetry.span("board.diagnose", disagreement_score, arbitration)
  → span 종료
  → env 활성 시 OTLP exporter로 자동 export
```

## 4. 압축 로드맵

### Phase A — 모듈 + no-op fallback (1시간)
- `telemetry.py` 신규 모듈
- `init_tracer()` 함수 (env 기반 OTEL_EXPORTER_OTLP_ENDPOINT 검출)
- `span()` context manager (트레이서 없으면 no-op contextmanager)
- env 부재 시 import 자체가 silent skip

### Phase B — 통합 (1시간)
- `marketing_workflow.py` `analyze()` 진입/종료 span
- `llm_client.py` `call()` span + cost/latency attribute
- span attributes: PII redaction 통과 후만 (`state.redacted_text` 사용)

### Phase C — LangSmith (30분, optional)
- `langsmith_init()` 함수 (env LANGSMITH_API_KEY)
- LLM 호출 trace 자동 export
- env 부재 시 silent skip

### Phase D — 검증 (1시간)
- mock OTLP collector로 span 수신 검증
- env clearance test (no env → no-op)
- 회귀: 123+ passed

## 5. 리스크와 완화

| 리스크 | 완화 |
|---|---|
| opentelemetry SDK 무거움 | optional extra, lazy import |
| OTLP endpoint 실패 → 작업 중단 | exporter failure silent fallback |
| LangSmith key leak | env에서만 로드, code hardcoding 금지 |
| span attribute에 PII | `state.redacted_text` only 사용, raw input 금지 |
| 회귀 test에서 트레이서 활성 → 외부 collector 부재로 fail | conftest에서 env 명시적 unset |

## 6. 산출물 검증 매핑

| 산출물 | AC | 검증 |
|---|---|---|
| `telemetry.py` | AC-OTEL-001 | unit test |
| env 부재 no-op | AC-OTEL-002 | env clearance test |
| OTLP export | AC-OTEL-003 | mock collector integration test |
| span attributes | AC-OTEL-004 | mock collector 검증 |
| LangSmith | AC-OTEL-005 | env test |
| 회귀 | AC-OTEL-006 | pytest -q (123+ passed) |
| optional SDK | AC-OTEL-007 | dependency check |

## 7. PDF 직접 대응

| PDF 요구 | 대응 |
|---|---|
| line 80 "심의 지연" | latency span attribute로 외부 dashboard 추적 |
| line 80 "심의 품질 편차" | disagreement_score span attribute로 추적 |
| line 84 "자동 연계" | 외부 telemetry 인프라(Jaeger/LangSmith)와 표준 연동 |
