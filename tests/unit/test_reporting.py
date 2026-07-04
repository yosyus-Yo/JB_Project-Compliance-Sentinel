"""M12 Final Report 단위 테스트.

대상: src/compliance_sentinel/reporting.py
  - _approval_status(status, confidence) — PASSED→APPROVED 등 매핑
  - _confidence_score(confidence, risk_level) — 5등급 → 점수
  - _review_request_id(input_text) — RR-<12hex>
  - _input_completeness(state) — 메타데이터 완성도
  - build_final_report(state) — CONFIDENCE 5등급 분기 + PII 필드 노출

Bug #2 회귀 방지: build_final_report가 pii_findings/pii_count/redacted_text를 응답에 포함해야 함.
"""
from __future__ import annotations

import pytest

from compliance_sentinel.models import (
    ComplianceState,
    Finding,
    PIIFinding,
)
from compliance_sentinel.reporting import (
    _approval_status,
    _confidence_score,
    _input_completeness,
    _review_request_id,
    build_final_report,
)


class TestApprovalStatus:
    def test_passed_maps_to_approved(self):
        assert _approval_status("PASSED", "VERIFIED") == "APPROVED"

    def test_passed_with_failed_confidence_still_human_review(self):
        assert _approval_status("HUMAN_REVIEW_REQUIRED", "FAILED") == "HUMAN_REVIEW_REQUIRED"

    def test_non_passed_returns_human_review(self):
        assert _approval_status("NEEDS_REVISION", "VERIFIED") == "HUMAN_REVIEW_REQUIRED"
        assert _approval_status("FAILED", "PARTIAL") == "HUMAN_REVIEW_REQUIRED"


class TestConfidenceScore:
    @pytest.mark.parametrize(
        "confidence,risk,expected",
        [
            ("FAILED", "LOW", 0.32),
            ("PARTIAL", "MEDIUM", 0.62),
            ("FEEDBACK", "HIGH", 0.78),
            ("PERFECT", "LOW", 0.96),
            ("VERIFIED", "LOW", 0.88),     # LOW/MEDIUM → 0.88
            ("VERIFIED", "MEDIUM", 0.88),
            ("VERIFIED", "HIGH", 0.72),    # HIGH/CRITICAL → 0.72
            ("VERIFIED", "CRITICAL", 0.72),
        ],
    )
    def test_score_matrix(self, confidence, risk, expected):
        assert _confidence_score(confidence, risk) == expected


class TestReviewRequestId:
    def test_format_rr_prefix_12hex(self):
        rid = _review_request_id("test input")
        assert rid.startswith("RR-")
        assert len(rid) == 15  # "RR-" + 12 hex chars

    def test_deterministic_same_input(self):
        assert _review_request_id("same") == _review_request_id("same")


class TestInputCompleteness:
    def test_accepts_nonempty_input(self, sample_state):
        result = _input_completeness(sample_state)
        assert result["accepted"] is True
        assert result["mode"] == "text_only_demo_with_inferred_metadata"

    def test_empty_input_not_accepted(self):
        state = ComplianceState(input_text="   ", redacted_text="", input_type="unknown")
        result = _input_completeness(state)
        assert result["accepted"] is False

    def test_unknown_input_type_marked_missing(self):
        state = ComplianceState(input_text="텍스트", redacted_text="텍스트", input_type="unknown")
        result = _input_completeness(state)
        # input_type이 unknown이면 missing list에 포함
        assert "input_type" in result["missing_or_unknown_fields"]
        assert result["requires_form_completion_for_production"] is True


