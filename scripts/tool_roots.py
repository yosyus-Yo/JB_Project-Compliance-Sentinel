"""Portable root discovery for sibling governance tools.

The project is developed on macOS/WSL/Linux and Windows. Tool wrappers resolve a
tool root in this order:
  1. explicit env var (AGENTSHIELD_ROOT / AGENTLOOP_ROOT / AGENTCOMPILER_ROOT)
  2. **vendored copy bundled in this repo** (third_party/<tool>) — so a fresh
     clone + env setup works with no external checkout
  3. sibling workspace repository (dev machines with the tool checked out beside)
  4. legacy C:/CC_project layout used by earlier documentation
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
VENDOR_ROOT = PROJECT_ROOT / "third_party"
LEGACY_WINDOWS_ROOT = Path("C:/CC_project")


def default_tool_root(tool_name: str, env_var: str | None = None) -> Path:
    """Return the best default root for a governance tool repository."""

    env_key = env_var or f"{tool_name.upper()}_ROOT"
    configured = os.environ.get(env_key)
    if configured:
        return Path(configured).expanduser()
    candidates = [
        VENDOR_ROOT / tool_name.lower(),   # bundled copy (self-contained clone)
        WORKSPACE_ROOT / tool_name,        # sibling checkout on dev machines
        LEGACY_WINDOWS_ROOT / tool_name,   # legacy path
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


DEFAULT_AGENTSHIELD_ROOT = default_tool_root("AgentShield", "AGENTSHIELD_ROOT")
DEFAULT_AGENTLOOP_ROOT = default_tool_root("AgentLoop", "AGENTLOOP_ROOT")
DEFAULT_AGENTCOMPILER_ROOT = default_tool_root("AgentCompiler", "AGENTCOMPILER_ROOT")
