"""M7 6 Compliance Board 단위 테스트.

대상: src/compliance_sentinel/board.py
  - run_compliance_board(text, context) → 6 personas 의견
  - 6 deterministic personas: legal_counsel, pipa_expert, consumer_expert,
    operational_risk, business_practicality, contrarian
  - apply_llm_advisory_to_board(opinions, llm_calls, enabled)
  - max_risk(opinions) → 가장 높은 risk
  - diagnose_board(opinions) → BoardDiagnostics (risk distribution + minority)

LLM 호출 없음 (deterministic keyword matching only).
"""
from __future__ import annotations

import pytest

from compliance_sentinel.board import (
    apply_llm_advisory_to_board,
    business_practicality,
    consumer_expert,
    contrarian,
    diagnose_board,
    legal_counsel,
    max_risk,
    operational_risk,
    pipa_expert,
    run_compliance_board,
)
from compliance_sentinel.models import BoardOpinion, Citation, LawArticle


@pytest.fixture
def sample_citations(sample_law_article):
    return [
        Citation(sample_law_article.law_name, sample_law_article.article_no, sample_law_article.text),
        Citation("금융소비자보호법", "19", "중요한 사항 설명 의무"),
    ]


class TestSixPersonas:
    """6 personas — 각각 keyword 매칭 deterministic."""

    def test_legal_counsel_high_when_terms(self, sample_citations):
        op = legal_counsel("약관 동의서 검토", sample_citations)
        assert op.agent_id == "legal-counsel"
        assert op.risk_level == "MEDIUM"

    def test_legal_counsel_low_when_no_keywords(self, sample_citations):
        op = legal_counsel("일반 안내", sample_citations)
        assert op.risk_level == "LOW"

    def test_pipa_expert_high_on_privacy_terms(self, sample_citations):
        op = pipa_expert("개인정보 제3자 제공", sample_citations)
        assert op.agent_id == "pipa-credit-info-expert"
        assert op.risk_level == "HIGH"

    def test_pipa_expert_low_when_no_privacy(self, sample_citations):
        op = pipa_expert("날씨가 좋다", sample_citations)
        assert op.risk_level == "LOW"

    def test_consumer_expert_high_on_marketing_claims(self, sample_citations):
        op = consumer_expert("100% 승인 무위험 확정 수익", sample_citations)
        assert op.agent_id == "consumer-protection-expert"
        assert op.risk_level == "HIGH"

    def test_consumer_expert_medium_on_ad_keyword(self, sample_citations):
        op = consumer_expert("광고 안내", sample_citations)
        assert op.risk_level == "MEDIUM"

    def test_operational_risk_high_on_bypass(self, sample_citations):
        op = operational_risk("인증 없이 즉시 거래", sample_citations)
        assert op.agent_id == "aml-operational-risk-expert"
        assert op.risk_level == "HIGH"

    def test_operational_risk_medium_on_aml(self, sample_citations):
        op = operational_risk("자금세탁 거래 모니터링", sample_citations)
        assert op.risk_level == "MEDIUM"

    def test_business_practicality_always_medium(self, sample_citations):
        op = business_practicality("아무 내용", sample_citations)
        assert op.agent_id == "business-practicality-expert"
        assert op.risk_level == "MEDIUM"

    def test_contrarian_always_medium(self, sample_citations):
        op = contrarian("아무 내용", sample_citations)
        assert op.agent_id == "contrarian-agent"
        assert op.risk_level == "MEDIUM"


class TestRunComplianceBoard:
    def test_returns_6_personas(self, sample_law_article):
        opinions = run_compliance_board("광고 검토", [sample_law_article])
        assert len(opinions) == 6
        expected_ids = {
            "legal-counsel", "pipa-credit-info-expert", "consumer-protection-expert",
            "aml-operational-risk-expert", "business-practicality-expert", "contrarian-agent",
        }
        assert set(opinions.keys()) == expected_ids

    def test_all_opinions_are_board_opinion(self, sample_law_article):
        opinions = run_compliance_board("광고", [sample_law_article])
        for op in opinions.values():
            assert isinstance(op, BoardOpinion)
            assert op.risk_level in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

    def test_empty_context_still_returns_6(self):
        opinions = run_compliance_board("text", [])
        assert len(opinions) == 6


