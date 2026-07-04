"""External learning lab bridge for Compliance Sentinel.

This module implements the recommended strict workflow:

JB runtime artifacts -> sanitized export -> external learning/training lab ->
candidate JSONL -> validated import -> optional approved staging.

It does not run model training in production. Agent-training frameworks such as
Agent Lightning can consume the exported `agent_training_tasks.jsonl` outside this
system and return candidate improvements for review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from . import cs_brain
from .knowledge_ingest import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_RAG_PATH,
    IngestChunk,
    ingest_document,
    _contains_prompt_injection,
    _contains_secret,
    _upsert_skill_items,
    _write_rag_items,
)
from .pii import redact_pii
from .skill_injection import DEFAULT_MARKETING_SKILL_PATH

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "training" / "exports" / "latest"
DEFAULT_CANDIDATE_DIR = PROJECT_ROOT / "data" / "learning_candidates"
DEFAULT_CANDIDATE_PATH = DEFAULT_CANDIDATE_DIR / "imported_candidates.jsonl"
DEFAULT_TRAINING_PROGRAM = PROJECT_ROOT / "training" / "program.md"
DEFAULT_PEER_LAB_ROOT = PROJECT_ROOT / "training" / "peer-labs"

CandidateTarget = Literal["skill", "rag", "memory"]


@dataclass(frozen=True)
class ExportReport:
    out_dir: str
    brain_patterns: int
    pending_patterns: int
    skill_notes: int
    rag_chunks: int
    eval_cases: int
    agent_training_tasks: int
    files: list[str]


@dataclass(frozen=True)
class CandidateImportReport:
    imported: int
    rejected: int
    staged: int
    candidate_path: str
    rejection_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TrainingIntegrationReport:
    mode: str
    source_path: str
    staged: int
    imported: int = 0
    rejected: int = 0
    written_skill_items: int = 0
    written_rag_items: int = 0
    written_memory_items: int = 0
    merged_count: int = 0
    skipped_readonly_count: int = 0
    new_pattern_ids: list[str] = field(default_factory=list)
    candidate_path: str = ""
    skill_path: str = ""
    rag_path: str = ""
    pending_path: str = ""
    brain_path: str = ""
    rejection_reasons: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PeerTrainingLabReport:
    lab_dir: str
    run_id: str
    topic: str
    roles: list[str]
    files: list[str]
    safety_notes: list[str]
    next_steps: list[str]


@dataclass(frozen=True)
class PeerTrainingLabIntegrationReport:
    lab_dir: str
    integrated_artifacts: list[str]
    staged: int
    imported: int
    rejected: int
    merged_count: int
    skipped_readonly_count: int
    new_pattern_ids: list[str]
    reports: list[dict]
    safety_notes: list[str]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    slug = "-".join(part for part in slug.split("-") if part)
    return slug[:80] or "peer-training"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _read_candidate_rows(path: Path) -> list[dict]:
    """Read teacher/student output candidates from JSONL or JSON.

    JSON may be either a list of rows or an object containing `candidates`,
    `results`, or `rows`. Markdown/text artifacts intentionally go through the
    document-ingest path instead of this structured candidate reader.
    """

    if path.suffix.lower() == ".jsonl":
        return _read_jsonl(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ["candidates", "results", "rows"]:
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    raise ValueError("candidate JSON must be a list or contain candidates/results/rows")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append_jsonl(path: Path, rows: list[dict]) -> int:
    existing_ids = {row.get("id") for row in _read_jsonl(path)}
    new_rows = [row for row in rows if row.get("id") not in existing_ids]
    if not new_rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in new_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(new_rows)


def _redact_text(value: str) -> tuple[str, str]:
    redacted, _ = redact_pii(value or "")
    return redacted, _sha(value or "")


def _sanitize_pattern(pattern: dict, *, source_store: str) -> dict:
    clean = dict(pattern)
    for field in ["context", "content", "hypothesis"]:
        if field in clean and clean[field] is not None:
            redacted, raw_hash = _redact_text(str(clean[field]))
            clean[field] = redacted
            clean[f"{field}_raw_hash"] = raw_hash
    clean["source_store"] = source_store
    return clean


def _load_brain_patterns() -> tuple[list[dict], list[dict]]:
    brain = cs_brain._load_yaml(cs_brain.PROJECT_BRAIN) or {}
    pending = cs_brain._load_yaml(cs_brain.PENDING_PATTERNS) or {}
    learned = [_sanitize_pattern(p, source_store="project_brain") for p in brain.get("learned_patterns") or []]
    pending_rows = [_sanitize_pattern(p, source_store="pending_patterns") for p in pending.get("pending_patterns") or []]
    return learned, pending_rows


def _extract_skill_notes(skill_path: Path = DEFAULT_MARKETING_SKILL_PATH) -> list[dict]:
    if not skill_path.exists():
        return []
    notes: list[dict] = []
    for idx, line in enumerate(skill_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        redacted, raw_hash = _redact_text(stripped[2:].strip())
        notes.append({
            "id": f"SKILL-{idx:04d}-{_sha(redacted)[:8]}",
            "source": str(skill_path.relative_to(PROJECT_ROOT)),
            "line": idx,
            "text": redacted,
            "raw_hash": raw_hash,
        })
    return notes


def _load_rag_chunks(rag_path: Path = DEFAULT_RAG_PATH) -> list[dict]:
    rows = []
    for row in _read_jsonl(rag_path):
        redacted, raw_hash = _redact_text(str(row.get("text", "")))
        clean = dict(row)
        clean["text"] = redacted
        clean["raw_hash"] = raw_hash
        rows.append(clean)
    return rows


def _load_eval_cases() -> list[dict]:
    rows: list[dict] = []
    for path in [PROJECT_ROOT / "evals" / "marketing_content_cases.jsonl", PROJECT_ROOT / "evals" / "red_team_cases.jsonl"]:
        for row in _read_jsonl(path):
            text = str(row.get("content") or row.get("input") or "")
            redacted, raw_hash = _redact_text(text)
            clean = dict(row)
            if "content" in clean:
                clean["content"] = redacted
            if "input" in clean:
                clean["input"] = redacted
            clean["raw_input_hash"] = raw_hash
            clean["source_file"] = str(path.relative_to(PROJECT_ROOT))
            rows.append(clean)
    return rows


def _training_tasks_from_eval_cases(eval_cases: list[dict]) -> list[dict]:
    tasks: list[dict] = []
    for row in eval_cases:
        text = row.get("content") or row.get("input") or ""
        expected_flags = row.get("expected_flags") or []
        expected = row.get("expected") or row.get("expected_approval") or ""
        task_id = f"TRAIN-{row.get('id', _sha(str(row))[:8])}"
        tasks.append({
            "id": task_id,
            "task_type": "financial_marketing_or_compliance_review",
            "prompt": text,
            "expected": {
                "flags": expected_flags,
                "outcome": expected,
            },
            "reward_spec": {
                "detect_expected_flags": 0.35,
                "approval_or_review_routing_match": 0.25,
                "pii_not_leaked": 0.20,
                "verifier_or_disclaimer_present": 0.20,
            },
            "source_case_id": row.get("id"),
        })
    return tasks


def _write_program(out_dir: Path) -> Path:
    text = """# Compliance Sentinel External Learning Program

