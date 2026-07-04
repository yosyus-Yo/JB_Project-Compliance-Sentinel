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
from .budget_guard import from_env as budget_guard_from_env
from .langgraph_runtime import compile_options, human_review_gate_metadata
from .llm_client import LLMClient
from .marketing_reviewer import (
    decide_approval,
    generate_marketing_rewrite,
    generate_revisions,
    llm_detect_risk_findings,
    review_marketing_content,
)
from .marketing_workflow import build_marketing_report
from .memory_rag import ComplianceMemoryRAG
from .models import ComplianceState
from .node_cost_tracker import aggregate_node_cost, report_from_state
from .pii import redact_pii
from .runtime import _BOARD_ADVISORY_ROLES, build_runtime_plan, llm_advisory_call, llm_advisory_calls_parallel, run_independent_validation

try:  # pragma: no cover
    from langgraph.graph import END, START, StateGraph  # type: ignore
    _HAS_LANGGRAPH = True
except Exception:  # pragma: no cover
    _HAS_LANGGRAPH = False


class MarketingGraphState(TypedDict, total=False):
    input_text: str
    redacted_content: str
    language: str
    channel: str
    content_type: str
    product_type: str
    findings: list
    revision_suggestions: list
    approval_status: str
    workflow_exports: dict
    evaluation_metadata: dict
    routing_decision: dict
    model_plan: dict
    llm_calls: list
    ceo_draft: dict
    cross_model_result: dict
    short_term_memory: dict
    long_term_memory: list
    rag_metadata: dict
    final_report: dict
    audit_log_id: NotRequired[str]
    human_review_gate: NotRequired[dict]
    langgraph_runtime: NotRequired[dict]
    # 입력 시 "수정 제안 생성" 토글 (체크 시 True). False면 심의만 수행 — revise 루프 + rewrite 미생성.
    include_revision: NotRequired[bool]
    # 자가교정 revise loop (방식 C 하이브리드) — docs/marketing-revise-loop-design.md
    retry_count: NotRequired[int]
    revised_text: NotRequired[str]
    revised_marketing_rewrite: NotRequired[dict]
    revise_trace: NotRequired[list]
    delta_findings: NotRequired[list]  # 수정안 신규 위험 1차 스캔 결과 (delta_screen → revise_branch)
    node_costs: NotRequired[list]  # 노드별 실측 cost (CostAttribution — node_cost_tracker)


def is_available() -> bool:
    return _HAS_LANGGRAPH and os.environ.get("USE_LANGGRAPH", "0") == "1"


def _instrument(node_id: str, fn, llm_client: LLMClient):
    """노드 실행을 감싸 실측 latency + llm_client.call_log 토큰 델타를 node_costs에 누적.

    final_report 노드는 제외(자체적으로 per_node_cost report 생성 — 본 래퍼로 감싸면 이중 집계).
    LLM 미호출 노드도 latency만 기록되어 그래프 구조 완전성 보존.
    """
    def wrapped(state: dict) -> dict:
        before = len(llm_client.call_log)
        t0 = perf_counter()
        result = fn(state) or {}
        latency_ms = (perf_counter() - t0) * 1000
        nc = aggregate_node_cost(node_id, llm_client.call_log[before:], latency_ms)
        costs = list(state.get("node_costs") or [])
        costs.append(nc.as_dict())
        result = dict(result)
        result["node_costs"] = costs
        return result
    return wrapped


def _make_intake(llm_client: LLMClient):
    def node(state: dict) -> dict:
        redacted, _ = redact_pii(state["input_text"])
        decision, plan = build_runtime_plan(state["input_text"], deterministic_mode=llm_client.deterministic)
        decision["raw_input"] = redacted
        return {"redacted_content": redacted, "routing_decision": decision, "model_plan": plan, "llm_calls": []}
    return node


def _understand(state: dict) -> dict:
    review = review_marketing_content(state["redacted_content"])
    return {
        "language": review.language,
        "channel": review.channel,
        "content_type": review.content_type,
        "product_type": review.product_type,
        "findings": review.findings,
        "revision_suggestions": review.revision_suggestions,
        "approval_status": review.approval_status,
        "workflow_exports": review.workflow_exports,
        "evaluation_metadata": review.evaluation_metadata,
    }


