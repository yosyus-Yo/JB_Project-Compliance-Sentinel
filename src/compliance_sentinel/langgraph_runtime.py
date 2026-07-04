"""LangGraph runtime helpers for checkpointing and human-review breakpoints.

The core workflow remains deterministic by default. These helpers make the
optional LangGraph path operationally safer without forcing external services:

- opt-in in-memory checkpointing via ``CS_LANGGRAPH_CHECKPOINT=1``
- stable, non-PII thread IDs derived from input hash
- optional static breakpoint before a human-review gate for operator demos

For durable production persistence, replace the default in-memory saver with a
Postgres/SQLite checkpointer and pass it to ``build_graph(checkpointer=...)``.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any, Optional


def env_flag(name: str, default: str = "0") -> bool:
    """Return true for common truthy environment values."""

    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def make_thread_id(input_text: str, *, prefix: str = "cs") -> str:
    """Create a stable thread id without embedding raw/PII input text."""

    digest = hashlib.sha256(input_text.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def config_for_input(input_text: str, *, enable_checkpoint: Optional[bool] = None) -> tuple[dict[str, Any] | None, str | None]:
    """Return LangGraph RunnableConfig and thread id when checkpointing is on."""

    checkpoint_enabled = env_flag("CS_LANGGRAPH_CHECKPOINT") if enable_checkpoint is None else enable_checkpoint
    if not checkpoint_enabled:
        return None, None
    thread_id = os.environ.get("CS_LANGGRAPH_THREAD_ID") or make_thread_id(input_text)
    return {"configurable": {"thread_id": thread_id}}, thread_id


def compile_options(
    *,
    enable_checkpoint: Optional[bool] = None,
    checkpointer: Any = None,
    interrupt_before: list[str] | tuple[str, ...] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build kwargs for ``StateGraph.compile`` and safe runtime metadata.

    ``interrupt_before`` requires a checkpointer in LangGraph. If a breakpoint is
    requested we automatically enable checkpointing.
    """

    checkpoint_enabled = env_flag("CS_LANGGRAPH_CHECKPOINT") if enable_checkpoint is None else bool(enable_checkpoint)
    if interrupt_before is None and env_flag("CS_LANGGRAPH_INTERRUPT_BEFORE_HUMAN_GATE"):
        interrupt_before = ["human_review_gate"]
    if interrupt_before:
        checkpoint_enabled = True

    kwargs: dict[str, Any] = {}
    checkpointer_kind = "none"
    if checkpoint_enabled:
        if checkpointer is None:
            try:  # optional dependency path inside langgraph
                from langgraph.checkpoint.memory import InMemorySaver  # type: ignore

                checkpointer = InMemorySaver()
                checkpointer_kind = "memory"
            except Exception:
                checkpointer = None
                checkpointer_kind = "unavailable"
        else:
            checkpointer_kind = type(checkpointer).__name__
        if checkpointer is not None:
            kwargs["checkpointer"] = checkpointer

    if interrupt_before:
        kwargs["interrupt_before"] = list(interrupt_before)

    metadata = {
        "checkpoint_enabled": bool(kwargs.get("checkpointer")),
        "checkpointer": checkpointer_kind,
        "interrupt_before": list(interrupt_before or []),
        "thread_id_required": bool(kwargs.get("checkpointer")),
    }
    return kwargs, metadata


def human_review_gate_metadata(
    *,
    required: bool,
    reasons: list[str],
    gate_name: str = "human_review_gate",
) -> dict[str, Any]:
    """Normalize graph HITL gate metadata for reports/audits."""

    return {
        "gate": gate_name,
        "required": required,
        "reasons": reasons,
        "checkpoint_required_for_interrupt_resume": True,
        "resume_instruction": "Review the audit_log_id and resume the LangGraph thread after approval.",
    }