## Goal

Improve financial marketing/compliance review behavior outside the production
system. Produce **candidates only**; do not directly mutate production Brain,
Skill, RAG, prompts, or model routing.

## Inputs

- `brain_patterns.jsonl`: approved and pending memory patterns.
- `skill_notes.jsonl`: project skill guidance injected into internal agents.
- `rag_chunks.jsonl`: source-grounded document RAG chunks.
- `eval_cases.jsonl`: redacted holdout/evaluation cases.
- `agent_training_tasks.jsonl`: Agent Lightning/GRPO-style task rows with reward spec.

## Required External Loop

1. Deduplicate similar patterns and chunks.
2. Detect contradictions and stale rules.
3. Replay eval tasks and compute no-regression metrics.
4. Generate candidates in JSONL format:

```json
{"id":"CAND-001","target":"skill","text":"...","source":"external-lab","approved":false,"score":0.82,"evidence":["eval:ko-deposit-001"]}
```

Valid `target`: `skill`, `rag`, `memory`.

## Safety Gates

- `approved=false` by default.
- Production import only stores candidate rows unless `--stage-approved` is used.
- Even staged memory goes to `.cs-brain/pending_patterns.yaml`, not directly to project Brain.
- Never include raw PII, credentials, or unredacted customer text.
"""
    path = out_dir / "program.md"
    path.write_text(text, encoding="utf-8")
    return path


def export_learning_bundle(*, out_dir: Path = DEFAULT_EXPORT_DIR) -> ExportReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    brain, pending = _load_brain_patterns()
    skill_notes = _extract_skill_notes()
    rag_chunks = _load_rag_chunks()
    eval_cases = _load_eval_cases()
    training_tasks = _training_tasks_from_eval_cases(eval_cases)

    files: list[Path] = []
    for name, rows in [
        ("brain_patterns.jsonl", brain),
        ("pending_patterns.jsonl", pending),
        ("skill_notes.jsonl", skill_notes),
        ("rag_chunks.jsonl", rag_chunks),
        ("eval_cases.jsonl", eval_cases),
        ("agent_training_tasks.jsonl", training_tasks),
    ]:
        path = out_dir / name
        _write_jsonl(path, rows)
        files.append(path)
    files.append(_write_program(out_dir))
    manifest = {
        "schema_version": "cs-learning-export/v1",
        "created_at": _now(),
        "counts": {
            "brain_patterns": len(brain),
            "pending_patterns": len(pending),
            "skill_notes": len(skill_notes),
            "rag_chunks": len(rag_chunks),
            "eval_cases": len(eval_cases),
            "agent_training_tasks": len(training_tasks),
        },
        "safety": {
            "raw_pii_exported": False,
            "production_mutation_allowed": False,
            "candidate_import_requires_approval": True,
        },
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    files.append(manifest_path)
    return ExportReport(
        out_dir=str(out_dir),
        brain_patterns=len(brain),
        pending_patterns=len(pending),
        skill_notes=len(skill_notes),
        rag_chunks=len(rag_chunks),
        eval_cases=len(eval_cases),
        agent_training_tasks=len(training_tasks),
        files=[str(path) for path in files],
    )


def _normalize_candidate_row(row: dict) -> dict:
    """Normalize external teacher/student rows into candidate schema.

    Required canonical fields are `target` and `text`. External labs often use
    names such as `target_store`, `lesson`, or `recommendation`; these aliases
    keep the bridge ergonomic without allowing arbitrary production mutation.
    """

    clean = dict(row)
    if not clean.get("target"):
        clean["target"] = clean.get("target_store") or clean.get("store") or clean.get("destination")
    if not clean.get("text"):
        clean["text"] = clean.get("lesson") or clean.get("recommendation") or clean.get("knowledge") or clean.get("pattern")
    if isinstance(clean.get("target"), str):
        clean["target"] = clean["target"].strip().lower()
    return clean


def _validate_candidate(row: dict) -> tuple[bool, str]:
    if row.get("target") not in {"skill", "rag", "memory"}:
        return False, "invalid_target"
    text = str(row.get("text", "")).strip()
    if not text:
        return False, "missing_text"
    if _contains_secret(text):
        return False, "secret_like_token_detected"
    if _contains_prompt_injection(text):
        return False, "prompt_injection_pattern_detected"
    if row.get("score") is not None:
        try:
            score = float(row.get("score"))
            if score < 0 or score > 1:
                return False, "score_out_of_range"
        except (TypeError, ValueError):
            return False, "score_not_numeric"
    return True, "ok"


def _candidate_id(row: dict) -> str:
    if row.get("id"):
        return str(row["id"])
    return f"CAND-{_sha(str(row.get('target')) + str(row.get('text')))[:12]}"


def _stage_candidate(row: dict, *, skill_path: Path, rag_path: Path, pending_path: Path, brain_path: Path = cs_brain.PROJECT_BRAIN) -> int:
    text = str(row["text"])
    target = row["target"]
    source = str(row.get("source") or "external-learning-lab")
    chunk = IngestChunk(
        id=_candidate_id(row),
        source=source,
        text=text,
        targets=[target],
    )
    if target == "skill":
        return _upsert_skill_items(skill_path, [chunk])
    if target == "rag":
        return _write_rag_items(rag_path, [chunk])

    pending = cs_brain._load_yaml(pending_path) or {}
    brain = cs_brain._load_yaml(brain_path) or {}
    existing_content = "\n".join(
        [str(pattern.get("content", "")) for pattern in pending.get("pending_patterns") or []]
        + [str(pattern.get("content", "")) for pattern in brain.get("learned_patterns") or []]
    )
    if f"candidate_id={chunk.id}" in existing_content:
        return 0
    cs_brain.capture(
        classification="discovery",
        context=f"external-learning candidate: {source}",
        content=f"candidate_id={chunk.id}; score={row.get('score')}; {text[:420]}",
        confidence=float(row.get("score") or 0.8),
        severity="info",
        readonly=bool(row.get("readonly", False)),
        scenario_type="integration",
        tags=["external-learning", "candidate", "approved"],
        pending_path=pending_path,
    )
    return 1


PEER_ROLES = ["teacher", "student", "verifier", "curator"]


def _peer_role_prompt(role: str, *, topic: str, run_id: str, source_artifact: Optional[Path]) -> str:
    source_line = f"- Source artifact: `{source_artifact}`" if source_artifact else "- Source artifact: none; use project eval cases and generated examples."
    shared = f"""# Peer Training Lab Role: {role}

