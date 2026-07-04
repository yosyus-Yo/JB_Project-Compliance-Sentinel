"""골든셋 회귀 게이트 테스트 (함정5 방어).

baseline 전체 통과 + invariant가 실제 회귀를 잡는지(negative test) 검증한다.
negative test가 없으면 "항상 통과하는 무용한 게이트"가 될 수 있으므로 필수.
"""
from __future__ import annotations

from compliance_sentinel.golden_regression import (
    judge_case,
    load_golden_cases,
    run_golden_regression,
)


class _FakeState:
    """judge_case 단위 테스트용 최소 state 더블."""

    def __init__(self, report, *, human_review, verifier=None, redacted=""):
        self.final_report = report
        self.human_review_needed = human_review
        self.verifier_results = verifier or []
        self.redacted_text = redacted


def test_golden_set_loads_all_30_cases():
    cases = load_golden_cases()
    assert len(cases) == 30, f"골든셋 30건이어야 함, 실제 {len(cases)}"


def test_golden_regression_baseline_all_pass():
    """현재 baseline은 30/30 통과해야 한다 (회귀 게이트의 기준선)."""
    summary = run_golden_regression()
    failed = [r for r in summary["results"] if not r["passed"]]
    assert summary["case_count"] == 30
    assert summary["failed"] == 0, f"회귀 발생: {failed}"


def test_gate_catches_silent_adversarial_pass():
    """적대 입력이 silently APPROVED(+no human review)되면 게이트가 FAIL해야 한다."""
    row = {"id": "adv", "expected": "high_risk_human_review"}
    state = _FakeState(
        {"approval_status": "APPROVED", "risk_level": "LOW"}, human_review=False
    )
    passed, reason = judge_case(row, state=state)
    assert not passed, "적대 입력이 silently 통과했는데 게이트가 놓침"
    assert "silently passed" in reason


def test_gate_catches_marketing_flag_miss():
    """marketing 케이스에서 expected_flag 탐지 누락 시 FAIL해야 한다."""
    row = {
        "id": "mkt",
        "expected_approval": "HUMAN_REVIEW_REQUIRED",
        "expected_flags": ["ZERO_RISK", "GUARANTEED_RETURN"],
    }
    state = _FakeState(
        {"approval_status": "HUMAN_REVIEW_REQUIRED", "findings": [{"rule_id": "ZERO_RISK"}]},
        human_review=True,
    )
    passed, reason = judge_case(row, state=state)
    assert not passed, "flag 탐지 누락인데 게이트가 놓침"
    assert "GUARANTEED_RETURN" in reason


def test_gate_catches_pii_leak():
    """PII 케이스에서 원문 주민번호가 redacted_text에 남으면 FAIL해야 한다."""
    row = {"id": "pii", "expected": "pii_redacted"}
    state = _FakeState(
        {"approval_status": "HUMAN_REVIEW_REQUIRED"},
        human_review=True,
        redacted="고객 900101-1234567 문의",
    )
    passed, reason = judge_case(row, state=state)
    assert not passed, "PII 누출인데 게이트가 놓침"


def test_gate_catches_missing_critical_block():
    """critical 기대 케이스가 REJECTED/CRITICAL이 아니면 FAIL해야 한다."""
    row = {"id": "crit", "expected": "critical_block"}
    state = _FakeState(
        {"approval_status": "APPROVE_WITH_CHANGES", "risk_level": "MEDIUM"},
        human_review=True,
    )
    passed, _ = judge_case(row, state=state)
    assert not passed, "critical 차단 실패인데 게이트가 놓침"