def _marketing_llm_risk_scan(redacted_content: str, findings: list, *, language: str, channel: str, product_type: str) -> list:
    """원본 콘텐츠 LLM 맥락 스캔 (방안 C) — 정적 룰이 놓치는 미묘·맥락 위반 보강.

    별도 헬퍼로 추출: 과거엔 _memory_review 안에서 순차 실행(→step3 병목)했으나,
    보드 advisory와 **독립 호출**(둘 다 redacted_content만 입력, 서로 출력 미참조)이라
    _make_advisory에서 보드와 병렬 실행한다. deterministic/실패 시 [] 반환(안전).
    """
    try:
        from .budget_guard import from_env as budget_guard_from_env
        from .llm_client import LLMClient
        from .marketing_reviewer import llm_detect_risk_findings

        scan_client = LLMClient(budget_guard=budget_guard_from_env())
        return llm_detect_risk_findings(
            redacted_content,
            findings,
            language=language,
            channel=channel,
            product_type=product_type,
            llm_client=scan_client,
        ) or []
    except Exception:  # noqa: BLE001 — LLM 스캔 실패해도 심의 결과 보존
        return []


def _memory_review(state: dict) -> dict:
    from .marketing_models import MarketingReview
    from .marketing_workflow import _apply_document_rag_marketing_rules, _apply_memory_marketing_rules

    comp_state = ComplianceState(
        input_text=state["input_text"],
        redacted_text=state["redacted_content"],
        input_type="advertisement",
    )
    memory_rag = ComplianceMemoryRAG()
    memory_rag.recall(comp_state, query_text=state["redacted_content"])
    bundle = memory_rag.retrieve_context(comp_state, query_text=state["redacted_content"])
    comp_state.retrieved_context = bundle.law_articles
    review = MarketingReview(
        raw_content=state["input_text"],
        redacted_content=state["redacted_content"],
        language=state["language"],
        channel=state["channel"],
        content_type=state["content_type"],
        product_type=state["product_type"],
        findings=state.get("findings", []),
        revision_suggestions=state.get("revision_suggestions", []),
        approval_status=state.get("approval_status", "APPROVED"),
        workflow_exports=state.get("workflow_exports", {}),
        evaluation_metadata=state.get("evaluation_metadata", {}),
    )
    added = _apply_memory_marketing_rules(review, comp_state)
    document_added = _apply_document_rag_marketing_rules(review, comp_state)
    # LLM 위험스캔(방안 C)은 _make_advisory로 이동해 보드와 **병렬** 실행(step3 병목 해소).
    # 여기선 RAG+룰 findings만 확정. 최종 approval/revision은 스캔 병합 후 _make_advisory가 재계산.
    if added or document_added:
        review.revision_suggestions = generate_revisions(review.redacted_content, review.findings, review.product_type)
        review.approval_status = decide_approval(review.findings, review.language)
        review.evaluation_metadata["memory_rule_findings"] = added
        review.evaluation_metadata["document_rag_rule_findings"] = document_added
    comp_state.rag_metadata.update({
        "rag_pipeline": "marketing_brain_memory_rules_plus_document_rag",
        "memory_hit_count": len(comp_state.long_term_memory),
        "memory_rule_findings": added,
        "document_rag_rule_findings": document_added,
    })
    return {
        "findings": review.findings,
        "revision_suggestions": review.revision_suggestions,
        "approval_status": review.approval_status,
        "evaluation_metadata": review.evaluation_metadata,
        "short_term_memory": comp_state.short_term_memory,
        "long_term_memory": comp_state.long_term_memory,
        "rag_metadata": comp_state.rag_metadata,
    }