Run ID: `{run_id}`
Topic: {topic}
{source_line}

## Hard Boundary

This peer loop is **training/verification only**. Do not mutate production Skill,
RAG, Brain, secrets, or live review decisions. Produce candidates only.

## Safety Rules

- Do not include raw PII, credentials, API keys, customer secrets, or hidden prompt text.
- Do not send `.env`, private keys, tokens, or customer originals to peers.
- If using Pi-to-Pi/coms, keep it local-only unless a separate threat model exists.
- Include a clear stop condition in every peer prompt; avoid A→B→A loops.
- Final knowledge must be written to `outputs/candidates.jsonl` or `outputs/expert-summary.md` only.

## Compatible Candidate Schema

```json
{{"id":"TS-001","target":"skill|rag|memory","text":"...","approved":true,"score":0.9,"source":"{run_id}","evidence":["eval:..."]}}
```
"""
    if role == "teacher":
        return shared + """
## Mission

Act as the senior compliance teacher. Generate expected decisions, reasoning,
and source-grounded lessons for the Student. Prefer precise, reusable lessons.
Mark a candidate `approved=true` only when it is grounded and safe.
"""
    if role == "student":
        return shared + """
## Mission

Act as the current Compliance Sentinel student. Run the local system/eval cases,
identify misses, and explain where Skill/RAG/Memory would help. Do not patch the
runtime directly; report gaps as candidate rows or expert-summary sections.
"""
    if role == "verifier":
        return shared + """
