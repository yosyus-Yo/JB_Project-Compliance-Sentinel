#!/usr/bin/env python3
"""Run the practical three-tool integration gates for Compliance Sentinel.

Order:
1. AgentShield security scan (first, strongest immediate gate)
2. AgentLoop lifecycle/release gate (uses AgentShield report + refreshed KB coverage)
3. AgentCompiler shadow benchmark (non-invasive optimization evidence)

Default mode is non-blocking because AgentShield/AgentLoop are governance tools
that may surface remediation work without replacing the deterministic MVP path.
Use --strict or individual --fail-on-* flags in CI once residual findings are
triaged.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_agentloop_gate import run_gate as run_agentloop_gate  # noqa: E402
from tool_roots import DEFAULT_AGENTCOMPILER_ROOT, DEFAULT_AGENTLOOP_ROOT, DEFAULT_AGENTSHIELD_ROOT  # noqa: E402


def run_agentshield(*, root: Path, target: Path, out_dir: Path, timeout_seconds: int) -> dict[str, Any]:
    cli = root / "src" / "agent_shield" / "cli.py"
    policy = root / "examples" / "agentshield-policy.yaml"
    if not cli.exists() or not policy.exists():
        return {"status": "skipped", "reason": f"AgentShield CLI/policy not found under {root}"}

    out_dir.mkdir(parents=True, exist_ok=True)
    effective_policy = _effective_agentshield_policy(policy, target=target, out_dir=out_dir)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    cmd = [
        sys.executable,
        "-m",
        "agent_shield.cli",
        "scan",
        "--target",
        str(target),
        "--policy",
        str(effective_policy),
        "--out",
        str(out_dir),
    ]
    safe_cmd = list(cmd)
    safe_cwd = root
    safe_timeout = timeout_seconds
    proc = subprocess.run(
        safe_cmd,
        cwd=safe_cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=safe_timeout,
        check=False,
    )
    report_path = out_dir / "agent_shield_report.json"
    if not report_path.exists():
        return {
            "status": "error",
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    report = json.loads(report_path.read_text(encoding="utf-8"))
    findings = report.get("findings", [])
    severity_counts = Counter(str(item.get("severity", "UNKNOWN")) for item in findings)
    category_counts = Counter(str(item.get("category", "UNKNOWN")) for item in findings)
    return {
        "status": report.get("status", "unknown"),
        "returncode": proc.returncode,
        "risk_score": report.get("risk_score"),
        "finding_count": len(findings),
        "severity_counts": dict(sorted(severity_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "report_path": str(report_path),
        "markdown_report_path": str(out_dir / "agent_shield_report.md"),
    }


def _effective_agentshield_policy(policy: Path, *, target: Path, out_dir: Path) -> Path:
    """Create a scan policy that excludes generated governance report artifacts."""

    extras = ["reports/three_tool_integration/**", "reports/governance/**", "reports/agentloop/**"]
    try:
        rel_out = out_dir.resolve().relative_to(target.resolve()).as_posix()
        extras.append(f"{rel_out}/**")
    except ValueError:
        pass
    text = policy.read_text(encoding="utf-8")
    effective = out_dir / "agentshield-policy.effective.yaml"
    effective.write_text(_add_exclude_paths(text, extras), encoding="utf-8")
    return effective


def _add_exclude_paths(text: str, extras: list[str]) -> str:
    lines = text.splitlines()
    existing = {line.strip()[2:].strip() for line in lines if line.strip().startswith("- ")}
    to_add = [item for item in extras if item not in existing]
    if not to_add:
        return text.rstrip() + "\n"
    out: list[str] = []
    inserted = False
    in_excludes = False
    for index, line in enumerate(lines):
        if line.startswith("exclude_paths:"):
            in_excludes = True
            out.append(line)
            continue
        if in_excludes and line and not line.startswith(" "):
            out.extend(f"  - {item}" for item in to_add)
            inserted = True
            in_excludes = False
        out.append(line)
    if in_excludes and not inserted:
        out.extend(f"  - {item}" for item in to_add)
        inserted = True
    if not inserted:
        out.append("exclude_paths:")
        out.extend(f"  - {item}" for item in to_add)
    return "\n".join(out).rstrip() + "\n"


def run_agentloop(*, root: Path, target: Path, out_dir: Path, agent_shield_report: Path | None, timeout_seconds: int) -> dict[str, Any]:
    return run_agentloop_gate(
        agentloop_root=root,
        target=target,
        out_dir=out_dir,
        agent_shield_report=agent_shield_report if agent_shield_report and agent_shield_report.exists() else None,
        timeout_seconds=timeout_seconds,
        refresh_kb_coverage=True,
        normalize_output_signature=True,
    )


def run_agentcompiler(*, root: Path, target: Path, out_dir: Path, timeout_seconds: int, skip_source: bool) -> dict[str, Any]:
    bench = root / "benchmarks" / "compliance_sentinel_shadow.py"
    if not bench.exists():
        return {"status": "skipped", "reason": f"AgentCompiler benchmark not found: {bench}"}

    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "agentcompiler_shadow.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [
        str(_python_for_tool(root)),
        str(bench),
        "--sentinel-root",
        str(target),
        "--json",
        "--output",
        str(output),
    ]
    if skip_source:
        cmd.append("--skip-source")
    safe_cmd = list(cmd)
    safe_cwd = root
    safe_timeout = timeout_seconds
    proc = subprocess.run(
        safe_cmd,
        cwd=safe_cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=safe_timeout,
        check=False,
    )
    if not output.exists():
        return {
            "status": "error",
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    payload = json.loads(output.read_text(encoding="utf-8"))
    graph = payload.get("graph", {})
    comparison = payload.get("comparison", {})
    source = payload.get("source_of_truth") or {}
    evidence_artifacts = run_agentcompiler_evidence_artifacts(root=root, out_dir=out_dir, timeout_seconds=timeout_seconds)
    return {
        "status": "pass" if graph.get("safety", {}).get("passed") and source.get("returncode", 0) == 0 else "needs_work",
        "returncode": proc.returncode,
        "safety_passed": graph.get("safety", {}).get("passed"),
        "nodes": graph.get("nodes"),
        "edges": graph.get("edges"),
        "speedup_vs_vllm_sim": comparison.get("speedup_vs_vllm_sim"),
        "speedup_vs_sglang_sim": comparison.get("speedup_vs_sglang_sim"),
        "source_returncode": source.get("returncode", "skipped"),
        "report_path": str(output),
        "warning": payload.get("warning"),
        **evidence_artifacts,
    }


def run_agentcompiler_evidence_artifacts(*, root: Path, out_dir: Path, timeout_seconds: int) -> dict[str, Any]:
    """Generate non-executing MCP trace + backend evidence artifacts when supported."""

    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / "mcp_trace.json"
    trace_path.write_text(json.dumps(_default_mcp_trace(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence_path = out_dir / "agentcompiler_evidence_gate.json"
    python = _python_for_tool(root)
    code = """
