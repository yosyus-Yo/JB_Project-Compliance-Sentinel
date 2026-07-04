"""수정 제안 토글(include_revision) 동작 검증 (RT5).

핵심 불변식: 토글은 '수정 제안 레이어'(revision_suggestions / marketing_rewrite)만 켜고 끄며,
심의 결과(findings / risk_level / approval_status / verifier_result)는 절대 바꾸지 않는다.

deterministic 모드(prefer_langgraph=False, LLM 키 불필요)에서 검증하여 CI 안정성 확보.
"""
from __future__ import annotations

from compliance_sentinel.engine import _apply_revision_visibility, analyze_with_engine

AD_TEXT = "JB 예금 출시 기념! 누구나 원금 보장과 100% 가입 승인 혜택을 드립니다."
TERMS_TEXT = "본 약관은 회사와 이용자 간의 권리와 의무를 규정합니다. 이용자는 개인정보 제3자 제공에 동의하며 보유기간은 5년입니다."


class TestApplyRevisionVisibilityHelper:
    def test_false_strips_revision_layer(self):
        report = {
            "revision_suggestions": [{"finding_id": "F1"}],
            "marketing_rewrite": {"rewritten": "x"},
            "rewrite_review": {"ok": True},
            "risk_level": "HIGH",
        }
        _apply_revision_visibility(report, include_revision=False)
        assert report["revision_included"] is False
        assert report["revision_suggestions"] == []
        assert "marketing_rewrite" not in report
        assert "rewrite_review" not in report
        # 심의 결과는 불변
        assert report["risk_level"] == "HIGH"

    def test_true_keeps_revision_layer(self):
        report = {
            "revision_suggestions": [{"finding_id": "F1"}],
            "marketing_rewrite": {"rewritten": "x"},
            "risk_level": "HIGH",
        }
        _apply_revision_visibility(report, include_revision=True)
        assert report["revision_included"] is True
        assert report["revision_suggestions"] == [{"finding_id": "F1"}]
        assert report["marketing_rewrite"] == {"rewritten": "x"}

    def test_none_report_noop(self):
        _apply_revision_visibility(None, include_revision=False)  # 예외 없이 통과


def _report(text: str, *, include_revision: bool, tmp_path) -> dict:
    audit = tmp_path / "audit.jsonl"
    result = analyze_with_engine(text, audit_path=audit, prefer_langgraph=False, include_revision=include_revision)
    return result.state.final_report


class TestMarketingToggle:
    def test_review_only_strips_revision(self, tmp_path):
        report = _report(AD_TEXT, include_revision=False, tmp_path=tmp_path)
        assert report["revision_included"] is False
        assert report["revision_suggestions"] == []
        assert "marketing_rewrite" not in report

    def test_with_revision_marks_included(self, tmp_path):
        report = _report(AD_TEXT, include_revision=True, tmp_path=tmp_path)
        assert report["revision_included"] is True
        # revision_suggestions는 정적 제안 — 위반 광고이므로 비어있지 않아야 함
        assert isinstance(report["revision_suggestions"], list)

    def test_verdict_invariant_across_toggle(self, tmp_path):
        """토글 on/off가 심의 결과(findings/risk/approval)를 바꾸지 않음을 증명."""
        off = _report(AD_TEXT, include_revision=False, tmp_path=tmp_path / "off")
        on = _report(AD_TEXT, include_revision=True, tmp_path=tmp_path / "on")
        assert off["risk_level"] == on["risk_level"]
        assert off["approval_status"] == on["approval_status"]
        assert len(off["findings"]) == len(on["findings"])
        # 수정 레이어만 차이
        assert off["revision_suggestions"] == []
        assert on["revision_included"] is True


class TestComplianceToggle:
    def test_review_only_preserves_findings(self, tmp_path):
        """약관 경로: revision_suggestions만 억제, 검증 결과(findings/verifier)는 보존."""
        report = _report(TERMS_TEXT, include_revision=False, tmp_path=tmp_path)
        assert report["review_type"] == "general_compliance_review"
        assert report["revision_included"] is False
        assert report["revision_suggestions"] == []
        # 심의/검증 결과는 그대로 존재 (verifier 자가교정 루프 불변)
        assert "findings" in report
        assert "verifier_result" in report

    def test_with_revision_marks_included(self, tmp_path):
        report = _report(TERMS_TEXT, include_revision=True, tmp_path=tmp_path)
        assert report["review_type"] == "general_compliance_review"
        assert report["revision_included"] is True

    def test_verdict_invariant_across_toggle(self, tmp_path):
        off = _report(TERMS_TEXT, include_revision=False, tmp_path=tmp_path / "off")
        on = _report(TERMS_TEXT, include_revision=True, tmp_path=tmp_path / "on")
        assert off["risk_level"] == on["risk_level"]
        assert off["status"] == on["status"]
        assert len(off["findings"]) == len(on["findings"])