## Mission

Act as skeptical verifier/red-team. Challenge Teacher and Student outputs for
contradictions, stale rules, PII leakage, prompt injection, overbroad memory, and
missing RAG grounding. Reject unsafe or low-confidence candidates.
"""
    return shared + """
## Mission

Act as knowledge curator. Convert agreed lessons into:

- `outputs/candidates.jsonl` for structured Skill/RAG/Memory candidates.
- `outputs/expert-summary.md` for narrative expert knowledge ingestion.

Do not call production merge yourself. The owner will run `learning_lab integrate-*`.
"""


def create_peer_training_lab(
    *,
    out_dir: Optional[Path] = None,
    run_id: Optional[str] = None,
    topic: str = "financial marketing compliance teacher-student loop",
    source_artifact: Optional[Path] = None,
) -> PeerTrainingLabReport:
    """Create a local-only Pi-to-Pi style training lab scaffold.

    The scaffold is intentionally file-based so it works with Pi peer sessions,
    ordinary terminals, or a sandbox without making peer communication a runtime
    dependency of the Compliance Sentinel decision path.
    """

    if not run_id:
        run_id = f"peer-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{_sha(topic)[:6]}"
    lab_dir = out_dir or (DEFAULT_PEER_LAB_ROOT / _safe_slug(run_id))
    prompts_dir = lab_dir / "prompts"
    outputs_dir = lab_dir / "outputs"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    for role in PEER_ROLES:
        path = prompts_dir / f"{role}.md"
        path.write_text(_peer_role_prompt(role, topic=topic, run_id=run_id, source_artifact=source_artifact), encoding="utf-8")
        files.append(path)

    candidates_template = outputs_dir / "candidates.jsonl"
    candidates_template.write_text(
        json.dumps({
            "id": f"{run_id}-EXAMPLE-SKILL",
            "target": "skill",
            "text": "교사-학생 합의가 끝난 안전한 절차 지식 후보를 여기에 기록한다.",
            "approved": False,
            "score": 0.0,
            "source": run_id,
            "evidence": [],
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    files.append(candidates_template)

    summary_template = outputs_dir / "expert-summary.md"
    summary_template.write_text(
        f"# Peer Training Expert Summary — {run_id}\n\n"
        "## 심의관 체크리스트\n\n- 합의된 절차 지식만 작성합니다.\n\n"
        "## 내부 기준 원문 / RAG 근거\n\n- 출처가 있는 기준만 작성합니다.\n\n"
        "## 반복 사례 / Memory 후보\n\n- 반복 검증된 패턴만 작성합니다.\n",
        encoding="utf-8",
    )
    files.append(summary_template)

    readme = lab_dir / "README.md"
    readme.write_text(
        f"# Local Peer Training Lab — {run_id}\n\n"
        "This lab is for sandbox/local peer training only. It does not change production runtime.\n\n"
        "## Suggested Pi-to-Pi usage\n\n"
        "Start 3-4 local peers named `teacher`, `student`, `verifier`, and `curator`, then send each peer its prompt file from `prompts/`.\n\n"
        "## Integration\n\n"
        "Archive/dry-run candidates only:\n\n"
        f"```bash\nPYTHONPATH=src python -m compliance_sentinel.learning_lab integrate-peer-lab {lab_dir} --json\n```\n\n"
        "Stage approved results, then optionally merge memory patterns:\n\n"
        f"```bash\nPYTHONPATH=src python -m compliance_sentinel.learning_lab integrate-peer-lab {lab_dir} --stage-approved --merge-patterns --min-score 0.75 --json\n```\n",
        encoding="utf-8",
    )
    files.append(readme)

    manifest = lab_dir / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "cs-peer-training-lab/v1",
        "created_at": _now(),
        "run_id": run_id,
        "topic": topic,
        "roles": PEER_ROLES,
        "source_artifact": str(source_artifact) if source_artifact else None,
        "mode": "local_only_training_lab",
        "production_decision_path": False,
        "allowed_outputs": ["outputs/candidates.jsonl", "outputs/expert-summary.md"],
        "safety": {
            "raw_pii_allowed": False,
            "secrets_allowed": False,
            "auto_brain_merge_allowed": False,
            "network_peer_default": False,
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    files.append(manifest)

    return PeerTrainingLabReport(
        lab_dir=str(lab_dir),
        run_id=run_id,
        topic=topic,
        roles=list(PEER_ROLES),
        files=[str(path) for path in files],
        safety_notes=[
            "training_only_not_production_decision_path",
            "local_only_peer_default",
            "outputs_integrated_through_learning_lab_only",
        ],
        next_steps=[
            "Run local teacher/student/verifier/curator peers with prompts/*.md",
            "Write outputs/candidates.jsonl and/or outputs/expert-summary.md",
            "Run learning_lab integrate-peer-lab with --stage-approved after review",
        ],
    )


def integrate_peer_training_lab(
    lab_dir: Path,
    *,
    stage_approved: bool = False,
    merge_patterns: bool = False,
    min_score: float = 0.75,
    candidate_out_path: Path = DEFAULT_CANDIDATE_PATH,
    skill_path: Path = DEFAULT_MARKETING_SKILL_PATH,
    rag_path: Path = DEFAULT_RAG_PATH,
    pending_path: Path = cs_brain.PENDING_PATTERNS,
    brain_path: Path = cs_brain.PROJECT_BRAIN,
    merge_log_path: Path = cs_brain.MERGE_LOG,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> PeerTrainingLabIntegrationReport:
    outputs = lab_dir / "outputs"
    candidates = [path for path in [outputs / "candidates.jsonl", outputs / "candidates.json"] if path.exists()]
    summaries = [path for path in [outputs / "expert-summary.md", outputs / "summary.md"] if path.exists()]
    artifacts = candidates + summaries
    if not artifacts:
        raise ValueError(f"no peer training outputs found under {outputs}")

    reports: list[TrainingIntegrationReport] = []
    for artifact in artifacts:
        reports.append(integrate_training_artifact(
            artifact,
            stage_approved=stage_approved,
            merge_patterns=merge_patterns,
            min_score=min_score,
            candidate_out_path=candidate_out_path,
            skill_path=skill_path,
            rag_path=rag_path,
            pending_path=pending_path,
            brain_path=brain_path,
            merge_log_path=merge_log_path,
            manifest_path=manifest_path,
        ))

    return PeerTrainingLabIntegrationReport(
        lab_dir=str(lab_dir),
        integrated_artifacts=[report.source_path for report in reports],
        staged=sum(report.staged for report in reports),
        imported=sum(report.imported for report in reports),
        rejected=sum(report.rejected for report in reports),
        merged_count=sum(report.merged_count for report in reports),
        skipped_readonly_count=sum(report.skipped_readonly_count for report in reports),
        new_pattern_ids=[pid for report in reports for pid in report.new_pattern_ids],
        reports=[asdict(report) for report in reports],
        safety_notes=[
            "peer_lab_is_training_only",
            "production_decision_path_unchanged",
            "memory_merge_requires_explicit_merge_patterns_flag",
        ],
    )


def import_candidates(
    candidate_file: Path,
    *,
    out_path: Path = DEFAULT_CANDIDATE_PATH,
    stage_approved: bool = False,
    min_score: float = 0.75,
    skill_path: Path = DEFAULT_MARKETING_SKILL_PATH,
    rag_path: Path = DEFAULT_RAG_PATH,
    pending_path: Path = cs_brain.PENDING_PATTERNS,
    brain_path: Path = cs_brain.PROJECT_BRAIN,
) -> CandidateImportReport:
    rows = _read_candidate_rows(candidate_file)
    accepted: list[dict] = []
    rejected = 0
    staged = 0
    reasons: list[str] = []
    for raw_row in rows:
        row = _normalize_candidate_row(raw_row)
        ok, reason = _validate_candidate(row)
        if not ok:
            rejected += 1
            reasons.append(f"{row.get('id', '<no-id>')}:{reason}")
            continue
        redacted, raw_hash = _redact_text(str(row.get("text", "")))
        clean = dict(row)
        clean["id"] = _candidate_id(row)
        clean["text"] = redacted
        clean["raw_text_hash"] = raw_hash
        clean.setdefault("approved", False)
        clean.setdefault("imported_at", _now())
        accepted.append(clean)
        if stage_approved and clean.get("approved") and float(clean.get("score") or 0.0) >= min_score:
            staged += _stage_candidate(clean, skill_path=skill_path, rag_path=rag_path, pending_path=pending_path, brain_path=brain_path)
    imported = _append_jsonl(out_path, accepted)
    return CandidateImportReport(
        imported=imported,
        rejected=rejected,
        staged=staged,
        candidate_path=str(out_path),
        rejection_reasons=reasons,
    )


def integrate_training_artifact(
    artifact_path: Path,
    *,
    stage_approved: bool = False,
    merge_patterns: bool = False,
    min_score: float = 0.75,
    candidate_out_path: Path = DEFAULT_CANDIDATE_PATH,
    skill_path: Path = DEFAULT_MARKETING_SKILL_PATH,
    rag_path: Path = DEFAULT_RAG_PATH,
    pending_path: Path = cs_brain.PENDING_PATTERNS,
    brain_path: Path = cs_brain.PROJECT_BRAIN,
    merge_log_path: Path = cs_brain.MERGE_LOG,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> TrainingIntegrationReport:
    """Integrate independent training output into Skill/RAG/Memory safely.

    - `.jsonl` / `.json`: structured teacher-student candidate rows. Rows are
      archived first; only `approved=true` and `score >= min_score` rows are
      staged when `stage_approved=True`.
    - `.md` / `.txt`: expert-knowledge style summary document routed through
      the document ingest classifier. Without `stage_approved`, this is dry-run.
    - `merge_patterns=True` promotes staged memory from pending to Brain using
      `cs_brain.merge`; readonly protections and duplicate context rules remain
      in force.
    """

    suffix = artifact_path.suffix.lower()
    safety_notes = [
        "no_model_weight_finetuning",
        "skill_rag_memory_only",
        "memory_uses_pending_before_merge",
    ]
    imported = rejected = staged = 0
    written_skill = written_rag = written_memory = 0
    rejection_reasons: list[str] = []
    candidate_path = ""

    if suffix in {".jsonl", ".json"}:
        candidate_report = import_candidates(
            artifact_path,
            out_path=candidate_out_path,
            stage_approved=stage_approved,
            min_score=min_score,
            skill_path=skill_path,
            rag_path=rag_path,
            pending_path=pending_path,
            brain_path=brain_path,
        )
        imported = candidate_report.imported
        rejected = candidate_report.rejected
        staged = candidate_report.staged
        candidate_path = candidate_report.candidate_path
        rejection_reasons = candidate_report.rejection_reasons
    elif suffix in {".md", ".txt"}:
        text = artifact_path.read_text(encoding="utf-8")
        ingest_report = ingest_document(
            text,
            source=f"external-training:{artifact_path.name}",
            apply=stage_approved,
            approved_memory=stage_approved,
            skill_path=skill_path,
            rag_path=rag_path,
            pending_path=pending_path,
            manifest_path=manifest_path,
        )
        written_skill = ingest_report.written_skill_items
        written_rag = ingest_report.written_rag_items
        written_memory = ingest_report.written_memory_items
        staged = written_skill + written_rag + written_memory
        rejected = ingest_report.blocked_chunks
        rejection_reasons = [f"blocked_chunks={ingest_report.blocked_chunks}"] if ingest_report.blocked_chunks else []
    else:
        raise ValueError("training artifact must be .jsonl, .json, .md, or .txt")

    merged_count = skipped_readonly = 0
    new_ids: list[str] = []
    if merge_patterns and stage_approved:
        merge_report = cs_brain.merge(pending_path=pending_path, brain_path=brain_path, log_path=merge_log_path)
        merged_count = merge_report.merged_count
        skipped_readonly = merge_report.skipped_readonly_count
        new_ids = merge_report.new_pattern_ids
    elif merge_patterns:
        safety_notes.append("merge_skipped_stage_approved_false")

    return TrainingIntegrationReport(
        mode="structured_candidates" if suffix in {".jsonl", ".json"} else "expert_document",
        source_path=str(artifact_path),
        imported=imported,
        rejected=rejected,
        staged=staged,
        written_skill_items=written_skill,
        written_rag_items=written_rag,
        written_memory_items=written_memory,
        merged_count=merged_count,
        skipped_readonly_count=skipped_readonly,
        new_pattern_ids=new_ids,
        candidate_path=candidate_path,
        skill_path=str(skill_path),
        rag_path=str(rag_path),
        pending_path=str(pending_path),
        brain_path=str(brain_path),
        rejection_reasons=rejection_reasons,
        safety_notes=safety_notes,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compliance Sentinel external learning lab bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    p_export = sub.add_parser("export", help="export sanitized learning bundle")
    p_export.add_argument("--out", default=str(DEFAULT_EXPORT_DIR), help="output directory")
    p_export.add_argument("--json", action="store_true")

    p_import = sub.add_parser("import-candidates", help="import external candidate JSONL/JSON")
    p_import.add_argument("path", help="candidate JSONL/JSON path")
    p_import.add_argument("--out", default=str(DEFAULT_CANDIDATE_PATH), help="candidate archive JSONL")
    p_import.add_argument("--stage-approved", action="store_true", help="stage approved candidates into Skill/RAG/Memory pending")
    p_import.add_argument("--min-score", type=float, default=0.75)
    p_import.add_argument("--json", action="store_true")

    p_integrate = sub.add_parser("integrate-results", help="integrate independent training results into Skill/RAG/Memory and optionally Brain")
    p_integrate.add_argument("path", help="training artifact path (.jsonl/.json candidates or .md/.txt expert-style summary)")
    p_integrate.add_argument("--out", default=str(DEFAULT_CANDIDATE_PATH), help="candidate archive JSONL for structured artifacts")
    p_integrate.add_argument("--stage-approved", action="store_true", help="write approved candidates/document chunks into Skill/RAG/Memory pending")
    p_integrate.add_argument("--merge-patterns", action="store_true", help="merge staged memory pending patterns into project Brain")
    p_integrate.add_argument("--min-score", type=float, default=0.75)
    p_integrate.add_argument("--json", action="store_true")

    p_peer_create = sub.add_parser("create-peer-lab", help="create local-only Pi-to-Pi style teacher/student training lab scaffold")
    p_peer_create.add_argument("--out", help="lab output directory. Default: training/peer-labs/<run-id>")
    p_peer_create.add_argument("--run-id", help="stable run id")
    p_peer_create.add_argument("--topic", default="financial marketing compliance teacher-student loop")
    p_peer_create.add_argument("--source-artifact", help="optional source document/eval artifact path")
    p_peer_create.add_argument("--json", action="store_true")

    p_peer_integrate = sub.add_parser("integrate-peer-lab", help="integrate outputs from a local peer training lab")
    p_peer_integrate.add_argument("path", help="peer lab directory containing outputs/")
    p_peer_integrate.add_argument("--out", default=str(DEFAULT_CANDIDATE_PATH), help="candidate archive JSONL for structured artifacts")
    p_peer_integrate.add_argument("--stage-approved", action="store_true")
    p_peer_integrate.add_argument("--merge-patterns", action="store_true")
    p_peer_integrate.add_argument("--min-score", type=float, default=0.75)
    p_peer_integrate.add_argument("--json", action="store_true")
    return parser


def _print_report(report: object, *, as_json: bool) -> None:
    data = asdict(report)
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for key, value in data.items():
            print(f"{key}: {value}")


def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "export":
        report = export_learning_bundle(out_dir=Path(args.out))
        _print_report(report, as_json=args.json)
        return 0
    if args.command == "import-candidates":
        path = Path(args.path)
        if not path.exists():
            print(f"candidate file not found: {path}", file=sys.stderr)
            return 1
        report = import_candidates(
            path,
            out_path=Path(args.out),
            stage_approved=args.stage_approved,
            min_score=args.min_score,
        )
        _print_report(report, as_json=args.json)
        return 0
    if args.command == "integrate-results":
        path = Path(args.path)
        if not path.exists():
            print(f"training artifact not found: {path}", file=sys.stderr)
            return 1
        report = integrate_training_artifact(
            path,
            candidate_out_path=Path(args.out),
            stage_approved=args.stage_approved,
            merge_patterns=args.merge_patterns,
            min_score=args.min_score,
        )
        _print_report(report, as_json=args.json)
        return 0
    if args.command == "create-peer-lab":
        source_artifact = Path(args.source_artifact) if args.source_artifact else None
        if source_artifact and not source_artifact.exists():
            print(f"source artifact not found: {source_artifact}", file=sys.stderr)
            return 1
        report = create_peer_training_lab(
            out_dir=Path(args.out) if args.out else None,
            run_id=args.run_id,
            topic=args.topic,
            source_artifact=source_artifact,
        )
        _print_report(report, as_json=args.json)
        return 0
    if args.command == "integrate-peer-lab":
        path = Path(args.path)
        if not path.exists():
            print(f"peer lab not found: {path}", file=sys.stderr)
            return 1
        report = integrate_peer_training_lab(
            path,
            candidate_out_path=Path(args.out),
            stage_approved=args.stage_approved,
            merge_patterns=args.merge_patterns,
            min_score=args.min_score,
        )
        _print_report(report, as_json=args.json)
        return 0
    parser.error("unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
