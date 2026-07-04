# Tasks — Budget Guard Enforcement

> ID prefix: `BG-`.

## Phase A — 데이터 + 분석 함수

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| BG-001 | 기존 `BudgetGuard` 본문 확인 (실제 사후 기록만 하는지) | todo | 코드 grep + 분석. spec 가정 검증 |
| BG-002 | `check_before_call(estimated_cost) -> Tier` 메서드 추가 | todo | green/yellow/red/blocked Literal 반환 |
| BG-003 | 3-tier 임계값 (90/100/110%) 산식 구현 | todo | unit test 3 case 통과 |
| BG-004 | `track_call(model, actual_cost)` cost_tracker.jsonl I/O | todo | append-only, timestamp/model/cost/cumulative inline |
| BG-005 | `status() -> dict` 반환 (used/limit/percentage/tier) | todo | final_report 직렬화 가능 |
| BG-006 | 비용 추정 함수 (model별 보수적 over-estimate) | todo | model_router.MODEL_* 별 토큰당 cost dict |

## Phase B — LLM 통합

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| BG-101 | `llm_client.py` call() 진입에 check_before_call() | todo | tier=red 시 fallback, tier=blocked 시 raise |
| BG-102 | tier=red 시 deterministic fallback 활성 + state.trace 추가 | todo | trace에 `budget_fallback` 항목 |
| BG-103 | `runtime.py` `llm_advisory_calls_parallel` 동일 패턴 | todo | 병렬 호출 시 한도 확인 |
| BG-104 | track_call() 호출 (LLM 응답 후 actual_cost로) | todo | cost_tracker.jsonl에 append 확인 |

## Phase C — Report 통합

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| BG-201 | `build_marketing_report`에 `budget_status` 필드 추가 | todo | final_report["budget_status"] 노출 |
| BG-202 | disclaimer override (deterministic fallback 시) | todo | "본 응답은 비용 한도 도달로 deterministic fallback 사용" 명시 |
| BG-203 | env 부재 시 no-op fallback 동작 검증 | todo | `from_env() == None` 시 모든 호출 no-op |

## Phase D — 검증

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| BG-301 | `test_check_before_call_green_yellow_red_blocked` | todo | 4 tier 모두 정확 분기 |
| BG-302 | `test_track_call_appends_jsonl` | todo | cost_tracker.jsonl에 row 추가 |
| BG-303 | `test_budget_status_in_final_report` | todo | analyze_marketing_content 결과에 budget_status 포함 |
| BG-304 | `test_deterministic_fallback_disclaimer` | todo | tier=red 시 disclaimer 자동 갱신 |
| BG-305 | `test_env_override_respected` | todo | CS_PER_DEMO_USD=0.01 override 정상 |
| BG-306 | `test_env_absent_noop` | todo | env 없으면 check_before_call이 항상 green 반환 |
| BG-307 | `test_intentional_overrun_raises_budget_exceeded` | todo | 한도 110% 초과 시 BudgetExceeded raise |
| BG-308 | `pytest -q` 회귀 통과 | todo | 123+ + 7 신규 |
| BG-309 | `docs/jb-pdf-compliance-scorecard.md` 업데이트 | todo | budget_status 노출 명시 |
| BG-310 | `handoff/delegation-board.md` 결과 요약 | todo | AGENTS.md L24 준수 |

## Deferred

- 월 단위 cost_tracker.jsonl rotation (cron 또는 startup hook)
- Slack/email 알림 (다른 spec)
- 예측 비용 (LLM 호출 전 N개 호출 시뮬레이션) — 별도 spec

## Definition of Done

1. AC 7건 충족
2. `pytest -q` 회귀 통과 (123+ + 7 신규)
3. 의도적 한도 초과 sample → 3-tier graceful degradation 실측
4. scorecard + delegation-board 갱신
