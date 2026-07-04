"""LangGraph swap-in adapter (선택적, optional dependency).

기존 `ComplianceSentinel` deterministic orchestrator를 그대로 두고,
langgraph가 설치된 환경에서는 동일한 7-node 파이프라인을 StateGraph로 실행한다.

**행동 동등성 가드**: 어떤 백엔드를 쓰든 최종 `final_report` 출력이 동일해야 한다 — 본 모듈은
LangGraph node를 deterministic implementation의 thin wrapper로 정의한다.

설치:
    pip install "langgraph>=0.2"
    export USE_LANGGRAPH=1
    PYTHONPATH=src python3 -c "from compliance_sentinel.langgraph_adapter import build_graph; g=build_graph(); print(g)"

비활성 시:
    import 시점에 langgraph가 없으면 build_graph()는 RuntimeError. caller는 deterministic
    fallback (ComplianceSentinel)을 직접 사용한다.
"""
from __future__ import annotations

import os
from time import perf_counter
from typing import Any, Optional, TypedDict

try:  # Python 3.10 compatibility; typing.NotRequired is 3.11+
    from typing import NotRequired
except ImportError:  # pragma: no cover - exercised on Python 3.10 only
    from typing_extensions import NotRequired

from .agent_model_guard import ModelGuard
from .audit import AuditStore
from .board import run_compliance_board
from .budget_guard import from_env as budget_guard_from_env
from .citation_extractor import extract_explicit_citations
from .classification import classify_input
from .knowledge_base import LawKnowledgeBase
from .langgraph_runtime import compile_options, human_review_gate_metadata
from .llm_client import LLMClient
from .memory_rag import ComplianceMemoryRAG
from .models import ComplianceState
from .node_cost_tracker import aggregate_node_cost, instrument_node, report_from_state
from .pii import redact_pii
from .reporting import build_final_report
from .runtime import build_runtime_plan, llm_advisory_call, llm_advisory_calls_parallel, run_independent_validation
from .synthesizer import synthesize_opinion
from .verifier import apply_verifier_results, extract_atomic_claims, has_failures, verify_claims

try:  # pragma: no cover - optional dependency
    from langgraph.graph import END, START, StateGraph  # type: ignore
    _HAS_LANGGRAPH = True
except Exception:  # pragma: no cover - optional dependency
    _HAS_LANGGRAPH = False


class LangGraphComplianceState(TypedDict, total=False):
    """StateGraph schema for LangGraph 1.x.

    Using plain `dict` as the schema can drop the initial input payload in newer
    LangGraph versions. A TypedDict keeps the state contract explicit and makes
    the graph boundary visible for future AgentCompiler work.
    """

    input_text: str
    redacted_text: NotRequired[str]
    input_type: NotRequired[str]
    pii_findings: NotRequired[list]
    retrieved_context: NotRequired[list]
    user_cited_articles: NotRequired[list]
    board_opinions: NotRequired[dict]
    ceo_draft: NotRequired[dict]
    atomic_claims: NotRequired[list]
    verifier_results: NotRequired[list]
    routing_decision: NotRequired[dict]
    model_plan: NotRequired[dict]
    llm_calls: NotRequired[list]
    cross_model_result: NotRequired[dict]
    short_term_memory: NotRequired[dict]
    long_term_memory: NotRequired[list]
    rag_metadata: NotRequired[dict]
    # 입력 시 "수정 제안 생성" 토글. 약관 경로의 revision_suggestions는 정적(추가 비용 없음)이라
    # 그래프 내부 분기는 불필요 — verify→revise 자가교정 루프는 검증 정확성 메커니즘이므로 토글과 무관하게 유지.
    # 보고서 레벨 억제(revision_suggestions=[])는 engine._apply_revision_visibility가 통일 처리.
    include_revision: NotRequired[bool]
    retry_count: NotRequired[int]
    final_report: NotRequired[dict]
    audit_log_id: NotRequired[str]
    human_review_gate: NotRequired[dict]
    langgraph_runtime: NotRequired[dict]
    node_costs: NotRequired[list]  # 노드별 실측 cost (CostAttribution — node_cost_tracker)