def _make_advisory(llm_client: LLMClient):
    def node(state: dict) -> dict:
        from concurrent.futures import ThreadPoolExecutor

        calls = list(state.get("llm_calls") or [])
        # 6인 보드 전원 advisory + CEO/검증 콜을 병렬 실행 (role order 보존 → 결과 동일, latency만 절감).
        # 각 role은 user_text만 입력받는 독립 호출이라 정확성 무손실 (서로 출력 미참조).
        # 6인 전원(legal/pipa/consumer/operational/business/contrarian) LLM advisory — _BOARD_ADVISORY_ROLES single source.
        # 단 board 판정(opinion/risk)은 run_compliance_board(deterministic) 담당 — 본 콜은 텔레메트리/리스크신호.
        roles = [*_BOARD_ADVISORY_ROLES, "ceo_synthesizer", "verifier"]
        # LLM 위험스캔(방안 C)을 보드 batch와 **동시 실행** — 둘 다 redacted_content만 입력하는
        # 독립 호출이라 병렬화해도 정확성 무손실, step3 순차 병목(~11초) 제거.
        with ThreadPoolExecutor(max_workers=2) as ex:
            board_future = ex.submit(
                llm_advisory_calls_parallel,
                model_plan=state.get("model_plan") or {},
                llm_client=llm_client,
                roles=roles,
                user_text=state["redacted_content"],
            )
            scan_future = ex.submit(
                _marketing_llm_risk_scan,
                state["redacted_content"],
                list(state.get("findings") or []),
                language=state["language"],
                channel=state["channel"],
                product_type=state["product_type"],
            )
            calls.extend(board_future.result())
            scan_findings = scan_future.result()
        result: dict = {"llm_calls": calls}
        # 위험스캔 findings 병합 후 approval/revision 재계산 (기존 _memory_review 순차 로직과 동일 결과).
        if scan_findings:
            findings = list(state.get("findings") or []) + scan_findings
            meta = dict(state.get("evaluation_metadata") or {})
            meta["llm_risk_scan_findings"] = len(scan_findings)
            result.update({
                "findings": findings,
                "revision_suggestions": generate_revisions(state["redacted_content"], findings, state["product_type"]),
                "approval_status": decide_approval(findings, state["language"]),
                "evaluation_metadata": meta,
            })
        return result
    return node


def _synthesize(state: dict) -> dict:
    from .marketing_workflow import _ceo_draft_from_review
    from .marketing_models import MarketingReview

    review = MarketingReview(
        raw_content=state["input_text"],
        redacted_content=state["redacted_content"],
        language=state["language"],
        channel=state["channel"],
        content_type=state["content_type"],
        product_type=state["product_type"],
        findings=state.get("findings", []),
        revision_suggestions=state.get("revision_suggestions", []),
        approval_status=state.get("approval_status", "APPROVED"),
        workflow_exports=state.get("workflow_exports", {}),
        evaluation_metadata=state.get("evaluation_metadata", {}),
    )
    return {"ceo_draft": _ceo_draft_from_review(review)}


def _make_validate(llm_client: LLMClient):
    def node(state: dict) -> dict:
        cross = run_independent_validation(
            model_plan=state.get("model_plan") or {},
            ceo_draft=state.get("ceo_draft") or {},
            verifier_results=[],
            llm_client=llm_client,
        )
        calls = list(state.get("llm_calls") or [])
        cross_level = cross.get("level") or "NONE"
        should_add_extra_validation_advisory = os.environ.get("CS_EXTRA_VALIDATION_ADVISORY") == "1"
        if state.get("findings") and cross_level != "NONE" and (not cross.get("enabled") or should_add_extra_validation_advisory):
            # 추가 검증 2콜도 병렬 (독립 호출 — 정확성 무손실).
            calls.extend(llm_advisory_calls_parallel(
                model_plan=state.get("model_plan") or {},
                llm_client=llm_client,
                roles=["adversarial_critic", "independent_validator"],
                user_text=state["redacted_content"],
            ))
        return {"cross_model_result": cross, "llm_calls": calls}
    return node


def _human_review_gate(state: dict) -> dict:
    reasons: list[str] = []
    approval_status = str(state.get("approval_status") or "")
    if approval_status in {"HUMAN_REVIEW_REQUIRED", "REJECTED"}:
        reasons.append(f"approval_status={approval_status}")
    if state.get("findings"):
        severe = [getattr(item, "severity", "") for item in state.get("findings", [])]
        if any(level in {"HIGH", "CRITICAL"} for level in severe):
            reasons.append("high_or_critical_marketing_finding")
    cross_confidence = (state.get("cross_model_result") or {}).get("cross_model_confidence")
    if cross_confidence in {"FAILED", "PARTIAL", "FEEDBACK"}:
        reasons.append(f"cross_model_confidence={cross_confidence}")
    required = bool(reasons)
    return {"human_review_gate": human_review_gate_metadata(required=required, reasons=reasons)}


