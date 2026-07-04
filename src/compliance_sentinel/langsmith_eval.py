"""Offline-first LangSmith evaluation helpers.

The project must never require LangSmith for local demos. This module provides a
small deterministic regression harness and, when ``LANGSMITH_API_KEY`` exists,
records a redacted summary run through ``telemetry.langsmith_record_run``.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from typing import Any, Iterable

from .engine import analyze_with_engine
from .telemetry import langsmith_record_run


DEFAULT_EVAL_CASES: list[dict[str, Any]] = [
    {
        "id": "ko-guaranteed-return",
        "input": "JB 슈퍼적금 출시! 누구나 연 8% 확정 수익, 원금 보장!",
        "expected_status_any": ["APPROVE_WITH_CHANGES", "REJECTED", "HUMAN_REVIEW_REQUIRED"],
        "expected_risk_any": ["MEDIUM", "HIGH", "CRITICAL"],
    },
    {
        "id": "loan-no-score",
        "input": "신용점수 무관, 100% 승인되는 간편대출을 지금 신청하세요.",
        "expected_status_any": ["REJECTED", "HUMAN_REVIEW_REQUIRED", "APPROVE_WITH_CHANGES"],
        "expected_risk_any": ["HIGH", "CRITICAL"],
    },
    {
        "id": "safe-low-risk",
        "input": "이벤트 안내: 자세한 조건은 영업점에서 확인하세요.",
        "expected_status_any": ["APPROVED", "PASSED", "HUMAN_REVIEW_REQUIRED"],
        "expected_risk_any": ["LOW", "MEDIUM"],
    },
]


@dataclass(frozen=True)
class EvalCaseResult:
    id: str
    passed: bool
    actual_status: str
    actual_risk: str
    audit_log_id: str
    reason: str


def run_regression_eval(cases: Iterable[dict[str, Any]] | None = None, *, prefer_langgraph: bool = False) -> dict[str, Any]:
    """Run deterministic compliance regression cases locally.

    Only redacted report summaries are returned/exported; raw input strings stay
    inside the local process and are not sent to LangSmith.
    """

    results: list[EvalCaseResult] = []
    for case in list(cases or DEFAULT_EVAL_CASES):
        engine_result = analyze_with_engine(case["input"], prefer_langgraph=prefer_langgraph)
        report = engine_result.state.final_report
        status = str(report.get("approval_status") or report.get("status") or "UNKNOWN")
        risk = str(report.get("risk_level") or "UNKNOWN")
        status_ok = status in set(case.get("expected_status_any", []))
        risk_ok = risk in set(case.get("expected_risk_any", []))
        passed = status_ok and risk_ok
        reason = "ok" if passed else f"status_ok={status_ok}, risk_ok={risk_ok}"
        results.append(EvalCaseResult(
            id=str(case["id"]),
            passed=passed,
            actual_status=status,
            actual_risk=risk,
            audit_log_id=str(report.get("audit_log_id") or ""),
            reason=reason,
        ))

    summary = {
        "case_count": len(results),
        "passed": sum(1 for item in results if item.passed),
        "failed": sum(1 for item in results if not item.passed),
        "results": [asdict(item) for item in results],
    }
    run_id = langsmith_record_run(
        "compliance_sentinel_regression_eval",
        inputs={"case_ids": [item.id for item in results], "raw_inputs_included": False},
        outputs=summary,
        metadata={"component": "langsmith_eval", "prefer_langgraph": prefer_langgraph},
    )
    if run_id:
        summary["langsmith_run_id"] = run_id
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Compliance Sentinel LangSmith-ready regression eval")
    parser.add_argument("--prefer-langgraph", action="store_true", help="Use LangGraph when USE_LANGGRAPH=1 and available")
    args = parser.parse_args(argv)
    summary = run_regression_eval(prefer_langgraph=args.prefer_langgraph)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
