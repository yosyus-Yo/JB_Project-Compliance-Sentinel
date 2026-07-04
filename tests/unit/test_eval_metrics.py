"""eval_metrics.py — 9 measure_* + RAG quality gates."""
from __future__ import annotations

import pytest

from compliance_sentinel.eval_metrics import (
    MetricResult,
    measure_disclaimer_present,
    measure_human_review_routing,
    measure_memory_rag_presence,
    measure_pii_redaction,
    measure_rag_source_coverage,
    run_rag_quality_gates,
    summarize_gate_results,
)


class TestMetricResult:
    def test_construction(self):
        # 실제 시그니처: metric, score, passed, threshold, detail=""
        m = MetricResult(metric="test", score=1.0, passed=True, threshold=0.5, detail="ok")
        assert m.passed is True
        assert m.score == 1.0
        assert m.metric == "test"


class TestPIIRedaction:
    def test_passes_when_pii_redacted(self):
        result = measure_pii_redaction(
            redacted_text="[RRN_REDACTED_1] 처리",
            original_input="900101-1234567 처리",
        )
        assert result.passed is True

    def test_fails_when_pii_leaks(self):
        result = measure_pii_redaction(
            redacted_text="900101-1234567 처리",
            original_input="900101-1234567 처리",
        )
        assert result.passed is False


class TestDisclaimerPresent:
    def test_passes_with_disclaimer(self):
        report = {"disclaimer": "본 결과는 법률 자문이 아닌 준법 검토입니다."}
        result = measure_disclaimer_present(report)
        assert result.passed is True

    def test_fails_when_missing(self):
        result = measure_disclaimer_present({})
        assert result.passed is False

    def test_fails_when_empty(self):
        result = measure_disclaimer_present({"disclaimer": ""})
        assert result.passed is False


class TestHumanReviewRouting:
    def test_passes_when_high_risk_routed_to_review(self):
        report = {"risk_level": "HIGH", "human_review_needed": True}
        result = measure_human_review_routing(report)
        assert result.passed is True

    def test_passes_when_low_risk_auto(self):
        report = {"risk_level": "LOW", "human_review_needed": False}
        result = measure_human_review_routing(report)
        assert result.passed is True

    def test_fails_when_high_risk_no_review(self):
        report = {"risk_level": "HIGH", "human_review_needed": False}
        result = measure_human_review_routing(report)
        assert result.passed is False


class TestRagSourceCoverage:
    def test_returns_metric_result(self):
        report = {
            "rag_metadata": {"law_count": 5},
            "findings": [],
        }
        result = measure_rag_source_coverage(report)
        assert isinstance(result, MetricResult)


class TestMemoryRagPresence:
    def test_returns_metric_result(self):
        report = {"rag_metadata": {"memory_hit_count": 2}}
        result = measure_memory_rag_presence(report)
        assert isinstance(result, MetricResult)


class TestRunRagQualityGates:
    def test_returns_list_of_metrics(self):
        report = {
            "disclaimer": "본 결과는 법률 자문이 아닙니다.",
            "human_review_needed": False,
            "risk_level": "LOW",
            "redacted_text": "텍스트",
            "rag_metadata": {"law_count": 5, "memory_hit_count": 2},
            "findings": [],
        }
        results = run_rag_quality_gates(report)
        assert isinstance(results, list)
        assert all(isinstance(r, MetricResult) for r in results)


class _FakeKB:
    """In-memory KB stub for citation_existence/verbatim tests."""

    def __init__(self, articles=None):
        self._articles = articles or {}

    def get_article(self, law_name, article_no):
        return self._articles.get((law_name, article_no))


class TestCitationExistence:
    def test_no_findings_returns_pass(self):
        from compliance_sentinel.eval_metrics import measure_citation_existence
        result = measure_citation_existence({"findings": []}, _FakeKB())
        assert result.passed is True
        assert result.score == 1.0

    def test_all_citations_exist(self, sample_law_article):
        from compliance_sentinel.eval_metrics import measure_citation_existence
        kb = _FakeKB({(sample_law_article.law_name, sample_law_article.article_no): sample_law_article})
        report = {"findings": [{"law_name": sample_law_article.law_name,
                                 "article_no": sample_law_article.article_no}]}
        result = measure_citation_existence(report, kb)
        assert result.passed is True

    def test_some_citations_missing(self, sample_law_article):
        from compliance_sentinel.eval_metrics import measure_citation_existence
        kb = _FakeKB({(sample_law_article.law_name, sample_law_article.article_no): sample_law_article})
        report = {"findings": [
            {"law_name": sample_law_article.law_name, "article_no": sample_law_article.article_no},
            {"law_name": "없는 법", "article_no": "999"},
        ]}
        result = measure_citation_existence(report, kb)
        assert result.passed is False
        assert result.score == 0.5


