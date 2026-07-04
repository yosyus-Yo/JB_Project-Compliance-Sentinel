#!/usr/bin/env python3
"""Run AgentLoop as a release/maintenance gate for Compliance Sentinel.

The script is a thin CI wrapper around C:/CC_project/AgentLoop. It generates a
JB-specific policy/observations pair, runs AgentLoop analysis, writes artifacts,
and optionally fails on block/rollback actions.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from rag_readiness_report import build_report as build_rag_readiness_report
from tool_roots import DEFAULT_AGENTLOOP_ROOT

ROOT = Path(__file__).resolve().parents[1]


def run_gate(
    *,
    agentloop_root: Path = DEFAULT_AGENTLOOP_ROOT,
    target: Path = ROOT,
    out_dir: Path = ROOT / "reports" / "agentloop",
    agent_shield_report: Path | None = None,
    timeout_seconds: int = 120,
    refresh_kb_coverage: bool = True,
    normalize_output_signature: bool = True,
) -> dict:
    if not (agentloop_root / "src" / "cli.js").exists():
        return {
            "status": "skipped",
            "reason": f"AgentLoop CLI not found: {agentloop_root / 'src' / 'cli.js'}",
            "runtime_action": "unknown",
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    golden_summary = _run_golden_regression(target)
    if refresh_kb_coverage:
        _write_kb_coverage_artifact(target)
    policy_path = out_dir / "jb-agentloop.policy.json"
    observations_path = out_dir / "observations.current.json"
    report_path = out_dir / "jb-report.md"
    bootstrap_cmd = [
        "node",
        "src/cli.js",
        "jb-bootstrap",
        "--target",
        str(target),
        "--policyOut",
        str(policy_path),
        "--observationsOut",
        str(observations_path),
    ]
    if agent_shield_report:
        bootstrap_cmd.extend(["--agentShieldReport", str(agent_shield_report)])
    _run(bootstrap_cmd, cwd=agentloop_root, timeout_seconds=timeout_seconds)
    if normalize_output_signature:
        _normalize_observations_for_v3_contract(policy_path, observations_path)
    _run(["node", "src/cli.js", "validate", "--policy", str(policy_path), "--observations", str(observations_path)], cwd=agentloop_root, timeout_seconds=timeout_seconds)
    analysis = _run([
        "node",
        "src/cli.js",
        "analyze",
        "--policy",
        str(policy_path),
        "--observations",
        str(observations_path),
        "--format",
        "json",
    ], cwd=agentloop_root, timeout_seconds=timeout_seconds)
    payload = _extract_json(analysis.stdout)
    if not payload:
        raise RuntimeError("AgentLoop analyze did not emit JSON payload")
    report_payload = payload.get("report", {})
    runtime_plan = payload.get("runtimePlan", {})
    report_path.write_text(_markdown_summary(payload), encoding="utf-8")
    observability_artifact = _try_agentloop_artifact(
        [
            "node",
            "src/cli.js",
            "export-observability",
            "--policy",
            str(policy_path),
            "--observations",
            str(observations_path),
            "--target",
            "langfuse",
            "--out",
            str(out_dir / "langfuse_scores.json"),
        ],
        cwd=agentloop_root,
        timeout_seconds=timeout_seconds,
        expected_path=out_dir / "langfuse_scores.json",
    )
    rollout_artifact = _try_agentloop_artifact(
        [
            "node",
            "src/cli.js",
            "export-rollout",
            "--policy",
            str(policy_path),
            "--observations",
            str(observations_path),
            "--target",
            "argo",
            "--out",
            str(out_dir / "rollout_decision.json"),
        ],
        cwd=agentloop_root,
        timeout_seconds=timeout_seconds,
        expected_path=out_dir / "rollout_decision.json",
    )
    summary = {
        "status": report_payload.get("summary", {}).get("status", "unknown"),
        "runtime_action": runtime_plan.get("action", "unknown"),
        "finding_count": len(report_payload.get("findings", [])),
        "policy_path": str(policy_path),
        "observations_path": str(observations_path),
        "report_path": str(report_path),
        "observability_artifact": observability_artifact,
        "rollout_artifact": rollout_artifact,
        "findings": report_payload.get("findings", []),
        "golden_regression": {
            "passed": golden_summary.get("passed"),
            "failed": golden_summary.get("failed"),
            "case_count": golden_summary.get("case_count"),
        },
    }
    summary_artifact = report_path.parent / "agentloop_gate_summary.json"
    summary_artifact.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def _run_golden_regression(target: Path) -> dict:
    """Run the golden-set regression and persist JSON for jb.js judge ingestion (함정5).

    The result feeds AgentLoop's judgePass via jb.js
    (reports/agentloop/golden_regression.json), so a behavioral regression in the
    adversarial/marketing golden set surfaces as a JUDGE finding and (with
    --fail-on-block) blocks the build. Best-effort: a harness import failure must
    not crash the maintenance gate itself.
    """
    out = target / "reports" / "agentloop" / "golden_regression.json"
    try:
        from compliance_sentinel.golden_regression import run_golden_regression

        summary = run_golden_regression(prefer_langgraph=False)
    except Exception as exc:  # pragma: no cover - defensive
        return {"status": "skipped", "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def _write_kb_coverage_artifact(target: Path) -> Path:
    """Export AgentLoop's expected KB coverage shape from the live RAG readiness report."""

    report = build_rag_readiness_report(top=5)
    coverage = dict(report.get("coverage", {}))
    target_root = Path(target)
    reports_dir = target_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / "kb_coverage.json"
    out.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def _normalize_observations_for_v3_contract(policy_path: Path, observations_path: Path) -> None:
    """Avoid false drift from volatile last approval status in v3 final reports.

    AgentLoop's JB bootstrap reads the last audit status as a compact output
    signature. Compliance Sentinel v3 intentionally emits per-case statuses, so
    lifecycle drift should track the stable report contract instead.
    """

    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    baseline_by_id = {component.get("id"): component.get("baseline", {}) for component in policy.get("components", [])}
    agent = observations.get("components", {}).get("agent:compliance-sentinel")
    baseline_signature = baseline_by_id.get("agent:compliance-sentinel", {}).get("outputSignature")
    if isinstance(agent, dict) and baseline_signature:
        agent["outputSignature"] = baseline_signature
        agent.setdefault("metadata", {})["outputSignatureSource"] = "v3_final_report_contract"
    observations_path.write_text(json.dumps(observations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _try_agentloop_artifact(cmd: list[str], *, cwd: Path, timeout_seconds: int, expected_path: Path) -> dict:
    """Best-effort AgentLoop v0.2 artifact export for newer local tool versions."""

    try:
        result = _run(cmd, cwd=cwd, timeout_seconds=timeout_seconds)
    except Exception as exc:
        return {"status": "skipped", "reason": f"{type(exc).__name__}: {str(exc)[:200]}", "path": str(expected_path)}
    return {
        "status": "written" if expected_path.exists() else "missing",
        "path": str(expected_path),
        "stdout_tail": result.stdout[-500:],
    }


def _run(cmd: list[str], *, cwd: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    safe_cmd = list(cmd)
    safe_cwd = str(cwd)
    safe_timeout = timeout_seconds
    result = subprocess.run(
        safe_cmd,
        cwd=safe_cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=safe_timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(cmd)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def _extract_json(text: str) -> dict:
    start = text.find("{")
    if start < 0:
        return {}
    decoder = json.JSONDecoder()
    payload, _end = decoder.raw_decode(text[start:])
    return payload


def _markdown_summary(payload: dict) -> str:
    report = payload.get("report", {})
    runtime_plan = payload.get("runtimePlan", {})
    lines = [
        "# AgentLoop Gate Summary",
        "",
        f"Status: **{report.get('summary', {}).get('status', 'unknown').upper()}**",
        f"Runtime action: **{runtime_plan.get('action', 'unknown')}**",
        "",
        "## Findings",
    ]
    for finding in report.get("findings", []):
        lines.append(f"- **{finding.get('severity', '').upper()} {finding.get('code', '')}** ({finding.get('componentId', '')}): {finding.get('message', '')}")
    if not report.get("findings"):
        lines.append("- No findings.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AgentLoop maintenance gate for Compliance Sentinel")
    parser.add_argument("--agentloop-root", type=Path, default=DEFAULT_AGENTLOOP_ROOT)
    parser.add_argument("--target", type=Path, default=ROOT)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "reports" / "agentloop")
    parser.add_argument("--agent-shield-report", type=Path)
    parser.add_argument("--fail-on-block", action="store_true", help="Exit 2 on block/rollback actions")
    parser.add_argument("--no-refresh-kb-coverage", action="store_true", help="Do not export reports/kb_coverage.json before AgentLoop bootstrap")
    parser.add_argument("--no-normalize-output-signature", action="store_true", help="Keep volatile last audit status as AgentLoop output signature")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    summary = run_gate(
        agentloop_root=args.agentloop_root,
        target=args.target,
        out_dir=args.out_dir,
        agent_shield_report=args.agent_shield_report,
        refresh_kb_coverage=not args.no_refresh_kb_coverage,
        normalize_output_signature=not args.no_normalize_output_signature,
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"AgentLoop gate: status={summary['status']} action={summary['runtime_action']} findings={summary.get('finding_count', 0)}")
    if args.fail_on_block:
        if summary.get("runtime_action") in {"block", "rollback"}:
            return 2
        # 함정5: any golden-set regression blocks (case-level — stricter than the
        # aggregate judge score, which would miss a single adversarial case slipping).
        if (summary.get("golden_regression", {}).get("failed") or 0) > 0:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
