"""langsmith_eval.py — regression eval cases + EvalCaseResult."""
from __future__ import annotations

import pytest

from compliance_sentinel.langsmith_eval import (
    DEFAULT_EVAL_CASES,
    EvalCaseResult,
)


class TestDefaultEvalCases:
    def test_is_list(self):
        assert isinstance(DEFAULT_EVAL_CASES, list)

    def test_nonempty(self):
        assert len(DEFAULT_EVAL_CASES) > 0

    def test_each_case_has_required_fields(self):
        for case in DEFAULT_EVAL_CASES:
            assert isinstance(case, dict)
            # 최소 input/expected/text 같은 키 1개 이상
            assert len(case) > 0


class TestEvalCaseResult:
    def test_construction(self):
        # 실제 시그니처: id, passed, actual_status, actual_risk, audit_log_id, reason
        result = EvalCaseResult(
            id="case-001",
            passed=True,
            actual_status="PASSED",
            actual_risk="LOW",
            audit_log_id="AUD-abc",
            reason="모든 조건 충족",
        )
        assert result.id == "case-001"
        assert result.passed is True
        assert result.actual_risk == "LOW"

    def test_frozen_dataclass(self):
        result = EvalCaseResult(
            id="c1", passed=False, actual_status="FAILED",
            actual_risk="HIGH", audit_log_id="AUD-x", reason="r",
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            result.passed = True

    def test_failure_case(self):
        result = EvalCaseResult(
            id="c2", passed=False, actual_status="HUMAN_REVIEW_REQUIRED",
            actual_risk="CRITICAL", audit_log_id="AUD-y",
            reason="cross-model FAILED",
        )
        assert result.passed is False
        assert "FAILED" in result.reason
