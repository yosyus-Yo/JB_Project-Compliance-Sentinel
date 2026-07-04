"""M9 Verifier 단위 테스트.

대상: src/compliance_sentinel/verifier.py
  - extract_atomic_claims(findings) — 5 claims per finding (C1~C5)
  - verify_claims(claims, kb) — KB 대조 검증
  - has_failures(results)
  - normalize_text(value)
  - has_applicability_signal(value)
  - is_effective_date_valid(date)
  - has_scope_overlap(article, source_text)

LLM 호출 없음 (LawKnowledgeBase에 대한 deterministic check).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from compliance_sentinel.models import LawArticle, VerifierResult
from compliance_sentinel.verifier import (
    extract_atomic_claims,
    has_applicability_signal,
    has_failures,
    has_scope_overlap,
    is_effective_date_valid,
    normalize_text,
)


class TestNormalizeText:
    def test_removes_whitespace(self):
        assert normalize_text("개인정보 보호 법") == "개인정보보호법"

    def test_handles_tabs_and_newlines(self):
        assert normalize_text("a\tb\nc") == "abc"

    def test_empty_string(self):
        assert normalize_text("") == ""


class TestHasApplicabilitySignal:
    @pytest.mark.parametrize(
        "text",
        ["적용 가능합니다", "입력에 적용", "문구가 명확함", "검토 필요", "연결 가능"],
    )
    def test_signals_detected(self, text):
        assert has_applicability_signal(text) is True

    def test_no_signal(self):
        assert has_applicability_signal("일반 텍스트") is False

    def test_empty(self):
        assert has_applicability_signal("") is False


class TestIsEffectiveDateValid:
    def test_valid_past_iso_date(self):
        assert is_effective_date_valid("2020-08-05") is True

    def test_future_date_invalid(self):
        future = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        assert is_effective_date_valid(future) is False

    def test_empty_invalid(self):
        assert is_effective_date_valid("") is False

    def test_short_invalid(self):
        assert is_effective_date_valid("2020") is False

    def test_malformed_invalid(self):
        assert is_effective_date_valid("2020/08/05") is False
        assert is_effective_date_valid("not a date") is False


class TestHasScopeOverlap:
    def test_law_name_in_source(self, sample_law_article):
        assert has_scope_overlap(sample_law_article, "개인정보보호법 제15조 적용") is True

    def test_keyword_in_source(self, sample_law_article):
        # keywords = ["개인정보", "수집", "이용", "동의"]
        assert has_scope_overlap(sample_law_article, "고객 동의 누락") is True

    def test_law_core_token_match(self, sample_law_article):
        # law_name[:4] = "개인정보"
        article = LawArticle(
            law_name="개인정보보호법",
            article_no="1",
            title="t",
            text="x",
            effective_date="2020-01-01",
            source_url="",
            keywords=[],
        )
        # source에 "개인정보" 등장 → core token match
        assert has_scope_overlap(article, "개인정보 처리") is True

    def test_no_overlap(self, sample_law_article):
        assert has_scope_overlap(sample_law_article, "전혀 무관한 내용") is False

    def test_empty_source(self, sample_law_article):
        assert has_scope_overlap(sample_law_article, "") is False


class TestExtractAtomicClaims:
    """1 finding → 5 atomic claims (C1~C5)."""

    def test_emits_5_claims_per_finding(self, sample_finding):
        claims = extract_atomic_claims([sample_finding])
        assert len(claims) == 5

    def test_claim_ids_have_c1_c5_suffix(self, sample_finding):
        claims = extract_atomic_claims([sample_finding])
        suffixes = sorted({c.id.split("-")[-1] for c in claims})
        assert suffixes == ["C1", "C2", "C3", "C4", "C5"]

    def test_claim_kinds_cover_5_types(self, sample_finding):
        claims = extract_atomic_claims([sample_finding])
        kinds = {c.kind for c in claims}
        assert kinds == {
            "law_exists",
            "verbatim_match",
            "applicability",
            "effective_date_check",
            "applicability_scope",
        }

    def test_multiple_findings_multiplied(self, sample_finding):
        # 2 findings → 10 claims
        claims = extract_atomic_claims([sample_finding, sample_finding])
        assert len(claims) == 10

    def test_finding_id_preserved_in_claim_id(self, sample_finding):
        claims = extract_atomic_claims([sample_finding])
        for c in claims:
            assert c.id.startswith(sample_finding.id + "-C")

    def test_citation_attached(self, sample_finding):
        claims = extract_atomic_claims([sample_finding])
        for c in claims:
            assert c.citation.law_name == sample_finding.law_name
            assert c.citation.article_no == sample_finding.article_no


class _FakeKB:
    """In-memory KB stub for verify_claims branch coverage."""

    def __init__(self, articles=None):
        self._articles = articles or {}

    def get_article(self, law_name, article_no):
        return self._articles.get((law_name, article_no))


def _claim(kind, citation, statement="입력 적용 검토 필요"):
    from compliance_sentinel.models import AtomicClaim
    return AtomicClaim(
        id=f"F-001-{kind[:2].upper()}",
        finding_id="F-001",
        kind=kind,
        citation=citation,
        statement=statement,
    )


class TestVerifyClaimsLawExists:
    """C1 law_exists branch."""

    def test_pass_when_article_exists(self, sample_law_article, sample_citation):
        from compliance_sentinel.verifier import verify_claims
        kb = _FakeKB({(sample_citation.law_name, sample_citation.article_no): sample_law_article})
        results = verify_claims([_claim("law_exists", sample_citation)], kb)
        assert results[0].status == "PASS"

    def test_fail_when_missing(self, sample_citation):
        from compliance_sentinel.verifier import verify_claims
        results = verify_claims([_claim("law_exists", sample_citation)], _FakeKB())
        assert results[0].status == "FAIL"


class TestVerifyClaimsVerbatim:
    """C2 verbatim_match branch — 5 cases."""

    def test_fail_when_article_absent(self, sample_citation):
        from compliance_sentinel.verifier import verify_claims
        results = verify_claims([_claim("verbatim_match", sample_citation)], _FakeKB())
        assert results[0].status == "FAIL"

    def test_pass_when_exact_match(self, sample_law_article):
        from compliance_sentinel.models import Citation
        from compliance_sentinel.verifier import verify_claims
        cite = Citation(sample_law_article.law_name, sample_law_article.article_no,
                        sample_law_article.text)
        kb = _FakeKB({(cite.law_name, cite.article_no): sample_law_article})
        results = verify_claims([_claim("verbatim_match", cite)], kb)
        assert results[0].status == "PASS"

    def test_partial_when_substring(self, sample_law_article):
        from compliance_sentinel.models import Citation
        from compliance_sentinel.verifier import verify_claims
        cite = Citation(sample_law_article.law_name, sample_law_article.article_no,
                        sample_law_article.text[:20])  # 일부만
        kb = _FakeKB({(cite.law_name, cite.article_no): sample_law_article})
        results = verify_claims([_claim("verbatim_match", cite)], kb)
        assert results[0].status == "PARTIAL"

    def test_fail_when_mismatch(self, sample_law_article):
        from compliance_sentinel.models import Citation
        from compliance_sentinel.verifier import verify_claims
        cite = Citation(sample_law_article.law_name, sample_law_article.article_no,
                        "전혀 다른 텍스트")
        kb = _FakeKB({(cite.law_name, cite.article_no): sample_law_article})
        results = verify_claims([_claim("verbatim_match", cite)], kb)
        assert results[0].status == "FAIL"

    def test_partial_when_user_citation_marker(self, sample_law_article):
        from compliance_sentinel.models import Citation
        from compliance_sentinel.verifier import verify_claims
        cite = Citation(sample_law_article.law_name, sample_law_article.article_no,
                        "(사용자 인용) 내용")
        kb = _FakeKB({(cite.law_name, cite.article_no): sample_law_article})
        results = verify_claims([_claim("verbatim_match", cite)], kb)
        assert results[0].status == "PARTIAL"


class TestVerifyClaimsApplicability:
    """C3 applicability branch."""

    def test_pass_with_signal(self, sample_law_article, sample_citation):
        from compliance_sentinel.verifier import verify_claims
        kb = _FakeKB({(sample_citation.law_name, sample_citation.article_no): sample_law_article})
        results = verify_claims([_claim("applicability", sample_citation, "적용 가능")], kb)
        assert results[0].status == "PASS"

    def test_partial_without_signal(self, sample_law_article, sample_citation):
        from compliance_sentinel.verifier import verify_claims
        kb = _FakeKB({(sample_citation.law_name, sample_citation.article_no): sample_law_article})
        results = verify_claims([_claim("applicability", sample_citation, "단순 텍스트")], kb)
        assert results[0].status == "PARTIAL"


class TestVerifyClaimsEffectiveDate:
    """C4 effective_date_check branch."""

    def test_pass_with_valid_past_date(self, sample_law_article, sample_citation):
        # sample_law_article.effective_date = "2020-08-05"
        from compliance_sentinel.verifier import verify_claims
        kb = _FakeKB({(sample_citation.law_name, sample_citation.article_no): sample_law_article})
        results = verify_claims([_claim("effective_date_check", sample_citation)], kb)
        assert results[0].status == "PASS"

    def test_partial_with_malformed_date(self, sample_citation):
        from compliance_sentinel.models import LawArticle
        from compliance_sentinel.verifier import verify_claims
        bad = LawArticle(
            law_name=sample_citation.law_name, article_no=sample_citation.article_no,
            title="t", text="x", effective_date="invalid", source_url="", keywords=[],
        )
        kb = _FakeKB({(sample_citation.law_name, sample_citation.article_no): bad})
        results = verify_claims([_claim("effective_date_check", sample_citation)], kb)
        assert results[0].status == "PARTIAL"

    def test_fail_when_article_absent(self, sample_citation):
        from compliance_sentinel.verifier import verify_claims
        results = verify_claims([_claim("effective_date_check", sample_citation)], _FakeKB())
        assert results[0].status == "FAIL"


class TestVerifyClaimsScope:
    """C5 applicability_scope branch."""

    def test_pass_when_keyword_overlaps(self, sample_law_article, sample_citation):
        # sample.keywords = ["개인정보", "수집", "이용", "동의"]
        from compliance_sentinel.verifier import verify_claims
        kb = _FakeKB({(sample_citation.law_name, sample_citation.article_no): sample_law_article})
        results = verify_claims([_claim("applicability_scope", sample_citation, "고객 개인정보 처리")], kb)
        assert results[0].status == "PASS"

    def test_partial_when_no_overlap(self, sample_law_article, sample_citation):
        from compliance_sentinel.verifier import verify_claims
        kb = _FakeKB({(sample_citation.law_name, sample_citation.article_no): sample_law_article})
        results = verify_claims([_claim("applicability_scope", sample_citation, "전혀 무관한 내용")], kb)
        assert results[0].status == "PARTIAL"

    def test_fail_when_article_absent(self, sample_citation):
        from compliance_sentinel.verifier import verify_claims
        results = verify_claims([_claim("applicability_scope", sample_citation, "x")], _FakeKB())
        assert results[0].status == "FAIL"


class TestApplyVerifierResults:
    def test_finding_all_pass_marked_pass(self, sample_finding):
        from compliance_sentinel.verifier import apply_verifier_results
        results = [
            VerifierResult(claim_id=f"{sample_finding.id}-C1", status="PASS", reason=""),
            VerifierResult(claim_id=f"{sample_finding.id}-C2", status="PASS", reason=""),
        ]
        apply_verifier_results([sample_finding], results)
        assert sample_finding.verifier_status == "PASS"

    def test_finding_any_fail_marked_fail(self, sample_finding):
        from compliance_sentinel.verifier import apply_verifier_results
        results = [
            VerifierResult(claim_id=f"{sample_finding.id}-C1", status="PASS", reason=""),
            VerifierResult(claim_id=f"{sample_finding.id}-C2", status="FAIL", reason=""),
        ]
        apply_verifier_results([sample_finding], results)
        assert sample_finding.verifier_status == "FAIL"

    def test_finding_mixed_partial(self, sample_finding):
        from compliance_sentinel.verifier import apply_verifier_results
        results = [
            VerifierResult(claim_id=f"{sample_finding.id}-C1", status="PASS", reason=""),
            VerifierResult(claim_id=f"{sample_finding.id}-C2", status="PARTIAL", reason=""),
        ]
        apply_verifier_results([sample_finding], results)
        assert sample_finding.verifier_status == "PARTIAL"


class TestHasFailures:
    def test_no_failures_when_all_pass(self):
        results = [
            VerifierResult(claim_id="c1", status="PASS", reason=""),
            VerifierResult(claim_id="c2", status="PARTIAL", reason=""),
        ]
        assert has_failures(results) is False

    def test_failure_detected(self):
        results = [
            VerifierResult(claim_id="c1", status="PASS", reason=""),
            VerifierResult(claim_id="c2", status="FAIL", reason="조항 없음"),
        ]
        assert has_failures(results) is True

    def test_empty_no_failures(self):
        assert has_failures([]) is False