def _compute_marketing_rewrite(review, llm_client: LLMClient, comp_state) -> Optional[dict]:
    """AI 수정 광고 원고(rewrite) 생성 래퍼.

    T1: rewrite_loop 노드(T2)와 final_report 노드가 공유하는 단일 진입점.
    ad_copy_proposer 역할로 generate_marketing_rewrite 호출. 실패 시 trace 기록 후 None
    (심의 결과 불변 — rewrite는 보조 제안 레이어). deterministic 모드면 함수 내부에서 None 반환.
    """
    try:
        return generate_marketing_rewrite(
            review.redacted_content,
            review.findings,
            product_type=review.product_type,
            channel=review.channel,
            language=review.language,
            llm_client=llm_client,
            role="ad_copy_proposer",
        )
    except Exception as exc:  # noqa: BLE001 — rewrite 실패해도 심의 결과 보존
        comp_state.add_trace("marketing_rewrite_failed", reason=f"{type(exc).__name__}: {exc}")
        return None


def _marketing_review_from_state(state: dict):
    """state → MarketingReview 빌더 (T2 revise 노드 전용 헬퍼).

    기존 _memory_review/_synthesize/_make_final의 inline 빌더와 동일 패턴이나,
    그 3곳은 T1 "기존 동작 보존" 원칙으로 미변경. 신규 노드만 본 헬퍼 사용.
    """
    from .marketing_models import MarketingReview

    return MarketingReview(
        raw_content=state["input_text"],
        redacted_content=state["redacted_content"],
        language=state["language"],
        channel=state["channel"],
        content_type=state["content_type"],
        product_type=state["product_type"],
        findings=state.get("findings", []),
        revision_suggestions=state.get("revision_suggestions", []),
        approval_status=state.get("approval_status", "APPROVED"),
        workflow_exports=state.get("workflow_exports", {}),
        evaluation_metadata=state.get("evaluation_metadata", {}),
    )


def _make_rewrite_loop(llm_client: LLMClient):
    """수정안 생성 루프 노드 (방식 C). retry_count+1, 수정안을 state에 저장.

    T2: generate_marketing_rewrite(=_compute_marketing_rewrite)로 수정 원고 생성.
    - 성공 → revised_text(원고) + revised_marketing_rewrite(dict) 저장
    - deterministic/실패 → 수정안 미생성. retry_count만 증가 (백엣지에서 retry≥3 또는
      delta [] 로 탈출 → 무한루프 없음, 설계 §7 안전 원칙).
    심의 결과(findings/approval)는 절대 변경하지 않음 — rewrite는 보조 제안 레이어.
    """
    def node(state: dict) -> dict:
        review = _marketing_review_from_state(state)
        comp_state = ComplianceState(
            input_text=state["input_text"],
            redacted_text=state["redacted_content"],
            input_type="advertisement",
        )
        retry_count = int(state.get("retry_count", 0)) + 1
        rewrite = _compute_marketing_rewrite(review, llm_client, comp_state)
        trace = list(state.get("revise_trace") or [])
        if not rewrite or not rewrite.get("rewritten"):
            trace.append({"attempt": retry_count, "rewritten": False, "removed_terms": []})
            return {"retry_count": retry_count, "revise_trace": trace}
        trace.append({
            "attempt": retry_count,
            "rewritten": True,
            "removed_terms": rewrite.get("removed_terms") or [],
        })
        return {
            "retry_count": retry_count,
            "revised_text": rewrite["rewritten"],
            "revised_marketing_rewrite": rewrite,
            "revise_trace": trace,
        }
    return node