def is_available() -> bool:
    """LangGraph가 설치되어 있고 USE_LANGGRAPH=1이면 True."""
    return _HAS_LANGGRAPH and os.environ.get("USE_LANGGRAPH", "0") == "1"


# --- 노드 함수들 (각 노드는 ComplianceState dict를 받고 partial update를 반환) ---


def _make_classify(_kb: LawKnowledgeBase):
    def node(state: dict) -> dict:
        return {"input_type": classify_input(state["input_text"])}
    return node


def _make_plan_models(llm_client: LLMClient):
    def node(state: dict) -> dict:
        decision, plan = build_runtime_plan(
            state["input_text"],
            deterministic_mode=llm_client.deterministic,
        )
        return {"routing_decision": decision, "model_plan": plan, "llm_calls": []}
    return node


def _append_llm_call(state: dict, llm_client: LLMClient, role: str, user_text: str, max_tokens: int = 512) -> list[dict]:
    calls = list(state.get("llm_calls") or [])
    calls.append(llm_advisory_call(
        model_plan=state.get("model_plan") or {},
        llm_client=llm_client,
        role=role,
        user_text=user_text,
        max_tokens=max_tokens,
    ))
    return calls


def _make_pii_guard(_kb: LawKnowledgeBase):
    def node(state: dict) -> dict:
        redacted, findings = redact_pii(state["input_text"])
        routing_decision = dict(state.get("routing_decision") or {})
        if routing_decision:
            routing_decision["raw_input"] = redacted
        return {"redacted_text": redacted, "pii_findings": findings, "routing_decision": routing_decision}
    return node


def _make_extract_citations(_kb: LawKnowledgeBase):
    def node(state: dict) -> dict:
        return {"user_cited_articles": extract_explicit_citations(state["redacted_text"])}
    return node


def _make_memory_recall(kb: LawKnowledgeBase):
    memory_rag = ComplianceMemoryRAG(kb=kb)

    def node(state: dict) -> dict:
        partial_state = ComplianceState(
            input_text=state["input_text"],
            redacted_text=state.get("redacted_text", ""),
            input_type=state.get("input_type", "unknown"),
        )
        memory_rag.recall(partial_state)
        return {
            "short_term_memory": partial_state.short_term_memory,
            "long_term_memory": partial_state.long_term_memory,
            "rag_metadata": partial_state.rag_metadata,
        }
    return node


def _make_retrieve(kb: LawKnowledgeBase):
    memory_rag = ComplianceMemoryRAG(kb=kb)

    def node(state: dict) -> dict:
        partial_state = ComplianceState(
            input_text=state["input_text"],
            redacted_text=state.get("redacted_text", ""),
            input_type=state.get("input_type", "unknown"),
            short_term_memory=state.get("short_term_memory", {}),
            long_term_memory=state.get("long_term_memory", []),
            rag_metadata=state.get("rag_metadata", {}),
        )
        bundle = memory_rag.retrieve_context(partial_state)
        return {"retrieved_context": bundle.law_articles, "rag_metadata": partial_state.rag_metadata}
    return node


def _make_board(_kb: LawKnowledgeBase, llm_client: LLMClient):
    def node(state: dict) -> dict:
        calls = list(state.get("llm_calls") or [])
        # 6인 보드 advisory 콜을 병렬 실행 (role order 보존 → 결과 동일, latency만 절감).
        # 각 role은 user_text만 입력받는 독립 호출이라 정확성 무손실 (서로 출력 미참조).
        # board_opinions 판정은 run_compliance_board(결정론)가 담당 — 본 콜은 llm_calls 텔레메트리.
        # 광고 경로 _make_advisory와 동일 패턴 (marketing_langgraph_adapter.py).
        roles = [
            "legal_counsel",
            "pipa_expert",
            "consumer_protection",
            "operational_risk",
            "business_practicality",
            "contrarian",
        ]
        calls.extend(llm_advisory_calls_parallel(
            model_plan=state.get("model_plan") or {},
            llm_client=llm_client,
            roles=roles,
            user_text=state["redacted_text"],
            max_tokens=512,
        ))
        return {
            "board_opinions": run_compliance_board(state["redacted_text"], state["retrieved_context"]),
            "llm_calls": calls,
        }
    return node


