"""Execution engine selector for Compliance Sentinel.

The project keeps a deterministic Python workflow as the safety baseline, while
LangGraph can be promoted to the primary execution path when installed and
explicitly enabled. This module centralizes that decision so CLI/API/demo use the
same path and AgentCompiler-readiness stays visible at the graph boundary.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Iterable, Literal

from .agent_shield_bridge import (
    enforce_input_guard,
    guard_status,
    high_confidence_injection,
    input_guard_enforced,
    inspect_input_text,
    inspect_output_text,
)
from .audit import AuditStore
from .classification import classify_input
from .models import ComplianceState
from .report_schema import build_blocked_final_report
from .langgraph_runtime import config_for_input
from .marketing_workflow import MarketingContentReviewAgent
from .telemetry import _emit_l3_trace, emit_compliance_trace, langsmith_record_run
from .triage import build_not_applicable_report, triage_input
from .workflow import ComplianceSentinel

EngineName = Literal["deterministic", "langgraph"]
_AGENT_CACHE: dict[tuple[str, str], object] = {}
_AGENT_CACHE_LOCK = threading.Lock()

# LangGraph marketing/compliance review nodes. Used to filter astream_events progress
# events down to UI-facing graph steps (T1 realtime loader).
# 광고(marketing)와 약관/일반(compliance) 경로는 노드명이 다르므로 둘 다 화이트리스트에 포함해야
# 두 경로 모두 실시간 로더가 동작한다 (compliance 경로 누락 시 로더가 일부만 켜지는 버그 수정).
_GRAPH_NODE_SEQUENCE: tuple[str, ...] = (
    # 광고(marketing) 경로
    "content_intake",
    "understand_content",
    "memory_review",
    "llm_advisory_board",
    # 약관/일반(compliance) 경로
    "classify_input",
    "pii_guard",
    "retrieve_context",
    "board_review",
    "verify_atomic_claims",
    # 공유 노드
    "synthesize",
    "independent_validation",
    "human_review_gate",
    "final_report",
)
_GRAPH_NODE_NAMES = frozenset(_GRAPH_NODE_SEQUENCE)


@dataclass(frozen=True)
class EngineResult:
    """Result plus execution backend metadata."""

    state: ComplianceState
    engine: EngineName
    fallback_reason: str | None = None


@dataclass(frozen=True)
class BatchEngineResult:
    """Batch analysis metadata for reusable-agent deterministic processing."""

    results: list[EngineResult]
    item_count: int
    elapsed_seconds: float
    reused_agents: bool
    engine: EngineName


def _apply_revision_visibility(report: dict[str, Any] | None, include_revision: bool) -> None:
    """입력 시 '수정 제안 생성' 토글을 보고서 레벨에서 통일 적용 (광고/약관 공통).

    include_revision=False(기본, 심의만) → 수정 제안/원고 제거. 심의 결과(findings/risk/approval/
    board/verifier)는 절대 변경하지 않음 — 제거 대상은 보조 제안 레이어뿐.
    LangGraph 마케팅 경로는 그래프 내부에서 rewrite 생성 자체를 스킵(비용 절감)하고, 본 헬퍼는
    정적 revision_suggestions 억제 + 마커 부착을 두 엔진/스트림 경로에 일관되게 보장(멱등).
    """
    if not report:
        return
    report["revision_included"] = include_revision
    if not include_revision:
        report["revision_suggestions"] = []
        report.pop("marketing_rewrite", None)
        report.pop("rewrite_review", None)


def _blocked_engine_result(input_text: str, input_guard: dict[str, Any], *, started: float) -> EngineResult:
    """Build a short-circuited EngineResult that rejects guard-blocked input
    without running the analysis agents (so malicious content never reaches the
    LLM board / deterministic workflow)."""

    state = ComplianceState(input_text=input_text, input_type=classify_input(input_text))
    state.final_report = build_blocked_final_report(input_guard.get("reasons"))
    state.add_trace(
        "agentshield_input_guard_block",
        reasons=input_guard.get("reasons", []),
        mode=input_guard.get("mode"),
    )
    _attach_profile(state, started=started, engine="blocked")
    _attach_agentshield_runtime_guard(state, input_guard=input_guard)
    return EngineResult(state=state, engine="blocked", fallback_reason="agentshield_input_guard_blocked")


@_emit_l3_trace
def analyze_with_engine(
    input_text: str,
    *,
    audit_path: str | Path | None = None,
    prefer_langgraph: bool = True,
    include_revision: bool = False,
) -> EngineResult:
    """Analyze text using LangGraph when available, otherwise safe baseline.

    LangGraph is selected only when both conditions hold:
    1. `prefer_langgraph` is true
    2. `langgraph_adapter.is_available()` is true (`langgraph` installed and
       `USE_LANGGRAPH=1`)

    Any LangGraph runtime failure falls back to the deterministic workflow. This
    keeps demo/CLI/API reliable while making the graph path the primary option
    in environments prepared for LangGraph and future AgentCompiler work.
    """

    started = time.perf_counter()
    input_guard = inspect_input_text(input_text)
    if input_guard_enforced() and not input_guard.get("allowed", True) and high_confidence_injection(input_text):
        return _blocked_engine_result(input_text, input_guard, started=started)
    audit_store = AuditStore(audit_path) if audit_path else AuditStore()
    input_type = classify_input(input_text)
    use_marketing_agent = input_type == "advertisement"

    # Pre-board triage gate — 인사/잡담/테스트 같은 비심의 입력을 6인 보드 앞단에서 차단.
    # 보수적 fail-safe(애매하면 심의). 차단 시 보드/그래프 전체를 스킵하고 NOT_APPLICABLE 반환.
    if os.environ.get("CS_ENABLE_TRIAGE", "1") != "0":
        triage = triage_input(input_text)
        if not triage.reviewable:
            report = build_not_applicable_report(input_text, triage)
            state = ComplianceState(
                input_text=input_text,
                redacted_text=input_text,
                input_type=input_type,
                final_report=report,
            )
            state.add_trace(
                "triage_gate",
                reviewable=False,
                layer=triage.layer,
                reason=triage.reason,
                board_skipped=True,
            )
            _attach_profile(state, started=started, engine="deterministic")
            _attach_agentshield_runtime_guard(state, input_guard=input_guard)
            return EngineResult(
                state=state,
                engine="deterministic",
                fallback_reason="triage_not_applicable",
            )

    if prefer_langgraph:
        try:
            if use_marketing_agent:
                from . import marketing_langgraph_adapter

                if marketing_langgraph_adapter.is_available():
                    graph = marketing_langgraph_adapter.build_graph(audit_store=audit_store)
                    config, thread_id = config_for_input(input_text)
                    payload = {"input_text": input_text, "retry_count": 0, "include_revision": include_revision}
                    output = graph.invoke(payload, config=config) if config else graph.invoke(payload)
                    state = _state_from_graph_output(input_text, output)
                    _apply_revision_visibility(state.final_report, include_revision)
                    _attach_langgraph_metadata(state, thread_id=thread_id)
                    _attach_profile(state, started=started, engine="langgraph")
                    _attach_langsmith_trace(state, engine="langgraph")
                    _attach_agentshield_runtime_guard(state, input_guard=input_guard)
                    return EngineResult(
                        state=state,
                        engine="langgraph",
                    )
            else:
                from . import langgraph_adapter

                if langgraph_adapter.is_available():
                    graph = langgraph_adapter.build_graph(audit_store=audit_store)
                    config, thread_id = config_for_input(input_text)
                    payload = {"input_text": input_text, "retry_count": 0, "include_revision": include_revision}
                    output = graph.invoke(payload, config=config) if config else graph.invoke(payload)
                    state = _state_from_graph_output(input_text, output)
                    _apply_revision_visibility(state.final_report, include_revision)
                    _attach_langgraph_metadata(state, thread_id=thread_id)
                    _attach_profile(state, started=started, engine="langgraph")
                    _attach_langsmith_trace(state, engine="langgraph")
                    _attach_agentshield_runtime_guard(state, input_guard=input_guard)
                    return EngineResult(
                        state=state,
                        engine="langgraph",
                    )
            fallback_reason = "langgraph_not_enabled_or_not_installed"
        except Exception as exc:  # pragma: no cover - depends on optional runtime
            fallback_reason = f"langgraph_failed:{type(exc).__name__}:{exc}"
    else:
        fallback_reason = "prefer_langgraph_false"

    if use_marketing_agent:
        agent = _get_reusable_agent("marketing", audit_store)
        state = agent.analyze(input_text)  # type: ignore[attr-defined]
    else:
        agent = _get_reusable_agent("compliance", audit_store)
        state = agent.analyze(input_text)  # type: ignore[attr-defined]
    state.add_trace("engine_route", input_type=input_type, agent="marketing" if use_marketing_agent else "compliance", reused_agent=True)
    _apply_revision_visibility(state.final_report, include_revision)
    _attach_profile(state, started=started, engine="deterministic")
    _attach_langsmith_trace(state, engine="deterministic")
    _attach_agentshield_runtime_guard(state, input_guard=input_guard)
    return EngineResult(state=state, engine="deterministic", fallback_reason=fallback_reason)


def analyze_batch_with_engine(
    input_texts: Iterable[str],
    *,
    audit_path: str | Path | None = None,
    prefer_langgraph: bool = False,
    reuse_agents: bool = True,
) -> BatchEngineResult:
    """Analyze many inputs while reusing deterministic agent instances.

    This is the lightweight operational scaling path: keep single-request behavior
    unchanged, but avoid repeated KB/model/memory initialization for batch jobs.
    LangGraph batch reuse is intentionally not implemented here; callers that set
    `prefer_langgraph=True` fall back to the existing single-request selector.
    """
    texts = list(input_texts)
    started = time.perf_counter()
    if not texts:
        return BatchEngineResult(results=[], item_count=0, elapsed_seconds=0.0, reused_agents=False, engine="deterministic")

    if not reuse_agents or prefer_langgraph:
        results = [analyze_with_engine(text, audit_path=audit_path, prefer_langgraph=prefer_langgraph) for text in texts]
        elapsed = time.perf_counter() - started
        engine = results[0].engine if results else "deterministic"
        return BatchEngineResult(results=results, item_count=len(results), elapsed_seconds=elapsed, reused_agents=False, engine=engine)

    audit_store = AuditStore(audit_path) if audit_path else AuditStore()
    marketing_agent = MarketingContentReviewAgent(audit_store=audit_store)
    compliance_agent = ComplianceSentinel(audit_store=audit_store)
    results: list[EngineResult] = []
    for text in texts:
        item_guard = inspect_input_text(text)
        if input_guard_enforced() and not item_guard.get("allowed", True) and high_confidence_injection(text):
            results.append(_blocked_engine_result(text, item_guard, started=started))
            continue
        input_type = classify_input(text)
        if input_type == "advertisement":
            state = marketing_agent.analyze(text)
            agent_name = "marketing"
        else:
            state = compliance_agent.analyze(text)
            agent_name = "compliance"
        state.add_trace("engine_route", input_type=input_type, agent=agent_name, batch_reused_agent=True)
        results.append(EngineResult(state=state, engine="deterministic", fallback_reason="batch_reused_agent"))
    elapsed = time.perf_counter() - started
    return BatchEngineResult(results=results, item_count=len(results), elapsed_seconds=elapsed, reused_agents=True, engine="deterministic")


def analyze_text(input_text: str, *, audit_path: str | Path | None = None) -> dict:
    """Backward-compatible API returning only the final report."""

    return analyze_with_engine(input_text, audit_path=audit_path).state.final_report


async def astream_review_events(
    input_text: str,
    *,
    audit_path: str | Path | None = None,
    include_revision: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Stream node-level progress events for the real-time review loader (T1).

    Yields progress dicts as the LangGraph review advances through its nodes:

    - ``{"node": <name>, "status": "start"}``    when a graph node begins
    - ``{"node": <name>, "status": "complete"}``  when a graph node ends
    - ``{"node": "final_report", "status": "result", "result": <report dict>}``
      once, after the graph finishes, carrying the final report payload.

    This is an additive async path for UI progress display only. The synchronous
    ``analyze_with_engine`` invoke path and the deterministic baseline are left
    unchanged, so compliance verdict logic is not affected — events describe
    execution position, not decisions.

    Raises:
        RuntimeError: when ``langgraph`` is not installed or ``USE_LANGGRAPH`` is
            not enabled. Callers (the SSE endpoint in T2) should catch this and
            fall back to ``analyze_with_engine``, emitting a single terminal
            ``result`` event from the deterministic path.
    """

    # Library-level guard: the streaming generator is public/importable, so the
    # guard lives here (not only in the /review/stream API wrapper). A
    # high-confidence injection is rejected before the graph starts.
    blocked = enforce_input_guard(input_text)
    if blocked is not None:
        emit_compliance_trace(ComplianceState(input_text=input_text, redacted_text=input_text, final_report=blocked))
        yield {"node": "final_report", "status": "result", "result": blocked}
        return

    audit_store = AuditStore(audit_path) if audit_path else AuditStore()
    input_type = classify_input(input_text)
    use_marketing_agent = input_type == "advertisement"

    # Pre-board triage gate (스트림 경로) — 비심의 입력이면 보드 그래프를 시작하지 않고
    # 단일 분류 스텝 + NOT_APPLICABLE 결과만 방출 (로더는 즉시 완료, 보드 미실행).
    if os.environ.get("CS_ENABLE_TRIAGE", "1") != "0":
        triage = triage_input(input_text)
        if not triage.reviewable:
            report = build_not_applicable_report(input_text, triage)
            _triage_state = ComplianceState(
                input_text=input_text, redacted_text=input_text, input_type=input_type, final_report=report
            )
            _triage_state.add_trace("classify_input", reviewable=False)
            emit_compliance_trace(_triage_state)
            yield {"node": "classify_input", "status": "start"}
            yield {"node": "classify_input", "status": "complete"}
            yield {"node": "final_report", "status": "result", "result": report}
            return

    if use_marketing_agent:
        from . import marketing_langgraph_adapter as adapter
    else:
        from . import langgraph_adapter as adapter

    if not adapter.is_available():
        raise RuntimeError("langgraph_not_enabled_or_not_installed")

    graph = adapter.build_graph(audit_store=audit_store)
    config, _thread_id = config_for_input(input_text)
    payload = {"input_text": input_text, "retry_count": 0, "include_revision": include_revision}

    stream = (
        graph.astream_events(payload, config=config, version="v2")
        if config
        else graph.astream_events(payload, version="v2")
    )

    final_output: dict[str, Any] | None = None
    async for event in stream:
        name = event.get("name")
        kind = event.get("event")
        if name in _GRAPH_NODE_NAMES:
            if kind == "on_chain_start":
                yield {"node": name, "status": "start"}
            elif kind == "on_chain_end":
                yield {"node": name, "status": "complete"}
        elif kind == "on_chain_end" and not event.get("parent_ids"):
            # Top-level graph completion carries the accumulated final state.
            output = (event.get("data") or {}).get("output")
            if isinstance(output, dict):
                final_output = output

    if final_output is not None:
        state = _state_from_graph_output(input_text, final_output)
        _apply_revision_visibility(state.final_report, include_revision)
        emit_compliance_trace(state)  # L3 외부연동 — stream(LangGraph graph) 경로
        yield {
            "node": "final_report",
            "status": "result",
            "result": state.final_report,
        }


