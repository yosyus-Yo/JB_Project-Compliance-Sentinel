#!/usr/bin/env python3
"""Memory governance/readiness report for Compliance Sentinel.

This read-only gate checks Koala-style agent memory stores for operational
safety: active Brain patterns, pending episodic memory, project skills, and
RAG corpus metadata. It intentionally does not merge, delete, or rewrite memory.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compliance_sentinel import cs_brain  # noqa: E402

DEFAULT_SKILL_DIR = ROOT / "agents" / "skills"
DEFAULT_RAG_PATH = ROOT / "data" / "knowledge_rag" / "financial_marketing_corpus.jsonl"

SECRET_RE = re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[^\s]{8,}|sk-[A-Za-z0-9_-]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
PROMPT_INJECTION_RE = re.compile(
    r"(?i)(ignore\s+(all\s+)?previous\s+instructions|disregard\s+(all\s+)?instructions|reveal\s+system\s+prompt|developer\s+message|you\s+are\s+now|switch\s+to\s+developer\s+mode|act\s+as\s+DAN|<\|im_start\|>|\[INST\])"
)
PII_RE = re.compile(
    r"(\b\d{6}-\d{7}\b|\b01[016789]-\d{3,4}-\d{4}\b|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b|\b\d{2,6}-\d{2,6}-\d{2,6}\b)"
)
GOVERNANCE_TAGS = {
    "approved",
    "needs-approval",
    "runtime-memory",
    "document-ingest",
    "external-training",
    "peer-training",
    "experience",
    "readonly",
}


def _load_patterns(path: Path, key: str) -> list[dict[str, Any]]:
    data = cs_brain._load_yaml(path) or {}  # project-local helper; used read-only here.
    patterns = data.get(key) or []
    return [row for row in patterns if isinstance(row, dict)]


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _issue(kind: str, severity: str, store: str, pattern: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "store": store,
        "pattern_id": pattern.get("id", "<missing>"),
        "context": str(pattern.get("context", ""))[:120],
        "message": message,
    }


def _scan_pattern(store: str, pattern: dict[str, Any], *, now: datetime, stale_days: int) -> tuple[list[dict], list[dict]]:
    blockers: list[dict] = []
    warnings: list[dict] = []
    text = "\n".join(str(pattern.get(field, "")) for field in ("context", "content", "hypothesis"))
    missing = [field for field in ("id", "context", "status", "content", "learned_at") if not pattern.get(field)]
    if missing:
        blockers.append(_issue("schema_missing_required_fields", "critical", store, pattern, f"missing={','.join(missing)}"))
    if SECRET_RE.search(text):
        blockers.append(_issue("secret_like_memory_content", "critical", store, pattern, "secret-like token detected in memory text"))
    if PROMPT_INJECTION_RE.search(text):
        blockers.append(_issue("prompt_injection_memory_content", "critical", store, pattern, "prompt-injection phrase detected in memory text"))
    if PII_RE.search(text):
        blockers.append(_issue("raw_pii_memory_content", "critical", store, pattern, "raw PII-like value detected in memory text"))
    learned_at = _parse_dt(pattern.get("learned_at"))
    if learned_at is None:
        warnings.append(_issue("learned_at_unparseable", "warning", store, pattern, "learned_at is missing or not ISO-like"))
    elif (now - learned_at).days > stale_days:
        warnings.append(_issue("stale_memory_review_required", "warning", store, pattern, f"age_days={(now - learned_at).days}"))
    tags = {str(tag) for tag in (pattern.get("tags") or [])}
    has_governance_marker = bool(tags & GOVERNANCE_TAGS) or pattern.get("readonly") is True
    if not has_governance_marker:
        warnings.append(_issue("missing_approval_or_source_marker", "warning", store, pattern, "no approval/source governance marker found"))
    if store == "project_brain" and pattern.get("readonly") is not True:
        blockers.append(_issue("mutable_project_memory", "critical", store, pattern, "project Brain active pattern is not readonly"))
    if store == "pending" and "runtime-memory" in tags and any(str(tag).lower() == "low" for tag in tags):
        warnings.append(_issue("low_signal_runtime_memory_pending", "warning", store, pattern, "LOW runtime memory should be reviewed before merge"))
    return blockers, warnings


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            count += 1
    return count


def _recommendations(blockers: list[dict], warnings: list[dict], *, pending_count: int) -> list[str]:
    kinds = {item["kind"] for item in blockers + warnings}
    out: list[str] = []
    if {"secret_like_memory_content", "raw_pii_memory_content", "prompt_injection_memory_content"} & kinds:
        out.append("Redact or remove unsafe memory text, then rerun the gate before merge/deploy.")
    if "mutable_project_memory" in kinds:
        out.append("Keep project Brain production patterns readonly; stage new lessons in pending memory first.")
    if pending_count:
        out.append("Review pending memory candidates, approve/reject them, and merge only evidence-backed patterns.")
    if "stale_memory_review_required" in kinds:
        out.append("Refresh or retire stale memory patterns whose source evidence may no longer be valid.")
    if "missing_approval_or_source_marker" in kinds:
        out.append("Add approval/source tags or evidence metadata to memory patterns used in compliance decisions.")
    if not out:
        out.append("No critical memory governance blockers found; continue routine pending review and freshness checks.")
    return out


def build_report(
    *,
    brain_path: Path = cs_brain.PROJECT_BRAIN,
    pending_path: Path = cs_brain.PENDING_PATTERNS,
    skill_dir: Path = DEFAULT_SKILL_DIR,
    rag_path: Path = DEFAULT_RAG_PATH,
    stale_days: int = 365,
    top: int = 10,
    strict_pending: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = now or datetime.now(timezone.utc)
    project_patterns = _load_patterns(brain_path, "learned_patterns") if brain_path.exists() else []
    pending_patterns = _load_patterns(pending_path, "pending_patterns") if pending_path.exists() else []
    blockers: list[dict] = []
    warnings: list[dict] = []
    for store, patterns in (("project_brain", project_patterns), ("pending", pending_patterns)):
        for pattern in patterns:
            pattern_blockers, pattern_warnings = _scan_pattern(store, pattern, now=checked_at, stale_days=stale_days)
            blockers.extend(pattern_blockers)
            warnings.extend(pattern_warnings)
    pending_needs_approval = sum(1 for p in pending_patterns if "needs-approval" in {str(tag) for tag in (p.get("tags") or [])})
    if strict_pending and pending_patterns:
        blockers.append({
            "kind": "pending_memory_queue_not_empty",
            "severity": "critical",
            "store": "pending",
            "pattern_id": "*",
            "context": "pending_patterns.yaml",
            "message": f"pending_count={len(pending_patterns)}",
        })
    elif pending_patterns:
        warnings.append({
            "kind": "pending_memory_queue_not_empty",
            "severity": "warning",
            "store": "pending",
            "pattern_id": "*",
            "context": "pending_patterns.yaml",
            "message": f"pending_count={len(pending_patterns)}",
        })
    skill_files = sorted(skill_dir.rglob("*.md")) if skill_dir.exists() else []
    counts = {
        "project_patterns": len(project_patterns),
        "project_readonly_patterns": sum(1 for p in project_patterns if p.get("readonly") is True),
        "project_mutable_patterns": sum(1 for p in project_patterns if p.get("readonly") is not True),
        "pending_patterns": len(pending_patterns),
        "pending_needs_approval": pending_needs_approval,
        "skill_files": len(skill_files),
        "document_rag_chunks": _count_jsonl(rag_path),
    }
    ready = not blockers
    return {
        "system": "JB_Project-Compliance-Sentinel",
        "report_type": "memory_governance",
        "checked_at": checked_at.isoformat(),
        "status": "ready" if ready else "needs_work",
        "memory_governance_ready": ready,
        "strict_pending": strict_pending,
        "counts": counts,
        "koala_alignment": {
            "working_memory": "ComplianceState.short_term_memory / request trace",
            "semantic_memory": "LawKnowledgeBase + document RAG corpus",
            "procedural_memory": "agents/skills role-based skill injection",
            "episodic_memory": ".cs-brain project/pending patterns",
        },
        "blockers": blockers[:top],
        "warnings": warnings[:top],
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "recommended_next_steps": _recommendations(blockers, warnings, pending_count=len(pending_patterns)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit Compliance Sentinel memory governance readiness report")
    parser.add_argument("--brain-path", type=Path, default=cs_brain.PROJECT_BRAIN)
    parser.add_argument("--pending-path", type=Path, default=cs_brain.PENDING_PATTERNS)
    parser.add_argument("--skill-dir", type=Path, default=DEFAULT_SKILL_DIR)
    parser.add_argument("--rag-path", type=Path, default=DEFAULT_RAG_PATH)
    parser.add_argument("--stale-days", type=int, default=365)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--strict-pending", action="store_true", help="Treat any pending memory queue as a blocker")
    parser.add_argument("--out", help="Write JSON report to path")
    parser.add_argument("--fail-on-blockers", action="store_true", help="Exit 2 when critical blockers are present")
    args = parser.parse_args(argv)
    report = build_report(
        brain_path=args.brain_path,
        pending_path=args.pending_path,
        skill_dir=args.skill_dir,
        rag_path=args.rag_path,
        stale_days=max(1, args.stale_days),
        top=max(1, args.top),
        strict_pending=args.strict_pending,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if args.fail_on_blockers and not report["memory_governance_ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