def _make_delta_screen(llm_client: LLMClient):
    """수정안 신규 위험 1차 스캔 노드 (방식 C Delta — 풀 6인 보드 재호출 대체).

    T2: llm_detect_risk_findings로 수정 원고에 남은/새로 생긴 위험표현만 1 LLM 스캔.
    - revised_text 부재(rewrite 미생성) → [] (신규 위험 없음으로 간주 → revise_branch 통과)
    - deterministic 모드 → llm_detect_risk_findings 내부에서 [] 반환 (안전 fallback)
    원본 findings는 existing_findings로 전달 → 이미 flagged된 표현은 delta에서 제외(중복 차단).
    """
    def node(state: dict) -> dict:
        revised_text = state.get("revised_text")
        if not revised_text:
            return {"delta_findings": []}
        delta = llm_detect_risk_findings(
            revised_text,
            state.get("findings", []),
            language=state["language"],
            channel=state["channel"],
            product_type=state["product_type"],
            llm_client=llm_client,
        )
        return {"delta_findings": delta}
    return node


def _make_final(audit_store: AuditStore, llm_client: LLMClient):
    def node(state: dict) -> dict:
        from .marketing_models import MarketingReview
        from .marketing_workflow import build_marketing_report

        _final_calls_before = len(llm_client.call_log)
        _final_t0 = perf_counter()

        review = MarketingReview(
            raw_content=state["input_text"],
            redacted_content=state["redacted_content"],
            language=state["language"],
            channel=state["channel"],
            content_type=state["content_type"],
            product_type=state["product_type"],
            findings=state.get("findings", []),
            revision_suggestions=state.get("revision_suggestions", []),
            approval_status=state.get("approval_status", "APPROVED"),
            workflow_exports=state.get("workflow_exports", {}),
            evaluation_metadata=state.get("evaluation_metadata", {}),
        )
        comp_state = ComplianceState(
            input_text=state["input_text"],
            redacted_text=state["redacted_content"],
            input_type="advertisement",
            ceo_draft=state.get("ceo_draft", {}),
            routing_decision=state.get("routing_decision", {}),
            model_plan=state.get("model_plan", {}),
            llm_calls=state.get("llm_calls", []),
            cross_model_result=state.get("cross_model_result", {}),
            short_term_memory=state.get("short_term_memory", {}),
            long_term_memory=state.get("long_term_memory", []),
            rag_metadata=state.get("rag_metadata", {}),
        )
        comp_state.final_report = build_marketing_report(review, comp_state)
        if state.get("human_review_gate"):
            comp_state.final_report["human_review_gate"] = state["human_review_gate"]
            if state["human_review_gate"].get("required"):
                comp_state.final_report["human_review_needed"] = True
                if comp_state.final_report.get("approval_status") == "APPROVED":
                    comp_state.final_report["approval_status"] = "HUMAN_REVIEW_REQUIRED"
        comp_state.human_review_needed = comp_state.final_report["human_review_needed"]
        # AI 수정 광고 원고(rewrite). 심의 결과(approval/risk/findings)는 불변 — 보조 제안 레이어.
        # 수정 제안 토글(include_revision=False, 기본값) → rewrite 미생성 (심의만 수행). 보고서 레벨
        # revision_suggestions 억제 + revision_included 마커는 engine._apply_revision_visibility가 통일 처리.
        # T1: state에 통과 수정안(revise loop 경유)이 있으면 우선 사용, 없으면 helper 호출(직선 경로).
        include_revision = bool(state.get("include_revision", False))
        marketing_rewrite = None
        if include_revision:
            marketing_rewrite = state.get("revised_marketing_rewrite")
            if marketing_rewrite is None:
                marketing_rewrite = _compute_marketing_rewrite(review, llm_client, comp_state)
            if marketing_rewrite is not None:
                comp_state.final_report["marketing_rewrite"] = marketing_rewrite
                comp_state.add_trace(
                    "marketing_rewrite",
                    generated=bool(marketing_rewrite.get("rewritten")),
                    removed_count=len(marketing_rewrite.get("removed_terms") or []),
                    proposer_role="ad_copy_proposer",
                )
        # T4: 자가교정 루프 audit 추적 — revise_trace를 보고서/감사로그에 노출 (PDF F-04 추적성).
        revise_trace = state.get("revise_trace")
        if revise_trace:
            comp_state.final_report["revise_trace"] = revise_trace
            comp_state.add_trace(
                "revise_loop",
                attempts=len(revise_trace),
                final_retry_count=int(state.get("retry_count", 0)),
                converged=marketing_rewrite is not None,
            )
        ComplianceMemoryRAG().capture_outcome(comp_state)
        audit_id = audit_store.write(comp_state)
        comp_state.final_report["audit_log_id"] = audit_id
        comp_state.audit_log_id = audit_id
        # LangGraph 경로 전송 누락 fix: deterministic(_analyze_inner)과 동일하게 audit 확정 후
        # _exports_with_audit를 호출해 실제 워크플로우 전송(Slack publish_slack_payload)을 수행한다.
        # 기존엔 _understand가 만든 review.workflow_exports(build_slack_payload만, 전송 X)를 통과시켜
        # delivery_status가 누락되고 Slack 알림이 가지 않았다.
        from .marketing_workflow import _exports_with_audit
        _board_dict = comp_state.final_report.get("board_diagnostics")
        comp_state.final_report["workflow_exports"] = _exports_with_audit(
            review, audit_id, comp_state.final_report.get("risk_level", "UNKNOWN"),
            board_diagnostics=_board_dict,
        )
        _publish_plan = (comp_state.final_report["workflow_exports"].get("slack") or {}).get("publish_plan", {})
        comp_state.final_report["workflow_publish_plan"] = _publish_plan
        # 노드별 실측 cost 집계 (final_report 자신의 rewrite 호출 포함) → per_node_cost.
        _final_latency = (perf_counter() - _final_t0) * 1000
        _final_self = aggregate_node_cost("final_report", llm_client.call_log[_final_calls_before:], _final_latency)
        _all_costs = list(state.get("node_costs") or [])
        _all_costs.append(_final_self.as_dict())
        comp_state.final_report["per_node_cost"] = report_from_state(_all_costs).as_dict()
        return {"final_report": comp_state.final_report, "audit_log_id": audit_id, "node_costs": _all_costs}
    return node


