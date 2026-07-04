from __future__ import annotations

import hashlib

from .board import diagnose_board
from .eval_metrics import run_rag_quality_gates, summarize_gate_results
from .models import ComplianceState, Finding, to_plain
from .report_schema import validate_final_report


def _approval_status(status: str, confidence: str) -> str:
    if status == "PASSED":
        return "APPROVED"
    if confidence == "FAILED":
        return "HUMAN_REVIEW_REQUIRED"
    return "HUMAN_REVIEW_REQUIRED"


def _confidence_score(confidence: str, risk_level: str) -> float:
    if confidence == "FAILED":
        return 0.32
    if confidence == "PARTIAL":
        return 0.62
    if confidence == "FEEDBACK":
        return 0.78
    if confidence == "PERFECT":
        return 0.96
    return 0.88 if risk_level in {"LOW", "MEDIUM"} else 0.72


def _review_request_id(input_text: str) -> str:
    return f"RR-{hashlib.sha256(input_text.encode('utf-8')).hexdigest()[:12]}"


def _input_completeness(state: ComplianceState) -> dict:
    inferred = {
        "input_type": state.input_type,
        "target_audience": "general_customer",
    }
    missing = [key for key, value in inferred.items() if value in {"", "unknown", None}]
    return {
        "accepted": bool(state.input_text.strip()),
        "mode": "text_only_demo_with_inferred_metadata",
        "provided_fields": ["content"],
        "inferred_fields": inferred,
        "missing_or_unknown_fields": missing,
        "requires_form_completion_for_production": bool(missing),
    }


def _evidence_list(findings: list[Finding]) -> list[dict]:
    evidence: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        key = (finding.law_name, finding.article_no, finding.citation_text)
        if key in seen:
            continue
        evidence.append({
            "source": finding.law_name,
            "article_no": finding.article_no,
            "citation_text": finding.citation_text,
            "confidence": 0.45 if finding.verifier_status == "FAIL" else 0.78 if finding.verifier_status == "PARTIAL" else 1.0,
            "finding_ids": [item.id for item in findings if (item.law_name, item.article_no, item.citation_text) == key],
        })
        seen.add(key)
    return evidence


def _revision_suggestions(findings: list[Finding]) -> list[dict]:
    return [
        {
            "finding_id": finding.id,
            "original": finding.source_text[:160],
            "revised": finding.suggested_revision,
            "reason": finding.applicability_reason,
        }
        for finding in findings
        if finding.suggested_revision
    ]


def _verifier_result(findings: list[Finding], state: ComplianceState) -> dict:
    failed = sum(1 for finding in findings if finding.verifier_status == "FAIL")
    partial = sum(1 for finding in findings if finding.verifier_status == "PARTIAL")
    if failed:
        status = "FAILED"
    elif partial:
        status = "PARTIAL"
    else:
        status = "PASSED"
    return {
        "status": status,
        "checked_claims": len(state.atomic_claims) or len(findings),
        "failed_claims": failed,
        "partial_claims": partial,
        "method": "atomic_claim_law_exists_verbatim_applicability_check",
    }


def _board_diagnostics(state: ComplianceState) -> dict:
    if state.board_diagnostics is None and state.board_opinions:
        state.board_diagnostics = diagnose_board(state.board_opinions, audit_log_id=state.audit_log_id)
    return to_plain(state.board_diagnostics) if state.board_diagnostics is not None else {}


def _board_member_opinions(state: ComplianceState) -> list[dict]:
    rows: list[dict] = []
    for persona, opinion in state.board_opinions.items():
        risk = str(getattr(opinion, "risk_level", "LOW"))
        rows.append({
            "persona": persona,
            "title": str(getattr(opinion, "stance", persona)),
            "risk_level": risk,
            "opinion": _board_opinion_label(risk),
            "comment": str(getattr(opinion, "rationale", "")),
        })
    return rows


def _board_opinion_label(risk: str) -> str:
    risk = str(risk).upper()
    if risk == "CRITICAL":
        return "REJECT"
    if risk == "HIGH":
        return "HUMAN"
    if risk == "MEDIUM":
        return "AMEND"
    return "APPROVE"


def _llm_degraded_summary(state: ComplianceState) -> dict:
    reasons: set[str] = set()
    for call in state.llm_calls:
        if call.get("deterministic_fallback") or call.get("error"):
            reasons.add("llm_call_fallback_or_error")
    cross = getattr(state, "cross_model_result", {}) or {}
    if cross.get("deterministic_fallback") or cross.get("error"):
        reasons.add("cross_model_fallback_or_error")
    return {"degraded": bool(reasons), "reasons": sorted(reasons)}


