# Spec — Budget Guard 사전 차단 강화

> PDF 지정주제 2 우선순위 #4. 외부 reviewer 의견: "사후 기록 → hard limit + graceful degradation."

## 1. 목적

`budget_guard.py`가 현재 **사후 비용 기록**만 수행. LLM 호출이 비용 한도를 초과할 가능성이 있어도 **사전 차단 안 함**. 본 spec은 **hard limit + graceful degradation** 도입.

## 2. 현황

- `BudgetGuard` 존재 (`src/compliance_sentinel/budget_guard.py`)
- env: `CS_PER_DEMO_USD=0.40`, `CS_MONTHLY_USD=80.0`
- 환경변수로 한도 설정 가능
- **호출 전 hard limit 체크 없음** (LLM 호출 후 cost 누적만)
- BudgetExceeded 예외 정의되어 있으나 실제 raise 사례 부재 가정

## 3. 범위

### In Scope

- LLM 호출 직전 hard limit check (`budget_guard.check_before_call()`)
- 초과 시 3-tier graceful degradation:
  - Tier 1 (90% 도달): warning log + 계속
  - Tier 2 (100% 도달): deterministic fallback 강제 (LLM skip)
  - Tier 3 (110% 도달): BudgetExceeded raise + 작업 중단
- 누적 cost를 `cost_tracker.jsonl`로 추적 (per-demo + monthly)
- final_report에 `budget_status` 필드 노출

### Out of Scope

- 다중 사용자 격리 (single-tenant)
- 실시간 알림 (Slack/email — 별도 spec)
- 예측 비용 (현재 호출만, 향후 호출 예측 X)

## 4. Acceptance Criteria

| AC | 내용 | 검증 |
|---|---|---|
| AC-BG-001 | `BudgetGuard.check_before_call(estimated_cost)` 메서드 추가 | unit test |
| AC-BG-002 | 90% 도달 시 warning, 100%+ 시 deterministic fallback, 110%+ 시 BudgetExceeded | unit test (3 case) |
| AC-BG-003 | `cost_tracker.jsonl` append-only 기록 (per call: timestamp/model/cost/cumulative) | unit test |
| AC-BG-004 | final_report에 `budget_status: {used: $, limit: $, percentage: %, tier: green\|yellow\|red}` 노출 | integration test |
| AC-BG-005 | LLM 호출이 deterministic fallback로 전환 시 final_report.disclaimer에 명시 | unit test |
| AC-BG-006 | env override (CS_PER_DEMO_USD / CS_MONTHLY_USD) 정상 작동 | env test |
| AC-BG-007 | 기존 123 tests 회귀 없이 통과 | pytest |

## 5. 의존 변경

- `llm_client.py`: LLM 호출 직전 `budget_guard.check_before_call()` 호출
- `marketing_workflow.py`: deterministic fallback 발동 시 trace 추가
- `runtime.py`: `llm_advisory_calls_parallel` 내부에 cost 추정 + 사전 check

## 6. 위험 / 완화

| 위험 | 완화 |
|---|---|
| 비용 추정 부정확 → 잘못된 차단 | model별 prompt/completion 토큰 추정치 보수적 (over-estimate) |
| deterministic fallback이 품질 저하 | final_report.disclaimer로 사용자에게 명시 |
| 110% 차단이 데모 도중 발생 | per-demo 한도 default 0.40$ → 충분히 여유 |
| cost_tracker.jsonl 폭증 | 월 단위 rotation (자동 archive) |

## 7. PDF 직접 대응 표

| PDF 요구 | 본 spec 대응 |
|---|---|
| line 80 "리소스 선형 증가" | 한도 도달 시 deterministic fallback로 비용 cap |
| line 84 "준법 자동 연계" | budget_status를 final_report에 노출 → 외부 dashboard 추적 가능 |

## 8. Phase 분해

- **Phase A** (2 task): `BudgetGuard.check_before_call()` + 3-tier 로직 + tests
- **Phase B** (2 task): `cost_tracker.jsonl` + final_report `budget_status` 통합
- **Phase C** (1 task): documentation 갱신

## 9. 예상 작업 시간

**합계: 2-3시간**

## 10. Definition of Done

1. AC 7건 모두 충족
2. `pytest -q` 회귀 통과
3. 의도적 한도 초과 시나리오 → 3-tier graceful degradation 실측
4. scorecard + delegation-board 갱신

## 11. 검증 수준

| 주장 | 수준 | 근거 |
|---|---|---|
| `BudgetGuard` 클래스 존재 | [검증됨] | budget_guard.py + budget_guard_from_env import |
| BudgetExceeded 예외 정의 | [검증됨] | grep 확인 (`BudgetGuard, BudgetExceeded`) |
| 사후 기록만 현재 | [추정] | 코드 직접 분석 안 함 — Phase A 시작 시 재확인 필수 |
| 3-tier 임계값 (90/100/110%) 적정성 | [추정] | 일반 SRE 패턴, 데모셋 측정 후 튜닝 |
| 작업 시간 2-3시간 | [추정] | 코드 변경 범위 어림 |