_SEVERE_LEVELS = {"HIGH", "CRITICAL"}


def _has_severe_finding(findings) -> bool:
    """findings에 HIGH/CRITICAL severity가 하나라도 있으면 True (_human_review_gate와 동일 판정)."""
    return any(getattr(item, "severity", "") in _SEVERE_LEVELS for item in (findings or []))


def _revise_gate(state: dict) -> str:
    """synthesize 직후 심각도 판정 (방식 C 진입 분기).

    심각(REJECTED 또는 HIGH/CRITICAL finding) + retry 한도 미달 → revise 루프 진입.
    경미 또는 한도 도달 → 기존 직선(independent_validation)으로.
    첫 진입 시 retry_count=0이므로 심각하면 항상 revise. 한도는 _revise_branch가 강제.

    수정 제안 토글(include_revision=False, 기본값) → 항상 validate 직선. 심의만 수행하고
    수정 원고/revise 루프는 진입하지 않음 (비용 절감 + "심의만" UX). 심의 결과(findings/approval)는 불변.
    """
    if not bool(state.get("include_revision", False)):
        return "validate"
    severe = str(state.get("approval_status") or "") == "REJECTED" or _has_severe_finding(state.get("findings"))
    if not severe:
        return "validate"
    if int(state.get("retry_count", 0)) >= 3:
        return "validate"  # 이미 한도 — 직선 통과 후 human_review_gate가 HITL 처리
    return "revise"


def _revise_branch(state: dict) -> str:
    """delta_screen 직후 분기 (방식 C 종료 조건).

    - 신규 HIGH/CRITICAL 위험 없음 → independent_validation 통과 (수정안 채택)
    - 신규 위험 有 + retry<3 → rewrite_loop 백엣지 (재교정)
    - retry≥3 → human_review_gate 강제 (HUMAN_REVIEW_REQUIRED, PDF F-04 "초과 시 HITL")
    수정안 미생성(deterministic/실패) 시 delta_findings=[] → 신규 위험 없음 → 통과 (무한루프 없음).
    """
    if not _has_severe_finding(state.get("delta_findings")):
        return "validate"
    if int(state.get("retry_count", 0)) >= 3:
        return "human"
    return "revise"


