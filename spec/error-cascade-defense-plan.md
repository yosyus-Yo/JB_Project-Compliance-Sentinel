# Plan — Error Cascade 방어 (Board Diagnostics)

> 본 plan은 `spec/error-cascade-defense.md`(목표 spec)와 `spec/error-cascade-defense-tasks.md`(작업 분해)의 중간 layer다.

## 1. 원칙

1. **기존 board 보존** — 6 페르소나(`legal_counsel`, `pipa_expert`, `consumer_expert`, `operational_risk`, `business_practicality`, `contrarian`) 구조 변경 없음. 신규 분석 layer만 추가.
2. **명시적 충돌 감지** — silent 다수결 합치 차단. 충돌은 메트릭 + minority report로 가시화.
3. **deterministic 분기** — LLM 재호출 없음. 의견 분포 분석만으로 `requires_human_arbitration` 산출.
4. **기존 workflow 통합** — `marketing_workflow.py`의 `state.final_report`에 `board_diagnostics` 필드 추가 + `publish_plan.status_route` 재활용.
5. **회귀 무영향** — 기존 `max_risk()` 로직 유지. 신규 함수 `diagnose_board()`로 layer 추가만.

## 2. 목표 구조

```text
src/compliance_sentinel/
├── board.py
│   ├── (기존) run_compliance_board() — 6 페르소나 호출
│   ├── (기존) max_risk() — 위험도 최댓값
│   ├── (NEW) BoardDiagnostics dataclass
│   ├── (NEW) MinorityOpinion dataclass
│   └── (NEW) diagnose_board(opinions) -> BoardDiagnostics
├── marketing_workflow.py
│   └── (수정) state.final_report["board_diagnostics"] = asdict(diagnostics)
│       + requires_human_arbitration → approval_status="HUMAN_REVIEW_REQUIRED" 강제
└── workflow_publishers.py
    └── (수정) publish_plan에 board_diagnostics 요약 inline (Slack/Notion 가시화)

tests/test_compliance_sentinel.py
└── (추가) TestBoardDiagnostics 클래스 (6 테스트)
```

## 3. 핵심 데이터 흐름

```text
content_text → run_compliance_board()
   → 6 BoardOpinion 반환
   → diagnose_board()
      → risk_distribution / disagreement_score 산출
      → minority_opinions 보존
      → requires_human_arbitration 판정
   → state.final_report["board_diagnostics"]
   → requires_human_arbitration==True 시:
      state.approval_status = "HUMAN_REVIEW_REQUIRED"
      → build_publish_plan().status_route = "route_to_compliance_owner"
```

## 4. 압축 로드맵

### Phase A — 데이터 모델 + 분석 함수 (1시간)
- `BoardDiagnostics` / `MinorityOpinion` dataclass 추가
- `BoardOpinion.rationale` 필드 존재 여부 확인 (없으면 spec 재검토 트리거)
- `diagnose_board(opinions)` 함수 구현
- `disagreement_score` 산식 검증 (만장일치 0.0, 3:3=0.5, 2:2:2=0.67)

### Phase B — Marketing Workflow 통합 (30분)
- `marketing_workflow.py`에서 `run_compliance_board()` 호출 직후 `diagnose_board()` 호출
- `state.final_report["board_diagnostics"]` 필드 추가
- `requires_human_arbitration==True` 시 `approval_status="HUMAN_REVIEW_REQUIRED"` 강제

### Phase C — Publisher 가시화 (30분)
- `workflow_publishers.py`의 Slack payload에 `board_diagnostics` 요약 inline (충돌 페르소나 + minority opinion 1줄씩)
- `build_publish_plan()`은 변경 없음 (status_route 분기는 기존 로직 재활용)
- `audit_log_id` 연결 확인

### Phase D — 검증 (1시간)
- 회귀 테스트 6건 추가 (TestBoardDiagnostics)
- `pytest -q` → 108 passed 확인
- 의도적 충돌 sample 입력 → `requires_human_arbitration=True` 실측
- 만장일치 sample 입력 → `disagreement_score=0.0` 실측

## 5. 리스크와 완화

| 리스크 | 완화 |
|---|---|
| 의견 충돌 빈도 과다 → 매번 HUMAN_REVIEW 라우팅 → workflow 마비 | 임계값 0.5로 시작, 데모셋 측정 후 0.4-0.6 사이 튜닝. CLI `--arbitration-threshold` 옵션 검토 |
| `BoardOpinion`에 `rationale` 필드 부재 | Phase A 첫 단계에서 dataclass 본문 확인 → 없으면 spec 보완 (필드 추가 작업 별도) |
| 기존 `final_report` 스키마 강제 단언 회귀 | 신규 `board_diagnostics` 필드만 추가, 기존 필드 0 변경 → backward compat |
| `max_risk()`와 `requires_human_arbitration` 동시 라우팅 충돌 | `max_risk`는 risk_level 산출용, `requires_human_arbitration`은 approval_status 분기용 → 직교 |
| audit_log_id 연결 누락 | Phase B에서 `state.audit_log_id`를 `board_diagnostics`에 inline + 회귀 테스트로 강제 |
| contrarian 페르소나가 자주 fire → false positive arbitration | trigger 3종 중 #3(contrarian만 위험 경고)은 옵션화 가능 — 데모 측정 후 결정 |

## 6. 산출물 검증 매핑

| 산출물 | spec AC | 검증 명령 |
|---|---|---|
| `BoardDiagnostics` dataclass | AC-ERR-001 | `pytest -k test_board_diagnostics_dataclass_shape` |
| `disagreement_score ∈ [0, 1]` | AC-ERR-002 | `pytest -k test_unanimous_low_yields_zero_disagreement` |
| `minority_opinions` 보존 | AC-ERR-003 | `pytest -k test_minority_opinion_preserved` |
| HIGH ∧ LOW → arbitration | AC-ERR-004 | `pytest -k test_split_high_low_triggers_human_arbitration` |
| report `board_diagnostics` 필드 | AC-ERR-005 | `pytest -k test_marketing_report_contains_board_diagnostics` |
| arbitration → status_route 강제 | AC-ERR-006 | `pytest -k test_arbitration_forces_route_to_compliance_owner` |
| 회귀 무영향 | AC-ERR-007 | `pytest -q` (108 passed) |
| audit_log_id 연결 | AC-ERR-008 | `pytest -k test_audit_log_id_in_board_diagnostics` |

## 7. PDF 직접 대응 표

| PDF 요구 / 한계점 (line) | 본 plan 대응 |
|---|---|
| line 80 "심의자별 품질 편차 발생" | `disagreement_score` 정량 노출 |
| line 84 "준법 담당자의 검토·승인 역할 자동화" | `requires_human_arbitration` → `route_to_compliance_owner` 자동 분기 |
| line 78 "수작업 심의 → 병목" | minority report 자동 보존으로 담당자 검토 시간 단축 |
| line 86 "근거 제공" | `contradiction_pairs`로 충돌 지점 명시 |
| line 88 "준법 담당자가 검토 및 승인 역할에 집중" | arbitration 시 자동 라우팅으로 담당자 개입 시점 최적화 |
