"""M8 CEO Synthesizer 단위 테스트.

대상: src/compliance_sentinel/synthesizer.py
  - synthesize_opinion(text, opinions, user_citations) → ceo_draft dict
  - snippet(text, limit) — 길이 제한 텍스트
  - issue_for(law_name, text) — 법령별 issue 메시지
  - applicability_for(law_name) — 법령별 적용 논리
  - revision_for(law_name) — 법령별 수정 권고

LLM 호출 없음 (deterministic mapping).
"""
from __future__ import annotations

import pytest

from compliance_sentinel.models import BoardOpinion, Citation, Finding
from compliance_sentinel.synthesizer import (
    applicability_for,
    issue_for,
    revision_for,
    snippet,
    synthesize_opinion,
)


class TestSnippet:
    def test_short_text_unchanged(self):
        assert snippet("짧은 텍스트") == "짧은 텍스트"

    def test_long_text_truncated_with_ellipsis(self):
        text = "a" * 300
        result = snippet(text, limit=240)
        assert len(result) == 243  # 240 + "..."
        assert result.endswith("...")

    def test_custom_limit(self):
        result = snippet("hello world", limit=5)
        assert result == "hello..."


class TestIssueFor:
    @pytest.mark.parametrize(
        "law_name,expected_substring",
        [
            ("개인정보보호법", "개인정보"),
            ("신용정보의 이용 및 보호에 관한 법률", "개인신용정보"),
            ("금융소비자보호법", "중요사항"),
            ("금융광고 가이드라인", "오인 광고"),
            ("전자금융거래법", "전자금융"),
            ("미지의 법", "준법 리스크"),
        ],
    )
    def test_issue_mapping(self, law_name, expected_substring):
        assert expected_substring in issue_for(law_name, "any text")


class TestApplicabilityFor:
    def test_privacy_law_explanation(self):
        result = applicability_for("개인정보보호법")
        assert "개인정보" in result or "신용정보" in result

    def test_consumer_law_explanation(self):
        result = applicability_for("금융소비자보호법")
        assert "중요사항" in result or "권유" in result

    def test_advertising_law_explanation(self):
        result = applicability_for("금융광고 가이드라인")
        assert "광고" in result or "보장" in result

    def test_default_for_unknown(self):
        result = applicability_for("미지의 법")
        assert "업무 맥락" in result


class TestRevisionFor:
    def test_privacy_revision_mentions_purpose(self):
        result = revision_for("개인정보보호법")
        assert "목적" in result or "동의" in result

    def test_consumer_revision_mentions_risk(self):
        result = revision_for("금융소비자보호법")
        assert "위험" in result or "원금" in result

    def test_advertising_revision_mentions_loss(self):
        result = revision_for("금융광고 가이드라인")
        assert "원금" in result or "손실" in result


class TestSynthesizeOpinion:
    def _opinion(self, agent, risk, citations=None):
        return BoardOpinion(agent, "stance", risk, "rationale", citations or [])

    def test_returns_required_keys(self, sample_citation):
        opinions = {"a": self._opinion("a", "HIGH", [sample_citation])}
        result = synthesize_opinion("input text", opinions)
        for key in ["risk_level", "summary", "findings", "disclaimer"]:
            assert key in result

    def test_no_high_risk_opinions_falls_back_to_default_finding(self):
        opinions = {
            "a": self._opinion("a", "LOW"),
            "b": self._opinion("b", "LOW"),
        }
        result = synthesize_opinion("일반 입력", opinions)
        # LOW only → fallback finding 1개
        assert len(result["findings"]) == 1
        assert result["findings"][0].id == "F-001"

    def test_high_risk_opinion_emits_finding(self, sample_citation):
        opinions = {
            "a": self._opinion("a", "HIGH", [sample_citation]),
        }
        result = synthesize_opinion("개인정보 제공", opinions)
        # HIGH risk + citation → finding emit
        findings = result["findings"]
        assert len(findings) >= 1
        # 첫 finding이 sample_citation의 법령을 인용
        law_names = {f.law_name for f in findings}
        assert sample_citation.law_name in law_names

    def test_user_citations_emitted_first(self):
        user_cite = Citation("사용자 인용법", "100", "사용자 본문")
        opinions = {"a": self._opinion("a", "LOW")}
        result = synthesize_opinion("text", opinions, user_citations=[user_cite])

        findings = result["findings"]
        # 첫 finding이 user_cite 기반
        assert findings[0].law_name == "사용자 인용법"
        assert findings[0].article_no == "100"

    def test_duplicate_citations_deduplicated(self, sample_citation):
        opinions = {
            "a": self._opinion("a", "HIGH", [sample_citation, sample_citation]),
            "b": self._opinion("b", "HIGH", [sample_citation]),
        }
        result = synthesize_opinion("text", opinions)
        # 동일 (law_name, article_no) 키 1번만
        law_keys = {(f.law_name, f.article_no) for f in result["findings"]}
        assert len(law_keys) == len(set(law_keys))

    def test_risk_level_reflects_max(self):
        opinions = {
            "a": self._opinion("a", "LOW"),
            "b": self._opinion("b", "CRITICAL"),
        }
        result = synthesize_opinion("text", opinions)
        assert result["risk_level"] == "CRITICAL"

    def test_disclaimer_present(self):
        opinions = {"a": self._opinion("a", "LOW")}
        result = synthesize_opinion("text", opinions)
        assert "법률 자문" in result["disclaimer"]
