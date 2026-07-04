#!/usr/bin/env python3
"""Benchmark cold vs warm/reused-agent engine paths.

The benchmark is intentionally dependency-free and deterministic by default. It
helps distinguish real module bottlenecks from cold-start initialization cost.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compliance_sentinel.engine import analyze_batch_with_engine, analyze_with_engine  # noqa: E402

DEFAULT_CASES = [
    "JB 슈퍼적금 배너: 누구나 연 8% 확정 수익, 원금 보장!",
    "앱푸시: 오늘만 대출 100% 승인! 신용점수 상관없이 즉시 승인",
    "Guaranteed 8% return with zero risk for everyone.",
    "본 약관은 고객 개인정보와 개인신용정보를 제휴사에 제공하며 동의한 것으로 봅니다.",
]


def _time_call(fn):
    started = time.perf_counter()
    value = fn()
    return value, time.perf_counter() - started


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _summarize(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0}
    return {
        "count": len(values),
        "avg_ms": round(statistics.mean(values) * 1000, 2),
        "p50_ms": round(_percentile(values, 0.50) * 1000, 2),
        "p95_ms": round(_percentile(values, 0.95) * 1000, 2),
        "p99_ms": round(_percentile(values, 0.99) * 1000, 2),
        "min_ms": round(min(values) * 1000, 2),
        "max_ms": round(max(values) * 1000, 2),
    }


def run(iterations: int, batch_size: int, *, p95_slo_ms: float = 5000.0) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "audit.jsonl"
        cold_times: list[float] = []
        cold_reports: list[dict] = []
        for idx in range(iterations):
            text = DEFAULT_CASES[idx % len(DEFAULT_CASES)]
            result, elapsed = _time_call(lambda text=text: analyze_with_engine(text, audit_path=audit_path, prefer_langgraph=False))
            cold_times.append(elapsed)
            cold_reports.append({
                "risk_level": result.state.final_report.get("risk_level"),
                "approval_status": result.state.final_report.get("approval_status"),
                "engine": result.engine,
            })

        batch_inputs = [DEFAULT_CASES[i % len(DEFAULT_CASES)] for i in range(batch_size)]
        batch_result, batch_elapsed = _time_call(
            lambda: analyze_batch_with_engine(batch_inputs, audit_path=audit_path, prefer_langgraph=False, reuse_agents=True)
        )
        no_reuse_result, no_reuse_elapsed = _time_call(
            lambda: analyze_batch_with_engine(batch_inputs, audit_path=audit_path, prefer_langgraph=False, reuse_agents=False)
        )

        audit_lines = audit_path.read_text(encoding="utf-8").splitlines() if audit_path.exists() else []
        cold_summary = _summarize(cold_times)
        return {
            "iterations": iterations,
            "batch_size": batch_size,
            "cold_single": cold_summary,
            "slo": {
                "p95_slo_ms": p95_slo_ms,
                "cold_p95_passed": cold_summary.get("p95_ms", 0.0) <= p95_slo_ms,
            },
            "batch_reused_agent": {
                "elapsed_ms": round(batch_elapsed * 1000, 2),
                "avg_per_item_ms": round((batch_elapsed / max(batch_result.item_count, 1)) * 1000, 2),
                "item_count": batch_result.item_count,
                "reused_agents": batch_result.reused_agents,
            },
            "batch_no_reuse": {
                "elapsed_ms": round(no_reuse_elapsed * 1000, 2),
                "avg_per_item_ms": round((no_reuse_elapsed / max(no_reuse_result.item_count, 1)) * 1000, 2),
                "item_count": no_reuse_result.item_count,
                "reused_agents": no_reuse_result.reused_agents,
            },
            "sample_reports": cold_reports[:4],
            "audit_lines": len(audit_lines),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Compliance Sentinel engine cold/warm paths")
    parser.add_argument("--iterations", type=int, default=4, help="Cold single-request iterations")
    parser.add_argument("--batch-size", type=int, default=12, help="Batch size for reusable-agent comparison")
    parser.add_argument("--p95-slo-ms", type=float, default=5000.0, help="Cold single-request p95 SLO for pass/fail metadata")
    parser.add_argument("--out", help="Write JSON report to path")
    parser.add_argument("--fail-on-slo", action="store_true", help="Exit 2 when benchmark SLO fails")
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args()
    result = run(iterations=max(1, args.iterations), batch_size=max(1, args.batch_size), p95_slo_ms=args.p95_slo_ms)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload + "\n", encoding="utf-8")
    if args.json:
        print(payload)
    else:
        print("Compliance Sentinel benchmark")
        print(payload)
    if args.fail_on_slo and not result.get("slo", {}).get("cold_p95_passed", True):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