def _get_reusable_agent(kind: str, audit_store: AuditStore) -> object:
    """Return a process-local reusable deterministic agent.

    Agent instances are stateless across calls except for reusable dependencies
    such as KB/RAG/model clients. Cache by audit path so append-only logging stays
    routed to the requested file.
    """

    if os.environ.get("CS_DISABLE_AGENT_REUSE") == "1":
        return MarketingContentReviewAgent(audit_store=audit_store) if kind == "marketing" else ComplianceSentinel(audit_store=audit_store)
    cache_key = (kind, str(audit_store.path.resolve()))
    with _AGENT_CACHE_LOCK:
        cached = _AGENT_CACHE.get(cache_key)
        if cached is not None:
            return cached
        agent: object = MarketingContentReviewAgent(audit_store=audit_store) if kind == "marketing" else ComplianceSentinel(audit_store=audit_store)
        _AGENT_CACHE[cache_key] = agent
        return agent


def clear_agent_cache() -> None:
    """Test/maintenance helper for resetting process-local reusable agents."""

    with _AGENT_CACHE_LOCK:
        _AGENT_CACHE.clear()


def _attach_profile(state: ComplianceState, *, started: float, engine: EngineName) -> None:
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    state.add_trace("engine_profile", engine=engine, elapsed_ms=elapsed_ms)
    if os.environ.get("CS_PROFILE") == "1" and state.final_report is not None:
        state.final_report["performance_profile"] = {
            "engine": engine,
            "elapsed_ms": elapsed_ms,
            "trace_events": len(state.trace),
            "rag_cache_hit": bool(state.rag_metadata.get("rag_cache_hit")),
        }


