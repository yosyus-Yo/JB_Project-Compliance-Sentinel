"""M11 Marketing Workflow 단위 테스트.

대상: src/compliance_sentinel/marketing_workflow.py
  - _confidence(review) — findings severity 기반 5등급
  - _status(review) — approval_status 매핑
  - _ceo_draft_from_review(review) — MarketingReview → ceo_draft dict
  - _force_cross_model_for_high_risk_findings(model_plan, review) — HIGH/CRITICAL/FAIL 시 강제 부착

복합 의존성 (LLM/RAG/Audit) 영역은 integration test로 별도 분리.
본 unit suite는 pure helper만 검증.
"""
from __future__ import annotations

import pytest

from compliance_sentinel.marketing_models import MarketingFinding, MarketingReview
from compliance_sentinel.marketing_workflow import (
    _ceo_draft_from_review,
    _confidence,
    _force_cross_model_for_high_risk_findings,
    _status,
)


def _make_review(findings=None, approval_status="APPROVED"):
    review = MarketingReview(
        raw_content="원본 카피",
        redacted_content="원본 카피",
        language="ko",
        channel="banner",
        content_type="advertisement",
        product_type="installment_savings",
        findings=findings or [],
    )
    review.approval_status = approval_status
    review.revision_suggestions = []
    review.evaluation_metadata = {}
    return review


def _make_finding(severity="MEDIUM", verifier_status="PARTIAL"):
    return MarketingFinding(
        id="F-001",
        rule_id="RULE-1",
        severity=severity,
        evidence="evidence text",
        issue="이슈",
        rationale="이유",
        suggested_revision="수정",
        language="ko",
        channel="banner",
        product_type="installment_savings",
        verifier_status=verifier_status,
    )


class TestConfidence:
    def test_no_findings_perfect(self):
        review = _make_review()
        assert _confidence(review) == "PERFECT"

    def test_critical_finding_failed(self):
        review = _make_review(findings=[_make_finding(severity="CRITICAL")])
        assert _confidence(review) == "FAILED"

    def test_high_finding_partial(self):
        review = _make_review(findings=[_make_finding(severity="HIGH")])
        assert _confidence(review) == "PARTIAL"

    def test_medium_finding_partial(self):
        review = _make_review(findings=[_make_finding(severity="MEDIUM")])
        assert _confidence(review) == "PARTIAL"


class TestStatus:
    def test_approved_maps_to_passed(self):
        review = _make_review(approval_status="APPROVED")
        assert _status(review) == "PASSED"

    def test_non_approved_human_review(self):
        review = _make_review(approval_status="NEEDS_REVISION")
        assert _status(review) == "HUMAN_REVIEW_REQUIRED"

    def test_rejected_human_review(self):
        review = _make_review(approval_status="REJECTED")
        assert _status(review) == "HUMAN_REVIEW_REQUIRED"


class TestCeoDraftFromReview:
    def test_required_keys(self):
        review = _make_review(findings=[_make_finding()])
        draft = _ceo_draft_from_review(review)
        for key in ["risk_level", "summary", "findings", "disclaimer"]:
            assert key in draft

    def test_findings_converted_to_finding_models(self):
        review = _make_review(findings=[_make_finding(severity="HIGH")])
        draft = _ceo_draft_from_review(review)
        assert len(draft["findings"]) == 1
        f = draft["findings"][0]
        assert f.id == "F-001"
        assert f.law_name == "금융광고 심의 기준"

    def test_disclaimer_marketing_specific(self):
        review = _make_review()
        draft = _ceo_draft_from_review(review)
        assert "마케팅" in draft["disclaimer"] or "법률 자문" in draft["disclaimer"]

    def test_empty_findings_still_returns_draft(self):
        review = _make_review()
        draft = _ceo_draft_from_review(review)
        assert draft["findings"] == []


class TestForceCrossModel:
    def test_no_findings_not_forced(self):
        review = _make_review()
        plan = {"cross_model": {"level": "NONE"}}
        result = _force_cross_model_for_high_risk_findings(plan, review)
        assert result is False
        assert plan["cross_model"]["level"] == "NONE"

    def test_already_strong_not_forced(self):
        review = _make_review(findings=[_make_finding(severity="HIGH")])
        plan = {"cross_model": {"level": "STRONG", "model": "gpt-5.5"}}
        result = _force_cross_model_for_high_risk_findings(plan, review)
        assert result is False  # 이미 STRONG이므로 변경 안 됨

    def test_high_finding_forces_strong(self):
        review = _make_review(findings=[_make_finding(severity="HIGH")])
        plan = {"cross_model": {"level": "NONE"}}
        result = _force_cross_model_for_high_risk_findings(plan, review)
        assert result is True
        assert plan["cross_model"]["level"] == "STRONG"
        assert plan["cross_model"]["model"] == "gpt-5.5"
        assert plan["cross_model"]["auto_attach"] is True

    def test_critical_finding_forces_strong(self):
        review = _make_review(findings=[_make_finding(severity="CRITICAL")])
        plan = {}
        result = _force_cross_model_for_high_risk_findings(plan, review)
        assert result is True
        assert plan["cross_model"]["level"] == "STRONG"

    def test_fail_verifier_status_forces_strong(self):
        review = _make_review(findings=[_make_finding(severity="MEDIUM", verifier_status="FAIL")])
        plan = {}
        result = _force_cross_model_for_high_risk_findings(plan, review)
        assert result is True

    def test_medium_only_not_forced(self):
        review = _make_review(findings=[_make_finding(severity="MEDIUM", verifier_status="PARTIAL")])
        plan = {}
        result = _force_cross_model_for_high_risk_findings(plan, review)
        assert result is False