class TestMaxRisk:
    def _opinion(self, risk):
        return BoardOpinion("a", "stance", risk, "r", [])

    def test_max_picks_highest(self):
        opinions = {
            "a": self._opinion("LOW"),
            "b": self._opinion("HIGH"),
            "c": self._opinion("MEDIUM"),
        }
        assert max_risk(opinions) == "HIGH"

    def test_max_picks_critical(self):
        opinions = {"a": self._opinion("CRITICAL"), "b": self._opinion("HIGH")}
        assert max_risk(opinions) == "CRITICAL"

    def test_all_low(self):
        opinions = {"a": self._opinion("LOW"), "b": self._opinion("LOW")}
        assert max_risk(opinions) == "LOW"


class TestApplyLLMAdvisory:
    def test_disabled_returns_unchanged(self):
        original = {"legal-counsel": BoardOpinion("legal-counsel", "s", "LOW", "r", [])}
        result = apply_llm_advisory_to_board(original, [{"role": "legal_counsel", "risk_level": "HIGH"}], enabled=False)
        assert result["legal-counsel"].risk_level == "LOW"

    def test_enabled_applies_llm_risk(self):
        original = {"legal-counsel": BoardOpinion("legal-counsel", "s", "LOW", "r", [])}
        result = apply_llm_advisory_to_board(
            original,
            [{"called": True, "role": "legal_counsel", "risk_level": "HIGH", "model": "gpt-5.5"}],
            enabled=True,
        )
        assert result["legal-counsel"].risk_level == "HIGH"

    def test_deterministic_fallback_ignored(self):
        original = {"legal-counsel": BoardOpinion("legal-counsel", "s", "LOW", "r", [])}
        result = apply_llm_advisory_to_board(
            original,
            [{"called": True, "deterministic_fallback": True, "role": "legal_counsel", "risk_level": "HIGH"}],
            enabled=True,
        )
        assert result["legal-counsel"].risk_level == "LOW"

    def test_unknown_role_ignored(self):
        original = {"legal-counsel": BoardOpinion("legal-counsel", "s", "LOW", "r", [])}
        result = apply_llm_advisory_to_board(
            original,
            [{"called": True, "role": "unknown_xyz", "risk_level": "HIGH"}],
            enabled=True,
        )
        assert result["legal-counsel"].risk_level == "LOW"


class TestDiagnoseBoard:
    def _opinion(self, agent_id, risk):
        return BoardOpinion(agent_id, "stance", risk, "rationale", [])

    def test_empty_returns_default(self):
        diag = diagnose_board({})
        assert diag.risk_distribution == {}
        assert diag.majority_risk == "LOW"
        assert diag.disagreement_score == 0.0
        assert diag.requires_human_arbitration is False

    def test_unanimous_low_zero_disagreement(self):
        opinions = {
            "a": self._opinion("a", "LOW"),
            "b": self._opinion("b", "LOW"),
            "c": self._opinion("c", "LOW"),
        }
        diag = diagnose_board(opinions)
        assert diag.majority_risk == "LOW"
        assert diag.disagreement_score == 0.0
        assert diag.minority_opinions == []

    def test_split_finds_minority(self):
        opinions = {
            "a": self._opinion("a", "LOW"),
            "b": self._opinion("b", "LOW"),
            "c": self._opinion("c", "HIGH"),
        }
        diag = diagnose_board(opinions)
        assert diag.majority_risk == "LOW"
        # 3 중 1 분기 → 1 - 2/3 = 1/3 ≈ 0.3333
        assert diag.disagreement_score == pytest.approx(0.3333, abs=0.001)
        # minority = HIGH 의견 보유자
        assert len(diag.minority_opinions) == 1
        assert diag.minority_opinions[0].risk_level == "HIGH"

    def test_distribution_counted(self):
        opinions = {
            "a": self._opinion("a", "HIGH"),
            "b": self._opinion("b", "HIGH"),
            "c": self._opinion("c", "MEDIUM"),
            "d": self._opinion("d", "LOW"),
        }
        diag = diagnose_board(opinions)
        assert diag.risk_distribution == {"HIGH": 2, "MEDIUM": 1, "LOW": 1}

    def test_audit_log_id_preserved(self):
        diag = diagnose_board({"a": self._opinion("a", "LOW")}, audit_log_id="AUD-abc")
        assert diag.audit_log_id == "AUD-abc"

    def test_tie_picks_higher_risk_conservatively(self):
        """동률 시 더 위험한 쪽을 majority로 — 준법 보조 원칙."""
        opinions = {
            "a": self._opinion("a", "HIGH"),
            "b": self._opinion("b", "LOW"),
        }
        diag = diagnose_board(opinions)
        assert diag.majority_risk == "HIGH"