import json
import sys
from pathlib import Path
from agentcompiler.backends import SGLangAdapter, backend_evidence_gate
from agentcompiler.frontend import from_mcp_trace_with_report
trace_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
result = from_mcp_trace_with_report(trace_path)
plan = SGLangAdapter().compile(result.graph)
gate = backend_evidence_gate(plan, require_real_gpu=True, require_kv_claims=True)
payload = {
    "status": "generated",
    "graph_id": result.graph.graph_id,
    "nodes": len(result.graph.nodes),
    "edges": len(result.graph.edges),
    "skipped_events": [event.__dict__ for event in result.skipped_events],
    "plan_metadata": plan.metadata,
    "evidence_gate": gate,
}
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
""".strip()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    safe_cmd = [str(python), "-c", code, str(trace_path), str(evidence_path)]
    safe_cwd = root
    safe_timeout = timeout_seconds
    proc = subprocess.run(
        safe_cmd,
        cwd=safe_cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=safe_timeout,
        check=False,
    )
    if proc.returncode != 0 or not evidence_path.exists():
        return {
            "mcp_trace_path": str(trace_path),
            "evidence_artifact": {
                "status": "skipped",
                "path": str(evidence_path),
                "returncode": proc.returncode,
                "stderr_tail": proc.stderr[-1000:],
            },
        }
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    return {
        "mcp_trace_path": str(trace_path),
        "evidence_artifact": {"status": "written", "path": str(evidence_path)},
        "evidence_gate": payload.get("evidence_gate", {}),
        "mcp_trace_graph": {"nodes": payload.get("nodes"), "edges": payload.get("edges")},
    }


def _python_for_tool(root: Path) -> Path:
    for candidate in (root / ".venv" / "bin" / "python", root / ".venv" / "Scripts" / "python.exe"):
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def _default_mcp_trace() -> dict[str, Any]:
    return {
        "trace_id": "compliance-sentinel-mcp-shadow",
        "events": [
            {"method": "tools/call", "params": {"name": "compliance_review", "arguments": {"content": "redacted marketing draft"}, "idempotent": False}},
            {"method": "tools/call", "params": {"name": "kb_search", "arguments": {"query": "금융광고 원금 보장"}, "idempotent": True}},
            {"method": "tools/call", "params": {"name": "audit_log", "arguments": {"audit_log_id": "AUD-SHADOW"}, "idempotent": True}},
        ],
    }


def build_markdown(summary: dict[str, Any]) -> str:
    shield = summary.get("agentshield", {})
    loop = summary.get("agentloop", {})
    compiler = summary.get("agentcompiler", {})
    evidence_gate = compiler.get("evidence_gate", {}) if isinstance(compiler, dict) else {}
    return "\n".join(
        [
            "# Compliance Sentinel 3-Tool Integration Gate Report",
            "",
            "## Order",
            "1. AgentShield — security and memory-poisoning gate",
            "2. AgentLoop — lifecycle/release gate using AgentShield + KB coverage",
            "3. AgentCompiler — shadow benchmark only; no production decision replacement",
            "",
            "## Summary",
            f"- AgentShield: `{shield.get('status', 'unknown')}` findings={shield.get('finding_count', 'n/a')} severity={shield.get('severity_counts', {})}",
            f"- AgentLoop: `{loop.get('status', 'unknown')}` action={loop.get('runtime_action', 'unknown')} findings={loop.get('finding_count', 'n/a')}",
            f"- AgentCompiler: `{compiler.get('status', 'unknown')}` safety={compiler.get('safety_passed', 'n/a')} nodes={compiler.get('nodes', 'n/a')} edges={compiler.get('edges', 'n/a')}",
            f"- AgentCompiler evidence gate: passed={evidence_gate.get('passed', 'n/a')} reasons={evidence_gate.get('reasons', [])}",
            "",
            "## Notes",
            "- AgentShield/AgentLoop may intentionally report remediation work; default CLI mode is non-blocking.",
            "- AgentCompiler result is simulated/shadow evidence, not a runtime replacement claim.",
            "- `evidence_gate.passed=false` is expected until real GPU backend evidence exists.",
            "",
        ]
    )


def write_governance_dashboard(summary: dict[str, Any], governance_dir: Path) -> dict[str, str]:
    """Write a compact governance dashboard under reports/governance."""

    governance_dir.mkdir(parents=True, exist_ok=True)
    shield = summary.get("agentshield", {})
    loop = summary.get("agentloop", {})
    compiler = summary.get("agentcompiler", {})
    evidence_gate = compiler.get("evidence_gate", {}) if isinstance(compiler, dict) else {}
    dashboard = {
        "system": "Compliance Sentinel",
        "status": _governance_status(summary),
        "generated_from": summary.get("out_dir"),
        "security": {
            "status": shield.get("status", "unknown"),
            "finding_count": shield.get("finding_count", 0),
            "severity_counts": shield.get("severity_counts", {}),
        },
        "lifecycle": {
            "status": loop.get("status", "unknown"),
            "runtime_action": loop.get("runtime_action", "unknown"),
            "observability_artifact": loop.get("observability_artifact", {}),
            "rollout_artifact": loop.get("rollout_artifact", {}),
        },
        "shadow_optimization": {
            "status": compiler.get("status", "unknown"),
            "safety_passed": compiler.get("safety_passed"),
            "evidence_gate_passed": evidence_gate.get("passed"),
            "evidence_gate_reasons": evidence_gate.get("reasons", []),
            "mcp_trace_graph": compiler.get("mcp_trace_graph", {}),
        },
    }
    json_path = governance_dir / "three_tool_governance.json"
    md_path = governance_dir / "three_tool_governance.md"
    json_path.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_governance_markdown(dashboard), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _governance_status(summary: dict[str, Any]) -> str:
    shield_status = str(summary.get("agentshield", {}).get("status", "")).upper()
    loop_action = summary.get("agentloop", {}).get("runtime_action")
    compiler_status = summary.get("agentcompiler", {}).get("status")
    if shield_status == "FAIL" or loop_action in {"block", "rollback"} or compiler_status == "needs_work":
        return "needs_work"
    return "ready"


def _governance_markdown(dashboard: dict[str, Any]) -> str:
    return "\n".join([
        "# Compliance Sentinel Governance Dashboard",
        "",
        f"Status: **{dashboard.get('status', 'unknown')}**",
        "",
        "## Security",
        f"- AgentShield: `{dashboard['security']['status']}` findings={dashboard['security']['finding_count']}",
        "",
        "## Lifecycle",
        f"- AgentLoop: `{dashboard['lifecycle']['status']}` action={dashboard['lifecycle']['runtime_action']}",
        "",
        "## Shadow Optimization",
        f"- AgentCompiler: `{dashboard['shadow_optimization']['status']}` safety={dashboard['shadow_optimization']['safety_passed']}",
        f"- Evidence gate passed: `{dashboard['shadow_optimization']['evidence_gate_passed']}`",
        f"- Evidence gate reasons: `{dashboard['shadow_optimization']['evidence_gate_reasons']}`",
        "",
        "> AgentCompiler remains shadow-only until real backend evidence exists.",
        "",
    ])


def should_fail(summary: dict[str, Any], args: argparse.Namespace) -> bool:
    shield_status = str(summary.get("agentshield", {}).get("status", "")).upper()
    loop_action = summary.get("agentloop", {}).get("runtime_action")
    compiler_status = summary.get("agentcompiler", {}).get("status")
    fail_shield = args.fail_on_agentshield and shield_status == "FAIL"
    fail_loop = args.fail_on_agentloop and loop_action in {"block", "rollback"}
    fail_compiler = args.fail_on_agentcompiler and compiler_status not in {"pass", "skipped"}
    return fail_shield or fail_loop or fail_compiler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run AgentShield → AgentLoop → AgentCompiler integration gates")
    parser.add_argument("--target", type=Path, default=ROOT)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "reports" / "three_tool_integration")
    parser.add_argument("--governance-dir", type=Path, default=ROOT / "reports" / "governance")
    parser.add_argument("--agentshield-root", type=Path, default=DEFAULT_AGENTSHIELD_ROOT)
    parser.add_argument("--agentloop-root", type=Path, default=DEFAULT_AGENTLOOP_ROOT)
    parser.add_argument("--agentcompiler-root", type=Path, default=DEFAULT_AGENTCOMPILER_ROOT)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--skip-source", action="store_true", help="Skip source-of-truth Sentinel CLI run in AgentCompiler shadow benchmark")
    parser.add_argument("--skip-agentshield", action="store_true")
    parser.add_argument("--skip-agentloop", action="store_true")
    parser.add_argument("--skip-agentcompiler", action="store_true")
    parser.add_argument("--fail-on-agentshield", action="store_true")
    parser.add_argument("--fail-on-agentloop", action="store_true")
    parser.add_argument("--fail-on-agentcompiler", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Fail on any failing AgentShield, blocking AgentLoop, or failed AgentCompiler status")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.strict:
        args.fail_on_agentshield = True
        args.fail_on_agentloop = True
        args.fail_on_agentcompiler = True

    out_dir: Path = args.out_dir
    if out_dir.resolve() == args.target.resolve():
        raise ValueError("--out-dir must not be the target repository root")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"target": str(args.target), "out_dir": str(out_dir)}

    shield_report: Path | None = None
    if args.skip_agentshield:
        summary["agentshield"] = {"status": "skipped"}
    else:
        summary["agentshield"] = run_agentshield(root=args.agentshield_root, target=args.target, out_dir=out_dir / "agentshield", timeout_seconds=args.timeout)
        report_path = summary["agentshield"].get("report_path")
        shield_report = Path(report_path) if report_path else None

    if args.skip_agentloop:
        summary["agentloop"] = {"status": "skipped", "runtime_action": "unknown"}
    else:
        summary["agentloop"] = run_agentloop(root=args.agentloop_root, target=args.target, out_dir=out_dir / "agentloop", agent_shield_report=shield_report, timeout_seconds=args.timeout)

    if args.skip_agentcompiler:
        summary["agentcompiler"] = {"status": "skipped"}
    else:
        summary["agentcompiler"] = run_agentcompiler(root=args.agentcompiler_root, target=args.target, out_dir=out_dir / "agentcompiler", timeout_seconds=args.timeout, skip_source=args.skip_source)

    summary_path = out_dir / "summary.json"
    markdown_path = out_dir / "summary.md"
    summary["summary_path"] = str(summary_path)
    summary["markdown_path"] = str(markdown_path)
    summary["governance"] = write_governance_dashboard(summary, args.governance_dir)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(build_markdown(summary), encoding="utf-8")

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"AgentShield={summary['agentshield'].get('status')} findings={summary['agentshield'].get('finding_count', 'n/a')}")
        print(f"AgentLoop={summary['agentloop'].get('status')} action={summary['agentloop'].get('runtime_action')}")
        print(f"AgentCompiler={summary['agentcompiler'].get('status')} safety={summary['agentcompiler'].get('safety_passed', 'n/a')}")
        print(f"Report={markdown_path}")

    return 2 if should_fail(summary, args) else 0


if __name__ == "__main__":
    raise SystemExit(main())