def _attach_langgraph_metadata(state: ComplianceState, *, thread_id: str | None) -> None:
    metadata = {
        "enabled": True,
        "checkpoint_enabled": thread_id is not None,
        "thread_id": thread_id,
        "hitl_gate": state.final_report.get("human_review_gate") if state.final_report else None,
    }
    if state.final_report is not None:
        state.final_report["langgraph_runtime"] = metadata
    state.add_trace("langgraph_runtime", **metadata)


def _attach_langsmith_trace(state: ComplianceState, *, engine: EngineName) -> None:
    if not os.environ.get("LANGSMITH_API_KEY") or not state.final_report:
        return
    report = state.final_report
    run_id = langsmith_record_run(
        "compliance_sentinel_review",
        inputs={
            "redacted_text": state.redacted_text,
            "input_type": state.input_type,
            "raw_input_included": False,
        },
        outputs={
            "audit_log_id": report.get("audit_log_id") or state.audit_log_id,
            "status": report.get("approval_status") or report.get("status"),
            "risk_level": report.get("risk_level"),
            "human_review_needed": report.get("human_review_needed"),
            "finding_count": len(report.get("findings", [])),
        },
        metadata={"engine": engine, "component": "engine"},
    )
    trace_info = {"attempted": True, "exported": bool(run_id), "run_id": run_id}
    report["langsmith_trace"] = trace_info
    state.add_trace("langsmith_trace", **trace_info)


