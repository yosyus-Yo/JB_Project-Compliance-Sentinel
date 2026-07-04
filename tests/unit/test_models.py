"""models.py — 13 dataclass + to_plain helper.

대상: src/compliance_sentinel/models.py
LLM 호출 없음 (pure dataclass).
"""
from __future__ import annotations

import pytest

from compliance_sentinel.models import (
    AtomicClaim,
    BoardDiagnostics,
    BoardOpinion,
    Citation,
    ComplianceState,
    Finding,
    LawArticle,
    MinorityOpinion,
    PIIFinding,
    VerifierResult,
    to_plain,
)


class TestDataclassConstruction:
    def test_law_article(self, sample_law_article):
        assert sample_law_article.law_name == "개인정보보호법"
        assert sample_law_article.article_no == "15"
        assert "개인정보" in sample_law_article.keywords

    def test_pii_finding(self, sample_pii_finding):
        assert sample_pii_finding.kind == "rrn"
        assert sample_pii_finding.replacement.startswith("[RRN_REDACTED")

    def test_citation(self, sample_citation):
        assert sample_citation.law_name == "개인정보보호법"

    def test_finding_default_verifier_status(self, sample_finding):
        assert sample_finding.verifier_status == "PARTIAL"

    def test_board_opinion(self, sample_board_opinion):
        assert sample_board_opinion.risk_level == "MEDIUM"

    def test_minority_opinion(self):
        m = MinorityOpinion(persona="contrarian-agent", risk_level="HIGH",
                            rationale="r", why_minority="majority=LOW 5 vs 1")
        assert m.persona == "contrarian-agent"

    def test_atomic_claim(self, sample_citation):
        c = AtomicClaim(id="F-001-C1", finding_id="F-001",
                        kind="law_exists", citation=sample_citation, statement="법령 존재")
        assert c.kind == "law_exists"

    def test_verifier_result(self):
        r = VerifierResult(claim_id="c1", status="PASS", reason="OK")
        assert r.status == "PASS"

    def test_board_diagnostics_defaults(self):
        diag = BoardDiagnostics(
            risk_distribution={"LOW": 3},
            majority_risk="LOW",
            disagreement_score=0.0,
        )
        assert diag.minority_opinions == []
        assert diag.requires_human_arbitration is False

    def test_compliance_state_defaults(self):
        state = ComplianceState(input_text="x")
        assert state.input_type == "unknown"
        assert state.pii_findings == []
        assert state.retry_count == 0

    def test_compliance_state_add_trace(self, sample_state):
        sample_state.add_trace("test_node", foo="bar", count=3)
        assert len(sample_state.trace) == 1
        assert sample_state.trace[0]["node"] == "test_node"
        assert sample_state.trace[0]["foo"] == "bar"


class TestToPlain:
    def test_dataclass_converted(self, sample_finding):
        result = to_plain(sample_finding)
        assert isinstance(result, dict)
        assert result["id"] == "F-001"

    def test_nested_dataclass(self, sample_law_article):
        wrapped = {"article": sample_law_article}
        result = to_plain(wrapped)
        assert result["article"]["law_name"] == "개인정보보호법"

    def test_list_of_dataclasses(self, sample_law_article):
        result = to_plain([sample_law_article, sample_law_article])
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(item, dict) for item in result)

    def test_primitive_passes_through(self):
        assert to_plain("string") == "string"
        assert to_plain(42) == 42
        assert to_plain(None) is None

    def test_dict_keys_as_strings(self):
        result = to_plain({1: "a", 2: "b"})
        assert result == {"1": "a", "2": "b"}