def build_final_report(state: ComplianceState) -> dict:
    """CONFIDENCE 5등급 (Phase 9 P4, T-908) 분기 활성.

    등급 결정 알고리즘:
      - FAILED:   verifier FAIL ≥ 1
      - FEEDBACK: retry_count ≥ 1 + 최종 모든 finding PASS (revise loop가 발동했고 성공)
      - PERFECT:  retry_count == 0 + 모든 finding PASS + risk LOW + PARTIAL/FAIL 0
      - VERIFIED: retry_count == 0 + 모든 finding PASS (risk MEDIUM 이상 또는 PARTIAL 일부)
      - PARTIAL:  partial_count ≥ 1 + FAIL 0
    """
    findings: list[Finding] = state.ceo_draft.get("findings", [])
    fail_count = sum(1 for finding in findings if finding.verifier_status == "FAIL")
    partial_count = sum(1 for finding in findings if finding.verifier_status == "PARTIAL")
    pass_count = sum(1 for finding in findings if finding.verifier_status == "PASS")
    risk_level = state.ceo_draft.get("risk_level", "LOW")
    retry_count = getattr(state, "retry_count", 0)

    # CONFIDENCE 5등급 분기 (T-908 활성)
    if fail_count > 0:
        confidence = "FAILED"
        status = "HUMAN_REVIEW_REQUIRED"
        human_review_needed = True
    elif partial_count > 0:
        # PARTIAL 잔존 → human review 권장
        confidence = "PARTIAL"
        status = "HUMAN_REVIEW_REQUIRED"
        human_review_needed = True
    elif retry_count >= 1 and pass_count > 0:
        # revise loop가 발동했고 최종 PASS — system working as designed (FEEDBACK 신호)
        confidence = "FEEDBACK"
        status = "HUMAN_REVIEW_REQUIRED" if risk_level in ("HIGH", "CRITICAL") else "PASSED"
        human_review_needed = risk_level in ("HIGH", "CRITICAL")
    elif retry_count == 0 and pass_count > 0 and risk_level == "LOW":
        # 모든 finding PASS + revise 미발동 + risk LOW → 완벽 검증
        confidence = "PERFECT"
        status = "PASSED"
        human_review_needed = False
    elif risk_level in ("HIGH", "CRITICAL"):
        # 모든 finding PASS이지만 risk 등급 자체가 HIGH → 검증은 정상이나 human review 필요
        confidence = "VERIFIED"
        status = "HUMAN_REVIEW_REQUIRED"
        human_review_needed = True
    else:
        # standard case
        confidence = "VERIFIED"
        status = "PASSED"
        human_review_needed = False

    cross_model_result = getattr(state, "cross_model_result", {}) or {}
    llm_degraded = _llm_degraded_summary(state)
    if cross_model_result.get("cross_model_confidence") in {"FAILED", "PARTIAL", "FEEDBACK"}:
        human_review_needed = True
        status = "HUMAN_REVIEW_REQUIRED"

    state.human_review_needed = human_review_needed
    report = {
        "review_type": "general_compliance_review",
        "review_request_id": _review_request_id(state.input_text),
        "input_completeness": _input_completeness(state),
        "status": status,
        "approval_status": _approval_status(status, confidence),
        "risk_level": risk_level,
        "confidence": confidence,
        "confidence_score": _confidence_score(confidence, risk_level),
        "language": "unknown",
        "channel": "notice" if state.input_type in {"terms", "contract"} else "unknown",
        "product_type": "unknown",
        "retry_count": retry_count,
        "summary": state.ceo_draft.get("summary", "준법 검토 결과입니다."),
        "llm_degraded": llm_degraded["degraded"],
        "llm_degraded_reasons": llm_degraded["reasons"],
        "llm_degradation_reasons": llm_degraded["reasons"],
        "findings": [to_plain(finding) for finding in findings],
        "evidence": _evidence_list(findings),
        "revision_suggestions": _revision_suggestions(findings),
        "board_diagnostics": _board_diagnostics(state),
        "board_member_opinions": _board_member_opinions(state),
        "verifier_result": _verifier_result(findings, state),
        "audit_log_id": state.audit_log_id,
        "human_review_needed": human_review_needed,
        "routing_decision": state.routing_decision,
        "model_plan": state.model_plan,
        "llm_calls": state.llm_calls,
        "cross_model_result": cross_model_result,
        "memory_context": {
            "short_term": state.short_term_memory,
            "long_term": state.long_term_memory,
        },
        "rag_metadata": state.rag_metadata,
        # PII 마스킹 결과 노출 (UI에서 PII 감지 카운트/마스킹 미리보기 표시용).
        # raw input은 절대 노출하지 않으며 redacted_text + finding kind/replacement만 전달.
        # value(원본 PII)는 제외 — to_plain은 raw value를 직렬화하므로 사용 금지 (PIPA 준수).
        "pii_findings": [
            {"kind": f.kind, "replacement": f.replacement, "start": f.start, "end": f.end}
            for f in (state.pii_findings or [])
        ],
        "pii_count": len(state.pii_findings or []),
        "redacted_text": state.redacted_text or "",
        "disclaimer": state.ceo_draft.get("disclaimer", "본 결과는 법률 자문이 아닌 준법 검토 보조 및 리스크 탐지 결과입니다."),
    }
    report["schema_validation"] = {
        "schema_version": "compliance-sentinel-final-report/v2",
        "passed": not validate_final_report(report),
        "errors": validate_final_report(report),
    }
    report["rag_quality_gates"] = summarize_gate_results(run_rag_quality_gates(report))
    return report


def render_markdown(report: dict) -> str:
    lines = [
        "# Compliance Sentinel Report",
        "",
        f"- Status: {report.get('status', report.get('approval_status', 'UNKNOWN'))}",
        f"- Risk Level: {report.get('risk_level', 'UNKNOWN')}",
        f"- Confidence: {report.get('confidence', 'UNKNOWN')}",
        f"- Human Review Needed: {report.get('human_review_needed', False)}",
        "",
        f"> {report.get('disclaimer', '본 결과는 법률 자문이 아닌 준법 검토 보조입니다.')}",
        "",
        "## Summary",
        report["summary"],
        "",
        "## Findings",
    ]
    for finding in report.get("findings", []):
        lines.extend([
            f"### {finding['id']} — {finding['verifier_status']}",
            f"- Issue: {finding['issue']}",
            f"- Citation: {finding['law_name']} 제{finding['article_no']}조",
            f"- Reason: {finding['applicability_reason']}",
            f"- Suggested revision: {finding['suggested_revision']}",
            "",
        ])
    return "\n".join(lines)
