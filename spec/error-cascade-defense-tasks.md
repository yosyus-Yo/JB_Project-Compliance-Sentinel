# Tasks — Error Cascade 방어 (Board Diagnostics)

> ID prefix: `EC-`. Phase A=001-099, Phase B=101-199, Phase C=201-299, Phase D=301-399.

## Phase A — 데이터 모델 + 분석 함수

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| EC-001 | `BoardOpinion` 기존 필드 확인 (`rationale` / `evidence` / `recommendation`) | todo | grep 결과로 필드 목록 명확. `rationale` 부재 시 EC-002로 보강 |
| EC-002 | (조건부) `BoardOpinion.rationale` 필드 추가 | todo | EC-001에서 부재 확인 시만. 기존 페르소나 함수 6개 모두 rationale 반환하도록 수정 |
| EC-003 | `MinorityOpinion` dataclass 추가 | todo | `persona`/`risk_level`/`rationale`/`why_minority` 4 필드 frozen dataclass |
| EC-004 | `BoardDiagnostics` dataclass 추가 | todo | `risk_distribution`/`majority_risk`/`disagreement_score`/`minority_opinions`/`requires_human_arbitration`/`contradiction_pairs` 6 필드 frozen dataclass |
| EC-005 | `diagnose_board(opinions)` 함수 구현 | todo | dict[str, BoardOpinion] → BoardDiagnostics 변환, 산식 표준화 |
| EC-006 | `disagreement_score` 산식 unit test | todo | 6:0=0.0, 5:1≈0.167, 3:3=0.5, 2:2:2≈0.667 모두 정확 |
| EC-007 | `requires_human_arbitration` trigger 3종 구현 | todo | (1) HIGH∧LOW 동시 (2) disagreement≥0.5 (3) contrarian이 majority 대비 위험 경고 |
| EC-008 | `contradiction_pairs` 산출 로직 | todo | risk_level 차이 ≥2 단계인 페르소나 쌍 추출 (예: HIGH vs LOW) |

## Phase B — Marketing Workflow 통합

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| EC-101 | `marketing_workflow.py`에서 `diagnose_board()` 호출 추가 | todo | `run_compliance_board()` 직후 호출, state에 저장 |
| EC-102 | `state.final_report["board_diagnostics"]` 필드 추가 | todo | `asdict(diagnostics)` 직렬화 후 final_report에 inline |
| EC-103 | `requires_human_arbitration` 트리거 시 `approval_status` 강제 | todo | True일 때 `approval_status="HUMAN_REVIEW_REQUIRED"` 덮어쓰기 (기존 분기보다 우선) |
| EC-104 | `audit_log_id` 연결 | todo | `board_diagnostics`에 `audit_log_id` 필드 inline (state.audit_log_id 참조) |
| EC-105 | `claim_taxonomy_summary` / `pdf_requirement_alignment`와 충돌 없음 확인 | todo | 기존 보강 필드들과 board_diagnostics가 동시 노출되며 schema 충돌 없음 |

## Phase C — Publisher 가시화

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| EC-201 | Slack payload `blocks`에 `board_diagnostics` 요약 추가 | todo | 충돌 페르소나 + minority opinion 본문 1줄씩 노출 (3개 이하) |
| EC-202 | Notion payload에 동일 추가 | todo | `properties` 또는 `children`에 board 요약 inline |
| EC-203 | `requires_human_arbitration=True` 시 `publish_plan.status_route` 자동 강제 확인 | todo | EC-103 트리거로 approval_status 변경 → 기존 status_route 매핑이 `route_to_compliance_owner` 자동 산출 |
| EC-204 | mock_payload_only 모드에서도 board_diagnostics 노출 | todo | env 없는 데모 환경에서도 audit/심사 표시 가능 |

## Phase D — 검증

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| EC-301 | `test_board_diagnostics_dataclass_shape` | todo | 6 필드 모두 dataclass에 존재 + 타입 일치 |
| EC-302 | `test_unanimous_low_yields_zero_disagreement` | todo | 6 페르소나 모두 LOW → disagreement_score==0.0, requires_human_arbitration==False |
| EC-303 | `test_split_high_low_triggers_human_arbitration` | todo | 3 HIGH + 3 LOW → requires_human_arbitration==True, disagreement_score==0.5 |
| EC-304 | `test_minority_opinion_preserved` | todo | 5 LOW + 1 contrarian HIGH → minority_opinions 길이 1, persona="contrarian" |
| EC-305 | `test_contrarian_high_against_low_majority_triggers_arbitration` | todo | majority LOW + contrarian HIGH → requires_human_arbitration==True (trigger #3) |
| EC-306 | `test_marketing_report_contains_board_diagnostics` | todo | final_report에 `board_diagnostics` 필드 + 6 sub-필드 노출 |
| EC-307 | `test_arbitration_forces_route_to_compliance_owner` | todo | requires_human_arbitration=True 케이스에서 publish_plan.status_route=="route_to_compliance_owner" |
| EC-308 | `test_audit_log_id_in_board_diagnostics` | todo | board_diagnostics.audit_log_id == state.audit_log_id |
| EC-309 | `pytest -q` 회귀 통과 | todo | 110 passed (기존 102 + 신규 8). EC-006 산식 unit test 포함 |
| EC-310 | 의도적 충돌 sample 실행 | todo | "이 상품은 100% 안전합니다" + critical claim → board 충돌 발생 시 arbitration trigger 실측 |
| EC-311 | 만장일치 sample 실행 | todo | 안전한 광고 텍스트 → disagreement_score=0.0 실측 |
| EC-312 | `docs/jb-pdf-compliance-scorecard.md` 업데이트 | todo | Error Cascade 방어 항목 추가 + 시점 기록 |
| EC-313 | `handoff/delegation-board.md` 결과 요약 추가 | todo | AGENTS.md L24 준수 |

## Deferred (본 spec 범위 외)

- `cross_model_verifier.py`와 board 통합 (별도 spec, GPT-5/Claude 교차 검증)
- contrarian 페르소나 trigger 옵션화 (false positive 발생 시)
- `disagreement_score` 임계값 CLI 옵션 (`--arbitration-threshold`)
- board 페르소나 가중치 (legal_counsel 1.5x 등) — 운영 데이터 축적 후 결정
- arbitration 사유 LLM 요약 (LLM 호출 의존 → optional path)

## Definition of Done

1. **AC 8건 모두 충족** (`spec/error-cascade-defense.md` §4)
2. **`pytest -q` 110 passed** + 기존 102 회귀 없음
3. **의도적 충돌 sample 실행 시 `requires_human_arbitration=True` 실측 확인**
4. **`audit_log_id`가 `board_diagnostics`에 inline** (감사 추적성)
5. **Slack/Notion mock payload에 board 충돌 요약 가시화**
6. **`docs/jb-pdf-compliance-scorecard.md` 업데이트 + `handoff/delegation-board.md` 요약 추가**
