# Plan — Budget Guard 사전 차단 강화

> `spec/budget-guard-enforcement.md` 의 중간 layer.

## 1. 원칙

1. **사후 기록 → 사전 차단 전환** — LLM 호출 전 `check_before_call()` 호출 의무화.
2. **3-tier graceful degradation** — 90% warning / 100% deterministic fallback / 110% raise.
3. **회귀 무영향** — 기존 LLM 호출 경로 동작 유지, 한도 미설정 시 no-op.
4. **추적 가능성** — `cost_tracker.jsonl` append-only 기록.
5. **사용자 가시화** — final_report에 `budget_status` 필드 노출.

## 2. 목표 구조

```text
src/compliance_sentinel/
├── budget_guard.py
│   ├─ (기존) BudgetGuard / BudgetExceeded
│   ├─ (NEW) check_before_call(estimated_cost) -> Tier (green|yellow|red|blocked)
│   ├─ (NEW) track_call(model, actual_cost) → cost_tracker.jsonl append
│   └─ (NEW) status() -> {used, limit, percentage, tier}
├── llm_client.py
│   └─ (수정) call() 진입 시 budget_guard.check_before_call()
└── marketing_workflow.py
    └─ (수정) state.final_report["budget_status"] = budget_guard.status()

data/
└── cost_tracker.jsonl       # NEW: append-only per-call cost
```

## 3. 핵심 데이터 흐름

```text
LLM 호출 요청
  → budget_guard.check_before_call(estimated_cost)
     ├─ tier=green (<90%)  → 정상 진행
     ├─ tier=yellow (90~100%) → warning log + 정상 진행
     ├─ tier=red (100~110%) → deterministic fallback (LLM skip, return mock)
     └─ tier=blocked (≥110%) → BudgetExceeded raise → 작업 중단
  → 호출 완료
  → budget_guard.track_call(model, actual_cost) → cost_tracker.jsonl append
  → final_report["budget_status"] inline
```

## 4. 압축 로드맵

### Phase A — 데이터 + 분석 함수 (1시간)
- `BudgetGuard.check_before_call()` + 3-tier 로직
- `BudgetGuard.track_call()` + cost_tracker.jsonl I/O
- `BudgetGuard.status()` 반환 dict
- 비용 추정 함수 (model별 prompt/completion 토큰 cost — 보수적 over-estimate)

### Phase B — LLM 통합 (30분)
- `llm_client.py` call() 진입 시 check_before_call() 호출
- tier=red 시 deterministic fallback 활성 + trace 추가
- `runtime.py` `llm_advisory_calls_parallel` 동일 패턴

### Phase C — Report 통합 (30분)
- `marketing_workflow.py` `build_marketing_report`에 `budget_status` 필드 추가
- disclaimer에 deterministic fallback 발동 시 명시

### Phase D — 검증 (1시간)
- 회귀 테스트 7건 (TestBudgetGuardEnforcement)
- 의도적 한도 초과 시나리오 sample
- `pytest -q` 회귀 통과

## 5. 리스크와 완화

| 리스크 | 완화 |
|---|---|
| 비용 추정 부정확 → over-block | 보수적 over-estimate, 실제 cost와 비교 후 점진 튜닝 |
| deterministic fallback 품질 저하 | final_report.disclaimer로 사용자 명시 |
| 110% 차단이 데모 도중 발동 | per-demo default 0.40$ → 5분 데모에 충분 |
| cost_tracker.jsonl 폭증 | 월 단위 rotation (자동 archive 별도 작업) |
| 기존 tests에서 budget_guard 호출 없음 → 새 함수 호출 누락 | env 부재 시 no-op fallback (`from_env()`) 동작 검증 |

## 6. 산출물 검증 매핑

| 산출물 | AC | 검증 |
|---|---|---|
| `check_before_call()` | AC-BG-001 | unit test |
| 3-tier 분기 | AC-BG-002 | unit test 3 case |
| `cost_tracker.jsonl` | AC-BG-003 | unit test (파일 append) |
| `final_report.budget_status` | AC-BG-004 | integration test |
| disclaimer override | AC-BG-005 | unit test |
| env override | AC-BG-006 | env test |
| 회귀 | AC-BG-007 | pytest -q (123+ passed) |

## 7. PDF 직접 대응

| PDF 요구 (line) | 대응 |
|---|---|
| line 80 "리소스 선형 증가" | 한도 도달 시 deterministic fallback로 비용 cap |
| line 84 "자동 연계" | budget_status를 final_report 노출 → 외부 dashboard 추적 |
