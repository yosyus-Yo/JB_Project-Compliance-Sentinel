# Spec — Error Cascade 방어 (Board Contradiction Detection + Minority Report)

> PDF 지정주제 2 우선순위 #2 (외부 reviewer 보정 후 #2 승격) "콘텐츠 심의 품질 편차 축소" 대응.
> PDF 본문 line 80 "심의자별 품질 편차 발생" 한계점 직접 대응.

## 1. 목적

`board.py`의 6개 페르소나 의견이 **상충할 때 silent하게 다수결로 통합되어 정보 손실**되는 문제를 차단한다. 의견 충돌을 **명시적으로 감지·기록·escalation**하여 PDF 요구 "준법 담당자의 검토·승인 역할"에 충실하도록 보완한다.

## 2. 현황

`src/compliance_sentinel/board.py` [검증됨]:
- 6 페르소나: `legal_counsel`, `pipa_expert`, `consumer_expert`, `operational_risk`, `business_practicality`, `contrarian`
- `run_compliance_board()` → `dict[str, BoardOpinion]` 반환
- `max_risk()` → 위험도 최댓값 산출

**한계**:
- 의견 충돌 자체가 메트릭으로 노출 안 됨 (집계만)
- `contrarian`이 다수와 다른 의견을 내도 그냥 묻힘
- `cross_model_verifier.py` 존재하나 board와 미연결 [추정 — 별도 모듈]

## 3. 범위

### In Scope

- 의견 분포(`risk_level` 분포) → `disagreement_score` 산출
- 다수 의견과 다른 페르소나의 `minority_report` 보존
- 위험도 임계 이상 충돌 시 자동 escalation 플래그 (`requires_human_arbitration=True`)
- 최종 report에 `board_diagnostics` 필드 노출

### Out of Scope

- 신규 페르소나 추가
- LLM 재호출 (deterministic 분기만)
- cross_model_verifier 통합 (별도 작업)

## 4. Acceptance Criteria

| AC | 내용 | 검증 |
|---|---|---|
| AC-ERR-001 | `BoardDiagnostics` dataclass 신설 (risk 분포, disagreement_score, minority_opinions, requires_human_arbitration) | pytest |
| AC-ERR-002 | `disagreement_score ∈ [0, 1]` (0=만장일치, 1=최대 충돌) | pytest |
| AC-ERR-003 | `minority_opinions`에 다수 의견과 다른 페르소나 전부 보존 | pytest |
| AC-ERR-004 | `risk_levels = {HIGH, LOW}` 동시 등장 시 `requires_human_arbitration=True` | pytest |
| AC-ERR-005 | 마케팅 최종 report에 `board_diagnostics` 필드 포함 | pytest |
| AC-ERR-006 | `requires_human_arbitration=True` 시 `publish_plan.status_route="route_to_compliance_owner"` 강제 | pytest |
| AC-ERR-007 | 기존 102 tests 전부 회귀 없이 통과 | pytest -q |
| AC-ERR-008 | `audit_log_id`와 `board_diagnostics` 연결 (감사 추적성) | pytest |

## 5. 데이터 모델

### 5.1 `BoardDiagnostics` (신규)

`src/compliance_sentinel/board.py`에 추가:

```python
@dataclass(frozen=True)
class BoardDiagnostics:
    risk_distribution: dict[str, int]      # {"HIGH": 2, "MEDIUM": 3, "LOW": 1}
    majority_risk: str                      # 가장 많이 등장한 risk
    disagreement_score: float               # 0 (만장일치) ~ 1 (최대 충돌)
    minority_opinions: list[MinorityOpinion]
    requires_human_arbitration: bool        # HIGH ∧ LOW 동시 등장 등
    contradiction_pairs: list[tuple[str, str]]  # 직접 모순 페르소나 쌍

@dataclass(frozen=True)
class MinorityOpinion:
    persona: str                            # "contrarian"
    risk_level: str                         # "HIGH"
    rationale: str                          # 의견 본문 발췌
    why_minority: str                       # "majority=LOW, 5 vs 1"
```

### 5.2 `disagreement_score` 산식

```
N = total opinions (6)
distinct_levels = len(set(risk_levels))
max_count = max(risk_distribution.values())
disagreement = 1 - (max_count / N)
# 만장일치: 6/6 → 0.0
# 5:1 → 1 - 5/6 = 0.167
# 3:3 → 1 - 3/6 = 0.5
# 2:2:2 → 1 - 2/6 = 0.667
```

### 5.3 `requires_human_arbitration` 트리거

다음 중 하나라도 만족 시 `True`:

1. `HIGH ∈ risk_levels` ∧ `LOW ∈ risk_levels` (극단 모순)
2. `disagreement_score >= 0.5`
3. `contrarian.risk_level != majority_risk` ∧ `majority_risk in {"LOW", "MEDIUM"}` (contrarian이 위험 경고)

## 6. 통합 지점

### 6.1 `board.py` 수정

```python
def run_compliance_board(text: str, context: list[LawArticle]) -> dict[str, BoardOpinion]:
    # 기존 로직 유지

def diagnose_board(opinions: dict[str, BoardOpinion]) -> BoardDiagnostics:
    # NEW: 의견 분석 → 진단
    ...
```

### 6.2 `marketing_workflow.py` 수정