def _make_synthesize(_kb: LawKnowledgeBase, llm_client: LLMClient):
    def node(state: dict) -> dict:
        calls = _append_llm_call(state, llm_client, "ceo_synthesizer", state["redacted_text"], max_tokens=768)
        return {
            "ceo_draft": synthesize_opinion(
                state["redacted_text"],
                state["board_opinions"],
                user_citations=state.get("user_cited_articles") or [],
            ),
            "llm_calls": calls,
        }
    return node


def _make_verify(kb: LawKnowledgeBase, llm_client: LLMClient):
    def node(state: dict) -> dict:
        findings = state["ceo_draft"].get("findings", [])
        claims = extract_atomic_claims(findings)
        results = verify_claims(claims, kb)
        apply_verifier_results(findings, results)
        calls = _append_llm_call(state, llm_client, "verifier", state["redacted_text"], max_tokens=512)
        return {"atomic_claims": claims, "verifier_results": results, "llm_calls": calls}
    return node


def _make_revise(kb: LawKnowledgeBase):
    def node(state: dict) -> dict:
        findings = state["ceo_draft"].get("findings", [])
        for finding in findings:
            if finding.verifier_status in {"FAIL", "PARTIAL"}:
                article = kb.get_article(finding.law_name, finding.article_no)
                if article and finding.citation_text != article.text:
                    finding.citation_text = article.text
        return {"retry_count": state.get("retry_count", 0) + 1}
    return node


def _make_independent_validation(llm_client: LLMClient):
    def node(state: dict) -> dict:
        cross_result = run_independent_validation(
            model_plan=state.get("model_plan") or {},
            ceo_draft=state.get("ceo_draft") or {},
            verifier_results=state.get("verifier_results") or [],
            llm_client=llm_client,
        )
        calls = list(state.get("llm_calls") or [])
        should_add_extra_validation_advisory = os.environ.get("CS_EXTRA_VALIDATION_ADVISORY") == "1"
        if cross_result.get("level") != "NONE" and (not cross_result.get("enabled") or should_add_extra_validation_advisory):
            for role in ["adversarial_critic", "independent_validator"]:
                calls.append(llm_advisory_call(
                    model_plan=state.get("model_plan") or {},
                    llm_client=llm_client,
                    role=role,
                    user_text=state["redacted_text"],
                    max_tokens=512,
                ))
        return {"cross_model_result": cross_result, "llm_calls": calls}
    return node


def _human_review_gate(state: dict) -> dict:
    reasons: list[str] = []
    risk_level = str((state.get("ceo_draft") or {}).get("risk_level") or "LOW")
    if risk_level in {"HIGH", "CRITICAL"}:
        reasons.append(f"risk_level={risk_level}")
    if has_failures(state.get("verifier_results", [])):
        reasons.append("verifier_failure")
    findings = (state.get("ceo_draft") or {}).get("findings", [])
    if any(getattr(finding, "verifier_status", "") == "PARTIAL" for finding in findings):
        reasons.append("partial_verifier_result")
    cross_confidence = (state.get("cross_model_result") or {}).get("cross_model_confidence")
    if cross_confidence in {"FAILED", "PARTIAL", "FEEDBACK"}:
        reasons.append(f"cross_model_confidence={cross_confidence}")
    required = bool(reasons)
    return {"human_review_gate": human_review_gate_metadata(required=required, reasons=reasons)}


