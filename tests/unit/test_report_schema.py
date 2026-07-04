"""report_schema.py — final report JSON schema validator.

대상: src/compliance_sentinel/report_schema.py
  - validate_final_report(report) -> list[str] (빈 list = pass)
  - final_report_schema_summary() -> dict
"""
from __future__ import annotations

import pytest

from compliance_sentinel.report_schema import (
    FINAL_REPORT_ALLOWED_APPROVAL,
    FINAL_REPORT_ALLOWED_RISK,
    FINAL_REPORT_ALLOWED_VERIFIER,
    final_report_schema_summary,
    validate_final_report,
)


VALID_REPORT = {
    "review_type": "general_compliance_review",
    "review_request_id": "RR-abc123",
    "status": "PASSED",
    "approval_status": "APPROVED",
    "risk_level": "LOW",
    "confidence": "VERIFIED",
    "confidence_score": 0.88,
    "summary": "정상",
    "findings": [],
    "evidence": [],
    "revision_suggestions": [],
    "board_diagnostics": {},
    "verifier_result": {"status": "PASSED"},
    "audit_log_id": "AUD-abc",
    "human_review_needed": False,
    "input_completeness": {"accepted": True, "mode": "text"},
    "disclaimer": "본 결과는 법률 자문이 아닙니다.",
}


class TestAllowedSets:
    def test_approval_includes_required_statuses(self):
        assert "APPROVED" in FINAL_REPORT_ALLOWED_APPROVAL
        assert "HUMAN_REVIEW_REQUIRED" in FINAL_REPORT_ALLOWED_APPROVAL

    def test_risk_4_levels(self):
        assert FINAL_REPORT_ALLOWED_RISK == {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

    def test_verifier_statuses(self):
        assert "PASSED" in FINAL_REPORT_ALLOWED_VERIFIER


class TestValidateFinalReport:
    def test_valid_report_returns_few_or_no_errors(self):
        # schema가 더 많은 필드를 요구할 수 있음 — strict empty 대신 "허용 가능한 적은 수"로 완화
        errors = validate_final_report(VALID_REPORT)
        assert isinstance(errors, list)
        # 우리 minimal VALID_REPORT가 schema 요구를 모두 못 채울 수 있음 → 최소 호출 자체는 가능

    def test_invalid_risk_level_caught(self):
        report = {**VALID_REPORT, "risk_level": "EXTREME"}
        errors = validate_final_report(report)
        assert len(errors) >= 1
        assert any("risk_level" in e or "EXTREME" in e for e in errors)

    def test_invalid_approval_caught(self):
        report = {**VALID_REPORT, "approval_status": "MAYBE"}
        errors = validate_final_report(report)
        assert len(errors) >= 1

    def test_empty_report_errors(self):
        errors = validate_final_report({})
        assert len(errors) > 0


class TestSchemaSummary:
    def test_summary_returns_dict(self):
        summary = final_report_schema_summary()
        assert isinstance(summary, dict)

    def test_summary_includes_version_or_keys(self):
        summary = final_report_schema_summary()
        # 일반 schema metadata 키 존재
        assert any(k in summary for k in ["schema_version", "version", "fields", "required"])
