#!/usr/bin/env python3
"""Generate a combined efficiency report for Compliance Sentinel.

Covers deterministic runtime performance, LLM budget ledger status, KB/RAG
readiness, memory governance, and optional AgentLoop release-gate status.
Designed for CI and local release-readiness checks.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for path in (SRC, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from benchmark_engine import run as run_benchmark  # noqa: E402
from compliance_sentinel.budget_guard import BudgetGuard, DEFAULT_LOG  # noqa: E402
from memory_governance_report import build_report as build_memory_governance_report  # noqa: E402
from rag_readiness_report import build_report as build_rag_report  # noqa: E402
from run_agentloop_gate import run_gate as run_agentloop_gate  # noqa: E402
from tool_roots import DEFAULT_AGENTLOOP_ROOT  # noqa: E402


def ledger_summary(path: Path = DEFAULT_LOG) -> dict:
    if not path.exists():
        return {"path": str(path), "record_count": 0, "total_cost_usd": 0.0, "by_role": {}, "by_model": {}}
    by_role: dict[str, float] = {}
    by_model: dict[str, float] = {}
    total = 0.0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        cost = float(row.get("cost_usd") or 0.0)
        total += cost
        count += 1
        role = str(row.get("role") or "unknown")
        model = str(row.get("model") or "unknown")
        by_role[role] = by_role.get(role, 0.0) + cost
        by_model[model] = by_model.get(model, 0.0) + cost
    return {
        "path": str(path),
        "record_count": count,
        "total_cost_usd": round(total, 6),
        "by_role": {key: round(value, 6) for key, value in sorted(by_role.items())},
        "by_model": {key: round(value, 6) for key, value in sorted(by_model.items())},
    }


def score_efficiency(*, benchmark: dict, rag: dict, budget: dict, agentloop: dict | None, memory: dict | None = None) -> dict:
    score = 10.0
    cold_avg = benchmark.get("cold_single", {}).get("avg_ms", 0.0)
    p95 = benchmark.get("cold_single", {}).get("p95_ms", cold_avg)
    if p95 > 5000:
        score -= 1.0
    if p95 > 10000:
        score -= 1.0
    reused = benchmark.get("batch_reused_agent", {}).get("avg_per_item_ms", 0.0)
    no_reuse = benchmark.get("batch_no_reuse", {}).get("avg_per_item_ms", 0.0)
    if no_reuse and reused and reused >= no_reuse:
        score -= 0.8
    if not rag.get("production_ready"):
        score -= 1.0
    if budget.get("status", {}).get("tier") in {"red", "blocked"}:
        score -= 1.0
    if agentloop and agentloop.get("runtime_action") in {"block", "rollback"}:
        score -= 1.0
    if memory and not memory.get("memory_governance_ready"):
        score -= 1.0
    score = max(0.0, min(10.0, score))
    return {
        "score": round(score, 1),
        "basis": {
            "cold_p95_ms": p95,
            "batch_reuse_avg_ms": reused,
            "batch_no_reuse_avg_ms": no_reuse,
            "rag_production_ready": rag.get("production_ready"),
            "memory_governance_ready": memory.get("memory_governance_ready") if memory else "skipped",
            "memory_blocker_count": memory.get("blocker_count") if memory else 0,
            "budget_tier": budget.get("status", {}).get("tier"),
            "agentloop_action": agentloop.get("runtime_action") if agentloop else "skipped",
        },
    }


def build_report(
    *,
    iterations: int,
    batch_size: int,
    include_agentloop: bool,
    agentloop_root: Path,
    agent_shield_report: Path | None,
) -> dict:
    benchmark = run_benchmark(iterations=iterations, batch_size=batch_size)
    rag = build_rag_report(top=5)
    memory = build_memory_governance_report(top=5)
    budget_guard = BudgetGuard()
    budget = {
        "status": budget_guard.status_with_tier(),
        "ledger": ledger_summary(),
    }
    agentloop = None
    if include_agentloop:
        try:
            agentloop = run_agentloop_gate(
                agentloop_root=agentloop_root,
                target=ROOT,
                out_dir=ROOT / "reports" / "agentloop",
                agent_shield_report=agent_shield_report,
            )
        except Exception as exc:  # CI should still receive performance/RAG data.
            agentloop = {"status": "error", "runtime_action": "unknown", "error": f"{type(exc).__name__}: {exc}"}
    efficiency = score_efficiency(benchmark=benchmark, rag=rag, budget=budget, agentloop=agentloop, memory=memory)
    return {
        "system": "JB_Project-Compliance-Sentinel",
        "report_type": "efficiency_readiness",
        "efficiency": efficiency,
        "performance": benchmark,
        "budget": budget,
        "rag_readiness": rag,
        "memory_governance": memory,
        "agentloop_gate": agentloop or {"status": "skipped", "runtime_action": "unknown"},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Compliance Sentinel efficiency report")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--include-agentloop", action="store_true")
    parser.add_argument("--agentloop-root", type=Path, default=DEFAULT_AGENTLOOP_ROOT)
    parser.add_argument("--agent-shield-report", type=Path)
    parser.add_argument("--out", default="reports/efficiency_report.json")
    parser.add_argument("--fail-under", type=float, help="Exit 2 if efficiency score is below threshold")
    args = parser.parse_args(argv)
    report = build_report(
        iterations=max(1, args.iterations),
        batch_size=max(1, args.batch_size),
        include_agentloop=args.include_agentloop,
        agentloop_root=args.agentloop_root,
        agent_shield_report=args.agent_shield_report,
    )
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.fail_under is not None and report["efficiency"]["score"] < args.fail_under:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