def _make_final_report(_kb: LawKnowledgeBase, audit_store: AuditStore):
    def node(state: dict) -> dict:
        _final_t0 = perf_counter()
        # ComplianceState 인스턴스로 변환 후 reporting → audit
        partial_state = ComplianceState(
            input_text=state["input_text"],
            redacted_text=state.get("redacted_text", ""),
            input_type=state.get("input_type", "unknown"),
            pii_findings=state.get("pii_findings", []),
            retrieved_context=state.get("retrieved_context", []),
            user_cited_articles=state.get("user_cited_articles", []),
            board_opinions=state.get("board_opinions", {}),
            ceo_draft=state.get("ceo_draft", {}),
            atomic_claims=state.get("atomic_claims", []),
            verifier_results=state.get("verifier_results", []),
            routing_decision=state.get("routing_decision", {}),
            model_plan=state.get("model_plan", {}),
            llm_calls=state.get("llm_calls", []),
            cross_model_result=state.get("cross_model_result", {}),
            short_term_memory=state.get("short_term_memory", {}),
            long_term_memory=state.get("long_term_memory", []),
            rag_metadata=state.get("rag_metadata", {}),
            retry_count=state.get("retry_count", 0),
        )
        partial_state.final_report = build_final_report(partial_state)
        if state.get("human_review_gate"):
            partial_state.final_report["human_review_gate"] = state["human_review_gate"]
            if state["human_review_gate"].get("required"):
                partial_state.final_report["human_review_needed"] = True
                partial_state.final_report["status"] = "HUMAN_REVIEW_REQUIRED"
        ComplianceMemoryRAG(kb=_kb).capture_outcome(partial_state)
        partial_state.audit_log_id = audit_store.write(partial_state)
        partial_state.final_report["audit_log_id"] = partial_state.audit_log_id
        # 노드별 실측 cost 집계 (final_report는 LLM 미호출 → latency만) → per_node_cost.
        _final_latency = (perf_counter() - _final_t0) * 1000
        _all_costs = list(state.get("node_costs") or [])
        _all_costs.append(aggregate_node_cost("final_report", [], _final_latency).as_dict())
        partial_state.final_report["per_node_cost"] = report_from_state(_all_costs).as_dict()
        return {"final_report": partial_state.final_report, "audit_log_id": partial_state.audit_log_id, "node_costs": _all_costs}
    return node


def _verifier_branch(state: dict) -> str:
    """verify 노드 종료 후 분기.

    - 3회 retry 초과 또는 verify 통과 → final_report로
    - 그 외 (FAIL 또는 보정 가능 PARTIAL) → revise로
    """
    if state.get("retry_count", 0) >= 3:
        return "final_report"
    findings = state["ceo_draft"].get("findings", [])
    if has_failures(state.get("verifier_results", [])):
        return "revise"
    # PARTIAL 보정 가능 여부
    from .workflow import _has_revisable_partial  # local import to avoid cycle
    # kb는 클로저로 가져올 수 없으므로 단순화: PARTIAL 1건이라도 있으면 revise 시도
    if any(f.verifier_status == "PARTIAL" for f in findings):
        return "revise"
    return "final_report"


def _route_after_guard(state: dict) -> str:
    """Conditional-edge router for the AgentShield graph guard: 'blocked' when the
    wrapped entry node flagged the input, else 'continue' to the normal pipeline."""
    return "blocked" if isinstance(state, dict) and state.get("blocked") else "continue"


def _make_guard_block_node():
    """Terminal node for guard-blocked input: emits a schema-valid REJECTED final
    report and stops the graph (paired with a conditional edge → END)."""
    def node(state: dict) -> dict:
        from .report_schema import build_blocked_final_report

        reasons = state.get("guard_reasons") if isinstance(state, dict) else None
        return {"final_report": build_blocked_final_report(reasons)}
    return node