class TestCitationVerbatim:
    def test_no_findings_passes(self):
        from compliance_sentinel.eval_metrics import measure_citation_verbatim
        result = measure_citation_verbatim({"findings": []}, _FakeKB())
        assert result.passed is True

    def test_verbatim_match_passes(self, sample_law_article):
        from compliance_sentinel.eval_metrics import measure_citation_verbatim
        kb = _FakeKB({(sample_law_article.law_name, sample_law_article.article_no): sample_law_article})
        report = {"findings": [{
            "law_name": sample_law_article.law_name,
            "article_no": sample_law_article.article_no,
            "citation_text": sample_law_article.text,
        }]}
        result = measure_citation_verbatim(report, kb)
        assert result.passed is True


class TestPiiRedactionLeakDetection:
    def test_specific_pii_markers_detected(self):
        from compliance_sentinel.eval_metrics import measure_pii_redaction
        result = measure_pii_redaction(
            redacted_text="010-1234-5678 처리",  # 마스킹 안 됨
            original_input="홍길동 010-1234-5678 처리",
        )
        assert result.passed is False


class TestRagSourceCoverage:
    def test_no_findings_passes(self):
        from compliance_sentinel.eval_metrics import measure_rag_source_coverage
        result = measure_rag_source_coverage({"findings": []})
        assert result.passed is True

    def test_findings_without_provenance_fails(self):
        from compliance_sentinel.eval_metrics import measure_rag_source_coverage
        result = measure_rag_source_coverage({
            "findings": [{"id": "F-1"}],
            "rag_metadata": {},
        })
        assert result.passed is False

    def test_findings_with_law_provenance_passes(self):
        from compliance_sentinel.eval_metrics import measure_rag_source_coverage
        result = measure_rag_source_coverage({
            "findings": [{"id": "F-1"}],
            "rag_metadata": {"retrieved_law_provenance": [{"law_name": "x", "article_no": "1"}]},
        })
        assert result.passed is True

    def test_findings_with_document_rag_passes(self):
        from compliance_sentinel.eval_metrics import measure_rag_source_coverage
        result = measure_rag_source_coverage({
            "findings": [{"id": "F-1"}],
            "rag_metadata": {"document_rag_count": 3},
        })
        assert result.passed is True


class TestMemoryRagPresence:
    def test_both_present_passes(self):
        from compliance_sentinel.eval_metrics import measure_memory_rag_presence
        result = measure_memory_rag_presence({"memory_context": {}, "rag_metadata": {}})
        assert result.passed is True
        assert result.score == 1.0

    def test_only_one_partial_score(self):
        from compliance_sentinel.eval_metrics import measure_memory_rag_presence
        result = measure_memory_rag_presence({"memory_context": {}})
        assert result.passed is False
        assert result.score == 0.5

    def test_neither_fails(self):
        from compliance_sentinel.eval_metrics import measure_memory_rag_presence
        result = measure_memory_rag_presence({})
        assert result.passed is False
        assert result.score == 0.0


class TestHumanReviewRoutingDetail:
    def test_low_risk_no_review_consistent(self):
        from compliance_sentinel.eval_metrics import measure_human_review_routing
        result = measure_human_review_routing({"risk_level": "LOW", "confidence": "VERIFIED",
                                                "human_review_needed": False})
        assert result.passed is True

    def test_critical_with_review_consistent(self):
        from compliance_sentinel.eval_metrics import measure_human_review_routing
        result = measure_human_review_routing({"risk_level": "CRITICAL", "confidence": "VERIFIED",
                                                "human_review_needed": True})
        assert result.passed is True

    def test_partial_confidence_requires_review(self):
        from compliance_sentinel.eval_metrics import measure_human_review_routing
        result = measure_human_review_routing({"risk_level": "LOW", "confidence": "PARTIAL",
                                                "human_review_needed": False})
        assert result.passed is False  # PARTIAL은 review 필수


class TestDisclaimerPresentDetail:
    def test_korean_phrase_passes(self):
        from compliance_sentinel.eval_metrics import measure_disclaimer_present
        result = measure_disclaimer_present({"disclaimer": "본 결과는 법률 자문이 아닙니다."})
        assert result.passed is True

    def test_준법_보조_phrase_passes(self):
        from compliance_sentinel.eval_metrics import measure_disclaimer_present
        result = measure_disclaimer_present({"disclaimer": "본 결과는 준법 검토 보조 결과입니다."})
        assert result.passed is True

    def test_irrelevant_disclaimer_fails(self):
        from compliance_sentinel.eval_metrics import measure_disclaimer_present
        result = measure_disclaimer_present({"disclaimer": "단순 안내문"})
        assert result.passed is False


class TestSummarizeGateResults:
    def test_summary_keys(self):
        results = [
            MetricResult(metric="a", score=1.0, passed=True, threshold=0.5),
            MetricResult(metric="b", score=0.0, passed=False, threshold=0.5),
        ]
        summary = summarize_gate_results(results)
        assert isinstance(summary, dict)
        # passed/failed 카운트 또는 비율 키 존재
        flat = str(summary).lower()
        assert any(k in flat for k in ["passed", "failed", "total", "rate", "gate"])

    def test_empty_results(self):
        summary = summarize_gate_results([])
        assert isinstance(summary, dict)
