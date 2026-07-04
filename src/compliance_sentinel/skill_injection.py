"""Internal agent skill injection helpers.

Generated review skills live outside Python package code under `agents/skills/` so
compliance/legal teams can review them as documents. Runtime LLM prompts can opt
out with `CS_ENABLE_SKILL_INJECTION=0`.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MARKETING_SKILL_PATH = PROJECT_ROOT / "agents" / "skills" / "financial_marketing_content_reviewer" / "SKILL.md"
PERSONA_SKILL_DIR = PROJECT_ROOT / "agents" / "skills" / "compliance_board_personas"
AD_PROPOSER_SKILL_PATH = PROJECT_ROOT / "agents" / "skills" / "ad_copy_proposer" / "SKILL.md"
AD_REVIEWER_SKILL_PATH = PROJECT_ROOT / "agents" / "skills" / "ad_copy_reviewer" / "SKILL.md"

ROLE_SKILL_MAP: dict[str, list[Path]] = {
    "ad_copy_proposer": [DEFAULT_MARKETING_SKILL_PATH, AD_PROPOSER_SKILL_PATH],
    "ad_copy_reviewer": [DEFAULT_MARKETING_SKILL_PATH, AD_REVIEWER_SKILL_PATH],
    "legal_counsel": [DEFAULT_MARKETING_SKILL_PATH, PERSONA_SKILL_DIR / "legal_counsel.md"],
    "pipa_expert": [DEFAULT_MARKETING_SKILL_PATH, PERSONA_SKILL_DIR / "pipa_credit_info.md"],
    "consumer_protection": [DEFAULT_MARKETING_SKILL_PATH, PERSONA_SKILL_DIR / "consumer_protection.md"],
    "operational_risk": [DEFAULT_MARKETING_SKILL_PATH, PERSONA_SKILL_DIR / "operational_risk.md"],
    "business_practicality": [DEFAULT_MARKETING_SKILL_PATH, PERSONA_SKILL_DIR / "business_practicality.md"],
    "contrarian": [DEFAULT_MARKETING_SKILL_PATH, PERSONA_SKILL_DIR / "contrarian.md"],
    "ceo_synthesizer": [DEFAULT_MARKETING_SKILL_PATH],
    "verifier": [DEFAULT_MARKETING_SKILL_PATH],
    "adversarial_critic": [DEFAULT_MARKETING_SKILL_PATH],
    "independent_validator": [DEFAULT_MARKETING_SKILL_PATH],
    "cross_model_verifier": [DEFAULT_MARKETING_SKILL_PATH],
}


@lru_cache(maxsize=32)
def _read_skill_cached(path_str: str, mtime_ns: int, size: int, max_chars: int) -> tuple[str, bool]:
    _ = (mtime_ns, size)
    text = Path(path_str).read_text(encoding="utf-8").strip()
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + "\n\n<!-- truncated for prompt budget -->"
    return text, truncated


def _read_skill(path: Path, max_chars: int) -> tuple[str, bool]:
    stat = path.stat()
    return _read_skill_cached(str(path.resolve()), stat.st_mtime_ns, stat.st_size, max_chars)


def load_injected_skill_context(role: str, *, max_chars_per_skill: int = 8000) -> str:
    """Return markdown skill context for a role.

    Missing skill files are ignored. This keeps fresh clones working before any
    document-ingest run has generated project-local skills.
    """

    if os.environ.get("CS_ENABLE_SKILL_INJECTION", "1") == "0":
        return ""
    chunks: list[str] = []
    for path in ROLE_SKILL_MAP.get(role, []):
        if not path.exists():
            continue
        text, _truncated = _read_skill(path, max_chars_per_skill)
        if not text:
            continue
        chunks.append(f"## Injected Project Skill: {path.name}\n\n{text}")
    if not chunks:
        return ""
    return "\n\n---\n\n" + "\n\n---\n\n".join(chunks)


def skill_injection_status(role: str | None = None, *, max_chars_per_skill: int = 8000) -> dict[str, Any]:
    """Return operational status for project skill injection.

    This is intentionally metadata-only: it never returns full skill text, so it
    is safe to expose in health panels or diagnostics.
    """

    roles = [role] if role else sorted(ROLE_SKILL_MAP)
    role_reports: dict[str, Any] = {}
    loaded_total = 0
    missing_total = 0
    for item_role in roles:
        entries = []
        for path in ROLE_SKILL_MAP.get(item_role, []):
            exists = path.exists()
            entry: dict[str, Any] = {"path": str(path), "exists": exists}
            if exists:
                text, truncated = _read_skill(path, max_chars_per_skill)
                entry.update({"chars": len(text), "truncated": truncated})
                loaded_total += 1
            else:
                missing_total += 1
            entries.append(entry)
        role_reports[item_role] = {"configured": len(entries), "skills": entries}
    return {
        "enabled": os.environ.get("CS_ENABLE_SKILL_INJECTION", "1") != "0",
        "roles_checked": len(roles),
        "loaded_skill_files": loaded_total,
        "missing_skill_files": missing_total,
        "roles": role_reports,
    }


def clear_skill_cache() -> None:
    """Test/maintenance helper."""

    _read_skill_cached.cache_clear()