def build_graph(
    *,
    kb: Optional[LawKnowledgeBase] = None,
    audit_store: Optional[AuditStore] = None,
    enable_checkpoint: Optional[bool] = None,
    checkpointer: Any = None,
    interrupt_before: list[str] | None = None,
) -> Any:
    """LangGraph StateGraph를 빌드해 반환.

    langgraph가 설치돼 있지 않거나 USE_LANGGRAPH≠1이면 RuntimeError를 던진다.
    caller는 deterministic ComplianceSentinel로 fallback한다.
    """
    if not _HAS_LANGGRAPH:
        raise RuntimeError(
            "langgraph not installed. Run `pip install \"langgraph>=0.2\"` and set USE_LANGGRAPH=1."
        )
    kb = kb or LawKnowledgeBase.from_json()
    audit_store = audit_store or AuditStore()
    llm_client = LLMClient(budget_guard=budget_guard_from_env(), model_guard=ModelGuard.from_env())

    g = StateGraph(LangGraphComplianceState)  # type: ignore
    # AgentShield graph guard (opt-in): inspect classify_input's input_text for
    # prompt-injection before classification. When blocked, a conditional edge
    # routes to a terminal REJECTED node so the graph stops (F2 fix).
    # Offline-safe: classify node unchanged + no extra wiring when disabled.
    _graph_guard = os.environ.get("CS_ENABLE_AGENTSHIELD_GRAPH_GUARD") == "1"
    _classify_node = _make_classify(kb)
    if _graph_guard:
        from .agent_shield_bridge import wrap_langgraph_node

        _classify_node = wrap_langgraph_node(_classify_node, input_key="input_text")
    # 노드별 실측 cost 계측: final_report 제외 모든 노드를 instrument_node 래핑 (CostAttribution).
    g.add_node("classify_input", instrument_node("classify_input", _classify_node, llm_client))
    if _graph_guard:
        g.add_node("agentshield_block", _make_guard_block_node())
    g.add_node("plan_models", instrument_node("plan_models", _make_plan_models(llm_client), llm_client))
    g.add_node("pii_guard", instrument_node("pii_guard", _make_pii_guard(kb), llm_client))
    g.add_node("extract_user_citations", instrument_node("extract_user_citations", _make_extract_citations(kb), llm_client))
    g.add_node("memory_recall", instrument_node("memory_recall", _make_memory_recall(kb), llm_client))
    g.add_node("retrieve_context", instrument_node("retrieve_context", _make_retrieve(kb), llm_client))
    g.add_node("board_review", instrument_node("board_review", _make_board(kb, llm_client), llm_client))
    g.add_node("synthesize", instrument_node("synthesize", _make_synthesize(kb, llm_client), llm_client))
    g.add_node("verify_atomic_claims", instrument_node("verify_atomic_claims", _make_verify(kb, llm_client), llm_client))
    g.add_node("revise", instrument_node("revise", _make_revise(kb), llm_client))
    g.add_node("independent_validation", instrument_node("independent_validation", _make_independent_validation(llm_client), llm_client))
    g.add_node("human_review_gate", instrument_node("human_review_gate", _human_review_gate, llm_client))
    g.add_node("final_report", _make_final_report(kb, audit_store))  # 자체 per_node_cost 생성 (래핑 제외)

    g.add_edge(START, "classify_input")
    if _graph_guard:
        # blocked → terminal REJECTED node → END; clean → normal pipeline.
        g.add_conditional_edges("classify_input", _route_after_guard, {"blocked": "agentshield_block", "continue": "plan_models"})
        g.add_edge("agentshield_block", END)
    else:
        g.add_edge("classify_input", "plan_models")
    g.add_edge("plan_models", "pii_guard")
    g.add_edge("pii_guard", "extract_user_citations")
    g.add_edge("extract_user_citations", "memory_recall")
    g.add_edge("memory_recall", "retrieve_context")
    g.add_edge("retrieve_context", "board_review")
    g.add_edge("board_review", "synthesize")
    g.add_edge("synthesize", "verify_atomic_claims")
    g.add_conditional_edges(
        "verify_atomic_claims",
        _verifier_branch,
        {"revise": "revise", "final_report": "independent_validation"},
    )
    g.add_edge("revise", "verify_atomic_claims")
    g.add_edge("independent_validation", "human_review_gate")
    g.add_edge("human_review_gate", "final_report")
    g.add_edge("final_report", END)
    kwargs, _runtime_metadata = compile_options(
        enable_checkpoint=enable_checkpoint,
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
    )
    return g.compile(**kwargs)
