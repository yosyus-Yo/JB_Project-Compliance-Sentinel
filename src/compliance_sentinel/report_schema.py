from __future__ import annotations

from collections.abc import Mapping
from typing import Any

FINAL_REPORT_REQUIRED_FIELDS: dict[str, type | tuple[type, ...]] = {
    "review_type": str,
    "approval_status": str,
    "risk_level": str,
    "confidence": str,
    "confidence_score": (int, float),
    "language": str,
    "channel": str,
    "product_type": str,
    "findings": list,
    "evidence": list,
    "revision_suggestions": list,
    "board_diagnostics": dict,
    "verifier_result": dict,
    "audit_log_id": str,
    "review_request_id": str,
    "input_completeness": dict,
}

FINAL_REPORT_ALLOWED_APPROVAL = {
    "APPROVED",
    "APPROVE_WITH_CHANGES",
    "REJECTED",
    "HUMAN_REVIEW_REQUIRED",
}
FINAL_REPORT_ALLOWED_RISK = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
FINAL_REPORT_ALLOWED_VERIFIER = {"PASSED", "PARTIAL", "FAILED"}


def validate_final_report(report: Mapping[str, Any]) -> list[str]:
    """Return schema/contract validation errors for judge-facing reports.

    This intentionally avoids an external jsonschema dependency so the offline
    deterministic MVP can validate its output in the default environment.
    """

    errors: list[str] = []
    for key, expected_type in FINAL_REPORT_REQUIRED_FIELDS.items():
        if key not in report:
            errors.append(f"missing:{key}")
            continue
        if not isinstance(report[key], expected_type):
            errors.append(f"type:{key}:expected={expected_type}:actual={type(report[key]).__name__}")
    if report.get("approval_status") not in FINAL_REPORT_ALLOWED_APPROVAL:
        errors.append(f"enum:approval_status:{report.get('approval_status')}")
    if report.get("risk_level") not in FINAL_REPORT_ALLOWED_RISK:
        errors.append(f"enum:risk_level:{report.get('risk_level')}")
    verifier = report.get("verifier_result") if isinstance(report.get("verifier_result"), dict) else {}
    if verifier.get("status") not in FINAL_REPORT_ALLOWED_VERIFIER:
        errors.append(f"enum:verifier_result.status:{verifier.get('status')}")
    score = report.get("confidence_score")
    if isinstance(score, (int, float)) and not 0.0 <= float(score) <= 1.0:
        errors.append(f"range:confidence_score:{score}")
    completeness = report.get("input_completeness") if isinstance(report.get("input_completeness"), dict) else {}
    if completeness and not completeness.get("accepted"):
        errors.append("input_completeness:not_accepted")
    return errors


def build_blocked_final_report(reasons: list[str] | None = None) -> dict[str, Any]:
    """Schema-valid REJECTED report for AgentShield-guard-blocked input.

    Shared by the engine short-circuit and the LangGraph guard-block node so both
    enforcement paths emit an identical, contract-valid rejection. Carries only
    the guard's non-PII reasons — never the raw input text.
    """

    reason_list = list(reasons or [])
    return {
        "review_type": "general_compliance_review",
        "review_request_id": "agentshield-input-guard-blocked",
        "input_completeness": {"accepted": True, "blocked_by": "agentshield_input_guard"},
        "status": "REJECTED",
        "approval_status": "REJECTED",
        "risk_level": "CRITICAL",
        "confidence": "VERIFIED",
        "confidence_score": 1.0,
        "language": "unknown",
        "channel": "unknown",
        "product_type": "unknown",
        "findings": [
            {
                "issue": "AgentShield 런타임 입력 가드가 요청을 차단했습니다.",
                "evidence": "",
                "rationale": "; ".join(reason_list) or "input_guard_blocked",
            }
        ],
        "evidence": [],
        "revision_suggestions": [],
        "board_diagnostics": {},
        "verifier_result": {"status": "FAILED", "reasons": reason_list},
        "audit_log_id": "",
        "blocked": True,
    }


def final_report_schema_summary() -> dict[str, Any]:
    return {
        "schema_version": "compliance-sentinel-final-report/v2",
        "required_fields": list(FINAL_REPORT_REQUIRED_FIELDS),
        "approval_status_enum": sorted(FINAL_REPORT_ALLOWED_APPROVAL),
        "risk_level_enum": sorted(FINAL_REPORT_ALLOWED_RISK),
        "verifier_status_enum": sorted(FINAL_REPORT_ALLOWED_VERIFIER),
    }
