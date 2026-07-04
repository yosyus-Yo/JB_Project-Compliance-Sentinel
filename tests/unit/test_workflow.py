"""workflow.py — ComplianceSentinel orchestrator + helpers + full analyze()."""
from __future__ import annotations

import pytest

from compliance_sentinel.models import (
    AtomicClaim,
    Citation,
    ComplianceState,
    Finding,
)
from compliance_sentinel.workflow import (
    ComplianceSentinel,
    _force_cross_model_for_high_risk_findings,
    _has_revisable_partial,
    analyze_text,
)


def _make_finding(
    *,
    fid="F-1",
    law_name="개인정보보호법",
    article_no="15",
    citation_text="조항 원문",
    verifier_status=None,
    risk_level=None,
    severity=None,
):
    f = Finding(
        id=fid,
        source_text="원본 텍스트",
        issue="이슈",
        law_name=law_name,
        article_no=article_no,
        citation_text=citation_text,
        applicability_reason="적용",
        suggested_revision="권고",
    )
    if verifier_status is not None:
        f.verifier_status = verifier_status
    if risk_level is not None:
        f.risk_level = risk_level
    if severity is not None:
        f.severity = severity
    return f


class TestComplianceSentinelConstruction:
    def test_default_construction(self):
        sentinel = ComplianceSentinel()
        assert sentinel is not None
        assert sentinel.kb is not None
        assert sentinel.audit_store is not None
        assert sentinel.llm_client is not None
        assert sentinel.memory_rag is not None

    def test_with_explicit_audit_store(self, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        store = AuditStore(tmp_audit_path)
        sentinel = ComplianceSentinel(audit_store=store)
        assert sentinel.audit_store is store


class TestAnalyzeDeterministic:
    def test_basic_analyze_returns_state(self, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        store = AuditStore(tmp_audit_path)
        sentinel = ComplianceSentinel(audit_store=store)
        state = sentinel.analyze("일반적인 텍스트 입력입니다.")
        assert state is not None
        assert state.input_text == "일반적인 텍스트 입력입니다."
        assert state.final_report is not None
        assert "status" in state.final_report

    def test_analyze_classifies_input(self, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        store = AuditStore(tmp_audit_path)
        sentinel = ComplianceSentinel(audit_store=store)
        state = sentinel.analyze("100% 보장 무위험 광고")
        # advertisement or marketing 등 분류 결과 보유
        assert state.input_type in {"advertisement", "compliance_review", "marketing",
                                     "general", "unknown", "policy_announcement"}

    def test_analyze_attaches_audit_log_id(self, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        store = AuditStore(tmp_audit_path)
        sentinel = ComplianceSentinel(audit_store=store)
        state = sentinel.analyze("테스트 텍스트")
        assert state.audit_log_id
        assert state.final_report["audit_log_id"] == state.audit_log_id

    def test_analyze_pii_redaction(self, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        store = AuditStore(tmp_audit_path)
        sentinel = ComplianceSentinel(audit_store=store)
        state = sentinel.analyze("홍길동 900101-1234567 신청")
        # PII 마스킹 발생
        assert "1234567" not in state.redacted_text or len(state.pii_findings) > 0

    def test_analyze_text_wrapper(self, tmp_audit_path):
        report = analyze_text("간단 텍스트", audit_path=tmp_audit_path)
        assert isinstance(report, dict)
        assert "status" in report


class TestForceCrossModel:
    def test_no_findings_returns_false(self, sample_state):
        sample_state.ceo_draft = {"findings": []}
        result = _force_cross_model_for_high_risk_findings(sample_state)
        assert result is False

    def test_empty_ceo_draft_returns_false(self, sample_state):
        sample_state.ceo_draft = {}
        result = _force_cross_model_for_high_risk_findings(sample_state)
        assert result is False

    def test_low_risk_findings_returns_false(self, sample_state):
        finding = _make_finding(verifier_status="PASS", risk_level="LOW")
        sample_state.ceo_draft = {"findings": [finding]}
        sample_state.model_plan = {"cross_model": {}}
        result = _force_cross_model_for_high_risk_findings(sample_state)
        assert result is False

    def test_high_risk_finding_triggers_cross_model(self, sample_state):
        finding = _make_finding(risk_level="HIGH")
        sample_state.ceo_draft = {"findings": [finding]}
        sample_state.model_plan = {"cross_model": {}}
        result = _force_cross_model_for_high_risk_findings(sample_state)
        assert result is True
        assert sample_state.model_plan["cross_model"]["level"] == "STRONG"

    def test_failed_verifier_triggers_cross_model(self, sample_state):
        finding = _make_finding(verifier_status="FAIL")
        sample_state.ceo_draft = {"findings": [finding]}
        sample_state.model_plan = {"cross_model": {}}
        result = _force_cross_model_for_high_risk_findings(sample_state)
        assert result is True

    def test_critical_severity_triggers_cross_model(self, sample_state):
        finding = _make_finding(severity="CRITICAL")
        sample_state.ceo_draft = {"findings": [finding]}
        sample_state.model_plan = {"cross_model": {}}
        result = _force_cross_model_for_high_risk_findings(sample_state)
        assert result is True

    def test_existing_strong_cross_model_not_overwritten(self, sample_state):
        finding = _make_finding(risk_level="HIGH")
        sample_state.ceo_draft = {"findings": [finding]}
        sample_state.model_plan = {"cross_model": {"level": "STRONG"}}
        result = _force_cross_model_for_high_risk_findings(sample_state)
        assert result is False


class _FakeKBArticle:
    def __init__(self, text):
        self.text = text


class _FakeKBForRevisable:
    def __init__(self, articles=None):
        self._articles = articles or {}

    def get_article(self, law_name, article_no):
        return self._articles.get((law_name, article_no))


class TestHasRevisablePartial:
    def test_empty_findings_returns_false(self):
        kb = _FakeKBForRevisable()
        assert _has_revisable_partial([], kb) is False

    def test_non_partial_findings_returns_false(self):
        f = _make_finding(verifier_status="PASS")
        kb = _FakeKBForRevisable({("개인정보보호법", "15"): _FakeKBArticle("KB 원문")})
        assert _has_revisable_partial([f], kb) is False

    def test_partial_with_different_text_returns_true(self):
        f = _make_finding(verifier_status="PARTIAL", citation_text="틀린 인용")
        kb = _FakeKBForRevisable({("개인정보보호법", "15"): _FakeKBArticle("KB 원문")})
        assert _has_revisable_partial([f], kb) is True

    def test_partial_with_same_text_returns_false(self):
        # citation_text가 KB와 동일 → 보정할 필요 없음
        f = _make_finding(verifier_status="PARTIAL", citation_text="KB 원문")
        kb = _FakeKBForRevisable({("개인정보보호법", "15"): _FakeKBArticle("KB 원문")})
        assert _has_revisable_partial([f], kb) is False

    def test_partial_without_kb_article_returns_false(self):
        f = _make_finding(verifier_status="PARTIAL", citation_text="잘못된")
        kb = _FakeKBForRevisable()  # 없는 article
        assert _has_revisable_partial([f], kb) is False