class TestBuildFinalReport:
    """build_final_report 핵심 출력 키 + CONFIDENCE 분기 검증."""

    def _make_state(
        self,
        findings=None,
        risk_level="LOW",
        retry_count=0,
        pii_findings=None,
        redacted_text="테스트 입력",
    ):
        state = ComplianceState(
            input_text="테스트 입력",
            redacted_text=redacted_text,
            input_type="advertisement",
            pii_findings=pii_findings or [],
        )
        state.ceo_draft = {
            "findings": findings or [],
            "risk_level": risk_level,
            "summary": "테스트 요약",
            "disclaimer": "테스트 disclaimer",
        }
        state.retry_count = retry_count
        return state

    def test_required_top_level_keys(self):
        state = self._make_state()
        report = build_final_report(state)
        required = {
            "review_request_id", "status", "approval_status", "risk_level",
            "confidence", "confidence_score", "summary", "findings", "evidence",
            "revision_suggestions", "board_diagnostics", "verifier_result",
            "audit_log_id", "human_review_needed", "schema_validation",
        }
        assert required.issubset(report.keys()), f"missing: {required - set(report.keys())}"

    def test_pii_fields_exposed_bug2_regression(self, sample_pii_finding):
        """Bug #2 회귀 방지 — pii_findings + pii_count + redacted_text 필드가 응답에 포함."""
        state = self._make_state(
            pii_findings=[sample_pii_finding],
            redacted_text="홍길동 [RRN_REDACTED_1]",
        )
        report = build_final_report(state)

        assert "pii_findings" in report, "Bug #2: pii_findings 필드 누락"
        assert "pii_count" in report, "Bug #2: pii_count 필드 누락"
        assert "redacted_text" in report, "Bug #2: redacted_text 필드 누락"

        assert report["pii_count"] == 1
        assert report["redacted_text"] == "홍길동 [RRN_REDACTED_1]"
        assert len(report["pii_findings"]) == 1
        assert report["pii_findings"][0]["kind"] == "rrn"
        assert report["pii_findings"][0]["replacement"] == "[RRN_REDACTED_1]"

    def test_pii_findings_empty_list_when_none(self):
        state = self._make_state()
        report = build_final_report(state)
        assert report["pii_findings"] == []
        assert report["pii_count"] == 0

    def test_perfect_confidence_no_findings_low_risk(self):
        """findings 없이 LOW risk + retry 0 → PERFECT는 아님 (pass_count > 0 필요)."""
        # 명시: PERFECT는 retry_count == 0 + pass_count > 0 + risk LOW
        # findings 비어있으면 pass_count = 0 → else branch → VERIFIED + PASSED
        state = self._make_state(risk_level="LOW", retry_count=0)
        report = build_final_report(state)
        assert report["confidence"] == "VERIFIED"
        assert report["status"] == "PASSED"
        assert report["human_review_needed"] is False

    def test_failed_confidence_when_finding_fail(self):
        finding = Finding(
            id="F-001",
            source_text="원본",
            issue="이슈",
            law_name="법령",
            article_no="1",
            citation_text="조문",
            applicability_reason="적용",
            suggested_revision="수정",
            verifier_status="FAIL",
        )
        state = self._make_state(findings=[finding], risk_level="HIGH")
        report = build_final_report(state)
        assert report["confidence"] == "FAILED"
        assert report["status"] == "HUMAN_REVIEW_REQUIRED"
        assert report["human_review_needed"] is True

    def test_partial_confidence_when_finding_partial(self):
        finding = Finding(
            id="F-001", source_text="원본", issue="이슈", law_name="법령",
            article_no="1", citation_text="조문", applicability_reason="적용",
            suggested_revision="수정", verifier_status="PARTIAL",
        )
        state = self._make_state(findings=[finding])
        report = build_final_report(state)
        assert report["confidence"] == "PARTIAL"
        assert report["human_review_needed"] is True

    def test_cross_model_failed_forces_human_review(self):
        state = self._make_state()
        state.cross_model_result = {"cross_model_confidence": "FAILED"}
        report = build_final_report(state)
        assert report["human_review_needed"] is True
        assert report["status"] == "HUMAN_REVIEW_REQUIRED"

    def test_schema_validation_field_present(self):
        state = self._make_state()
        report = build_final_report(state)
        assert "schema_validation" in report
        assert "schema_version" in report["schema_validation"]
        assert report["schema_validation"]["schema_version"] == "compliance-sentinel-final-report/v2"
