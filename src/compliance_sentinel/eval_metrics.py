"""Eval Metrics — DeepEval/RAGAS 대신 자체 metric (offline-first).

목적:
  - DeepEval / RAGAS SDK 통합은 P5+ (외부 API key 필요)
  - 본 모듈은 deterministic metric으로 회귀 테스트 가능한 baseline 제공
  - faithfulness / citation_existence / citation_verbatim / pii_redaction / disclaimer_present

Production:
  - DeepEval 설치 후 G-Eval / FaithfulnessMetric 추가 호출 (P5+)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .knowledge_base import LawKnowledgeBase, normalize, normalize_article_no


@dataclass
class MetricResult:
    metric: str
    score: float  # 0.0-1.0
    passed: bool
    threshold: float
    detail: str = ""


def measure_citation_existence(final_report: dict, kb: LawKnowledgeBase) -> MetricResult:
    """모든 finding의 citation이 KB에 실재하는가?

    threshold: 1.0 (citation hallucination rate = 0)
    """
    findings = final_report.get("findings") or []
    if not findings:
        return MetricResult(
            "citation_existence", 1.0, True, 1.0, detail="no findings to check"
        )
    found = 0
    for f in findings:
        article = kb.get_article(f.get("law_name", ""), f.get("article_no", ""))
        if article:
            found += 1
    score = found / len(findings)
    return MetricResult(
        "citation_existence",
        score=score,
        passed=score >= 1.0,
        threshold=1.0,
        detail=f"{found}/{len(findings)} citations exist in KB",
    )


def measure_citation_verbatim(final_report: dict, kb: LawKnowledgeBase) -> MetricResult:
    """citation_text가 KB 원문과 일치하는가?

    threshold: 0.85 (대부분 finding은 원문 verbatim 일치 또는 PARTIAL 보정 후)
    """
    findings = final_report.get("findings") or []
    if not findings:
        return MetricResult(
            "citation_verbatim", 1.0, True, 0.85, detail="no findings to check"
        )
    verbatim_pass = 0
    for f in findings:
        article = kb.get_article(f.get("law_name", ""), f.get("article_no", ""))
        if not article:
            continue
        if normalize(article.text) == normalize(f.get("citation_text", "")):
            verbatim_pass += 1
    score = verbatim_pass / len(findings)
    return MetricResult(
        "citation_verbatim",
        score=score,
        passed=score >= 0.85,
        threshold=0.85,
        detail=f"{verbatim_pass}/{len(findings)} verbatim match",
    )


def measure_pii_redaction(redacted_text: str, original_input: str) -> MetricResult:
    """원문 PII가 redacted_text에 남아있는가?

    threshold: 1.0 (어떤 raw PII도 남으면 fail)
    """
    raw_pii_markers = ["900101-1234567", "010-1234-5678", "user@example.com"]
    leaked = [m for m in raw_pii_markers if m in original_input and m in redacted_text]
    score = 1.0 if not leaked else 0.0
    return MetricResult(
        "pii_redaction",
        score=score,
        passed=score >= 1.0,
        threshold=1.0,
        detail=f"leaked={leaked}" if leaked else "all PII masked",
    )


def measure_disclaimer_present(final_report: dict) -> MetricResult:
    """최종 보고서에 disclaimer 포함 여부.

    threshold: 1.0 (모든 보고서는 "법률 자문 아님" 명시 의무)
    """
    disclaimer = final_report.get("disclaimer", "") or ""
    has_disclaimer = bool(disclaimer) and ("법률 자문" in disclaimer or "준법 검토 보조" in disclaimer)
    return MetricResult(
        "disclaimer_present",
        score=1.0 if has_disclaimer else 0.0,
        passed=has_disclaimer,
        threshold=1.0,
        detail=disclaimer[:80] if disclaimer else "MISSING",
    )


def measure_human_review_routing(final_report: dict) -> MetricResult:
    """위험 등급/confidence와 human_review_needed 정합성.

    HIGH/CRITICAL risk 또는 PARTIAL/FAILED confidence이면 human_review_needed=True여야 함.
    """
    risk = final_report.get("risk_level", "LOW")
    conf = final_report.get("confidence", "VERIFIED")
    needed = bool(final_report.get("human_review_needed"))
    should_be_needed = risk in ("HIGH", "CRITICAL") or conf in ("PARTIAL", "FAILED", "FEEDBACK")
    consistent = needed == should_be_needed
    return MetricResult(
        "human_review_routing",
        score=1.0 if consistent else 0.0,
        passed=consistent,
        threshold=1.0,
        detail=f"risk={risk}, conf={conf}, needed={needed}, expected={should_be_needed}",
    )


def measure_rag_source_coverage(final_report: dict) -> MetricResult:
    """Retrieved context/provenance exists for reports with findings.

    This is an offline proxy for RAGAS context precision/faithfulness: it checks
    that a report exposing findings also exposes retrieved law provenance or
    document RAG chunks, instead of relying on ungrounded model text.
    """

    findings = final_report.get("findings") or []
    rag = final_report.get("rag_metadata") or {}
    provenance = rag.get("retrieved_law_provenance") or []
    document_count = int(rag.get("document_rag_count") or 0)
    if not findings:
        return MetricResult("rag_source_coverage", 1.0, True, 0.75, detail="no findings to ground")
    score = 1.0 if provenance or document_count > 0 else 0.0
    return MetricResult(
        "rag_source_coverage",
        score=score,
        passed=score >= 0.75,
        threshold=0.75,
        detail=f"findings={len(findings)}, law_provenance={len(provenance)}, document_chunks={document_count}",
    )


def measure_memory_rag_presence(final_report: dict) -> MetricResult:
    """Report exposes short/long memory and RAG metadata needed for auditability."""

    has_memory = isinstance(final_report.get("memory_context"), dict)
    has_rag = isinstance(final_report.get("rag_metadata"), dict)
    score = (0.5 if has_memory else 0.0) + (0.5 if has_rag else 0.0)
    return MetricResult(
        "memory_rag_presence",
        score=score,
        passed=score >= 1.0,
        threshold=1.0,
        detail=f"memory_context={has_memory}, rag_metadata={has_rag}",
    )


def measure_kb_production_readiness(kb: LawKnowledgeBase) -> MetricResult:
    """KB production readiness gate based on coverage_report().

    This gate is informational for MVP: a fail means operational expansion is
    still needed, not that local deterministic review cannot run.
    """

    report = kb.coverage_report()
    ready = bool(report.get("production_ready"))
    blockers = {
        "article_count": report.get("article_count"),
        "stale_count": report.get("stale_count"),
        "unverified_count": report.get("unverified_count"),
        "placeholder_count": report.get("placeholder_count"),
    }
    return MetricResult(
        "kb_production_readiness",
        score=1.0 if ready else 0.0,
        passed=ready,
        threshold=1.0,
        detail=str(blockers),
    )


def run_rag_quality_gates(final_report: dict, *, kb: Optional[LawKnowledgeBase] = None, include_production_gate: bool = False) -> list[MetricResult]:
    """Offline RAG/memory quality gates suitable for CI or health panels."""

    kb = kb or LawKnowledgeBase.from_json()
    results = [
        measure_rag_source_coverage(final_report),
        measure_memory_rag_presence(final_report),
    ]
    if include_production_gate:
        results.append(measure_kb_production_readiness(kb))
    return results


def summarize_gate_results(results: list[MetricResult]) -> dict:
    return {
        "passed": all(result.passed for result in results),
        "passed_count": sum(1 for result in results if result.passed),
        "failed_count": sum(1 for result in results if not result.passed),
        "results": [result.__dict__ for result in results],
    }


def run_all_gates(
    final_report: dict,
    *,
    redacted_text: Optional[str] = None,
    original_input: Optional[str] = None,
    kb: Optional[LawKnowledgeBase] = None,
) -> list[MetricResult]:
    """모든 게이트 한 번에 평가. CI 통합용.

    threshold 위반 시 caller가 PR merge 차단 가능 (P5+).
    """
    kb = kb or LawKnowledgeBase.from_json()
    results: list[MetricResult] = []
    results.append(measure_citation_existence(final_report, kb))
    results.append(measure_citation_verbatim(final_report, kb))
    if redacted_text is not None and original_input is not None:
        results.append(measure_pii_redaction(redacted_text, original_input))
    results.append(measure_disclaimer_present(final_report))
    results.append(measure_human_review_routing(final_report))
    results.extend(run_rag_quality_gates(final_report, kb=kb, include_production_gate=False))
    return results