```python
# 기존:
board_opinions = run_compliance_board(...)

# 신규 추가:
diagnostics = diagnose_board(board_opinions)
state.final_report["board_diagnostics"] = asdict(diagnostics)
if diagnostics.requires_human_arbitration:
    state.approval_status = "HUMAN_REVIEW_REQUIRED"  # 강제 라우팅
```

### 6.3 `workflow_publishers.py` 연계

이미 존재하는 `build_publish_plan()`의 `status_route` 분기를 활용:
- `HUMAN_REVIEW_REQUIRED` → `route_to_compliance_owner` (기존)
- `board_diagnostics`도 publish_plan에 inline (Slack/Notion payload에서 충돌 가시화)

## 7. 회귀 테스트 (신규 6건)

```python
class TestBoardDiagnostics(unittest.TestCase):

    def test_unanimous_low_yields_zero_disagreement(self):
        # 모든 페르소나 LOW → disagreement_score=0.0
        ...

    def test_split_high_low_triggers_human_arbitration(self):
        # 3:3 HIGH:LOW → requires_human_arbitration=True
        ...

    def test_minority_opinion_preserved(self):
        # 5 LOW + 1 contrarian HIGH → minority_opinions 1개 보존
        ...

    def test_contrarian_high_against_low_majority_triggers_arbitration(self):
        # contrarian만 HIGH인데 majority LOW → arbitration 필수
        ...

    def test_marketing_report_contains_board_diagnostics(self):
        # 최종 report에 board_diagnostics 필드 존재
        ...

    def test_arbitration_forces_route_to_compliance_owner(self):
        # requires_human_arbitration=True → publish_plan.status_route 강제
        ...
```

## 8. 위험 / 완화

| 위험 | 완화 |
|---|---|
| 의견 충돌 빈도 과다 → 매번 HUMAN_REVIEW로 라우팅 → workflow 마비 | `disagreement_score >= 0.5` 임계값 튜닝, 데모 데이터셋으로 검증 후 0.4-0.6 사이 조정 |
| 기존 `max_risk()` 로직과 충돌 | `diagnose_board()`는 신규 함수로 추가, `max_risk()`는 그대로 유지 |
| `BoardOpinion`에 `rationale` 필드 부재 시 minority report 본문 손실 | dataclass 확인 후 필요 시 필드 확장 (없으면 별도 작업) |
| 회귀 테스트가 기존 `final_report` 스키마 강제 단언과 충돌 | 신규 필드만 추가, 기존 필드 변경 없음 → 회귀 없음 |
| audit_log_id 연결 누락 | `state.audit_log_id`를 `board_diagnostics`에 inline (테스트로 강제) |

## 9. PDF 직접 대응 표

| PDF 요구 / 한계점 | 본 spec 대응 |
|---|---|
| "심의자별 품질 편차 발생" (line 80) | `disagreement_score`로 편차 정량화 |
| "준법 담당자의 검토·승인 역할 자동화" (line 84) | `requires_human_arbitration` → `route_to_compliance_owner` 자동 분기 |
| "수작업 심의" 병목 (line 78) | minority report 자동 보존 → 담당자가 핵심 의견만 빠르게 검토 |
| "근거 제공" (line 86) | `contradiction_pairs`로 충돌 지점 명시 |

## 10. 출력

| 산출물 | 위치 |
|---|---|
| `BoardDiagnostics`, `MinorityOpinion` dataclass | `src/compliance_sentinel/board.py` |
| `diagnose_board()` 함수 | 동일 |
| `marketing_workflow.py` `board_diagnostics` report 필드 | 기존 파일 확장 |
| 회귀 테스트 6건 | `tests/test_compliance_sentinel.py` |
| `docs/jb-pdf-compliance-scorecard.md` 업데이트 | 본 보강 명시 |

## 11. 완료 정의

1. `pytest -q`: 108 passed (기존 102 + 신규 6)
2. 샘플 실행 시 `state.final_report["board_diagnostics"]["disagreement_score"]` 노출 확인
3. 의도적 충돌 텍스트 입력 시 `requires_human_arbitration=True` + `status_route="route_to_compliance_owner"` 실측
4. `handoff/delegation-board.md` 결과 요약 추가

## 12. 예상 작업 시간

- 데이터 모델 + `diagnose_board()` 구현: 1시간
- `marketing_workflow.py` 통합: 30분
- `workflow_publishers.py` 분기 보강: 30분
- 회귀 테스트 6건: 1시간
- 검증·디버그·문서 업데이트: 1시간

**합계: 3-4시간**

## 13. 검증 수준

| 핵심 주장 | 수준 | 근거 |
|---|---|---|
| `board.py` 6 페르소나 존재 | [검증됨] | grep 결과 (legal_counsel/pipa/consumer/operational/business/contrarian) |
| `BoardOpinion`에 `rationale` 필드 존재 여부 | [미확인] | dataclass 본문 미확인, 구현 전 재확인 필수 |
| `cross_model_verifier`와 별도 모듈 | [검증됨] | 별개 파일 (board.py와 분리) |
| `disagreement_score` 산식 합리성 | [추정] | 분포 균등도 1차 메트릭, 운영 데이터 없음 |
| 임계값 0.5 적정성 | [추정] | 데모 데이터셋으로 튜닝 후 조정 필요 |
| PDF line 78-86 매핑 정확성 | [검증됨] | 직전 turn pdftotext 추출 본문 직접 인용 |
| audit_log_id 연결 가능성 | [추정] | 기존 `state.audit_log_id` 존재 가정 (코드 재확인 필요) |