def _route_after_guard(state: dict) -> str:
    """Conditional-edge router for the AgentShield graph guard: 'blocked' when the
    wrapped intake node flagged the input, else 'continue' to the pipeline."""
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
    audit_store: Optional[AuditStore] = None,
    enable_checkpoint: Optional[bool] = None,
    checkpointer: Any = None,
    interrupt_before: list[str] | None = None,
) -> Any:
    if not _HAS_LANGGRAPH:
        raise RuntimeError("langgraph not installed")
    audit_store = audit_store or AuditStore()
    llm_client = LLMClient(budget_guard=budget_guard_from_env(), model_guard=ModelGuard.from_env())
    g = StateGraph(MarketingGraphState)  # type: ignore
    # AgentShield graph guard (opt-in): inspect content_intake's input_text for
    # prompt-injection before intake. When blocked, a conditional edge routes to a
    # terminal REJECTED node so the graph stops (F2 fix). Offline-safe when disabled.
    _graph_guard = os.environ.get("CS_ENABLE_AGENTSHIELD_GRAPH_GUARD") == "1"
    _intake_node = _make_intake(llm_client)
    if _graph_guard:
        from .agent_shield_bridge import wrap_langgraph_node

        _intake_node = wrap_langgraph_node(_intake_node, input_key="input_text")
    # 노드별 실측 cost 계측: final_report 제외 모든 노드를 _instrument 래핑 (CostAttribution).
    g.add_node("content_intake", _instrument("content_intake", _intake_node, llm_client))
    if _graph_guard:
        g.add_node("agentshield_block", _make_guard_block_node())
    g.add_node("understand_content", _instrument("understand_content", _understand, llm_client))
    g.add_node("memory_review", _instrument("memory_review", _memory_review, llm_client))
    g.add_node("llm_advisory_board", _instrument("llm_advisory_board", _make_advisory(llm_client), llm_client))
    g.add_node("synthesize", _instrument("synthesize", _synthesize, llm_client))
    # 자가교정 revise loop 노드 (방식 C 하이브리드) — T2/T3
    g.add_node("rewrite_loop", _instrument("rewrite_loop", _make_rewrite_loop(llm_client), llm_client))
    g.add_node("delta_screen", _instrument("delta_screen", _make_delta_screen(llm_client), llm_client))
    g.add_node("independent_validation", _instrument("independent_validation", _make_validate(llm_client), llm_client))
    g.add_node("human_review_gate", _instrument("human_review_gate", _human_review_gate, llm_client))
    g.add_node("final_report", _make_final(audit_store, llm_client))  # 자체 per_node_cost 생성 (래핑 제외)
    g.add_edge(START, "content_intake")
    if _graph_guard:
        g.add_conditional_edges("content_intake", _route_after_guard, {"blocked": "agentshield_block", "continue": "understand_content"})
        g.add_edge("agentshield_block", END)
    else:
        g.add_edge("content_intake", "understand_content")
    g.add_edge("understand_content", "memory_review")
    g.add_edge("memory_review", "llm_advisory_board")
    g.add_edge("llm_advisory_board", "synthesize")
    # synthesize → [심각도 판정] → 경미: 직선 / 심각: revise 루프 진입
    g.add_conditional_edges("synthesize", _revise_gate, {
        "validate": "independent_validation",
        "revise": "rewrite_loop",
    })
    # rewrite_loop → delta_screen → [신규 위험 판정] → 통과 / 재교정(백엣지) / HITL
    g.add_edge("rewrite_loop", "delta_screen")
    g.add_conditional_edges("delta_screen", _revise_branch, {
        "validate": "independent_validation",
        "revise": "rewrite_loop",
        "human": "human_review_gate",
    })
    g.add_edge("independent_validation", "human_review_gate")
    g.add_edge("human_review_gate", "final_report")
    g.add_edge("final_report", END)
    kwargs, _runtime_metadata = compile_options(
        enable_checkpoint=enable_checkpoint,
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
    )
    return g.compile(**kwargs)