def _attach_agentshield_runtime_guard(state: ComplianceState, *, input_guard: dict[str, Any]) -> None:
    """Attach AgentShield RuntimeGuard metadata without storing raw text."""

    output_guard: dict[str, Any] = {"allowed": True, "reasons": [], "mode": input_guard.get("mode", "unknown")}
    if state.final_report is not None:
        output_guard = inspect_output_text(json.dumps(state.final_report, ensure_ascii=False))
        state.final_report["agentshield_runtime_guard"] = {
            "status": guard_status(),
            "input": input_guard,
            "output": output_guard,
        }
    state.add_trace(
        "agentshield_runtime_guard",
        mode=input_guard.get("mode"),
        input_allowed=input_guard.get("allowed"),
        input_reasons=input_guard.get("reasons", []),
        output_allowed=output_guard.get("allowed"),
        output_reasons=output_guard.get("reasons", []),
    )


def _state_from_graph_output(input_text: str, output: dict[str, Any]) -> ComplianceState:
    """Convert LangGraph final state dict into `ComplianceState` for callers."""

    state = ComplianceState(
        input_text=input_text,
        redacted_text=output.get("redacted_text", output.get("redacted_content", "")),
        input_type=output.get("input_type", "advertisement"),
        pii_findings=output.get("pii_findings", []),
        retrieved_context=output.get("retrieved_context", []),
        user_cited_articles=output.get("user_cited_articles", []),
        board_opinions=output.get("board_opinions", {}),
        ceo_draft=output.get("ceo_draft", {}),
        atomic_claims=output.get("atomic_claims", []),
        verifier_results=output.get("verifier_results", []),
        routing_decision=output.get("routing_decision", {}),
        model_plan=output.get("model_plan", {}),
        llm_calls=output.get("llm_calls", []),
        cross_model_result=output.get("cross_model_result", {}),
        short_term_memory=output.get("short_term_memory", {}),
        long_term_memory=output.get("long_term_memory", []),
        rag_metadata=output.get("rag_metadata", {}),
        retry_count=output.get("retry_count", 0),
        final_report=output.get("final_report", {}),
        audit_log_id=output.get("audit_log_id", ""),
    )
    if not state.audit_log_id and state.final_report:
        state.audit_log_id = state.final_report.get("audit_log_id")
    return state
