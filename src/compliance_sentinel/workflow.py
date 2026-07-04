from __future__ import annotations

import os
from pathlib import Path

from .agent_model_guard import ModelGuard
from .agent_shield_bridge import enforce_input_guard
from .telemetry import _emit_l3_trace  # L3 외부연동 (env 없으면 no-op)
from .audit import AuditStore
from .board import apply_llm_advisory_to_board, run_compliance_board
from .budget_guard import from_env as budget_guard_from_env
from .citation_extractor import extract_explicit_citations
from .classification import classify_input
from .knowledge_base import LawKnowledgeBase
from .models import ComplianceState, MAX_REVISE_RETRIES
from .llm_client import LLMClient
from .memory_rag import ComplianceMemoryRAG
from .pii import redact_pii
from .reporting import build_final_report
from .runtime import (
    advisory_max_tokens_for_risk,
    apply_live_profile_effort,
    apply_quality_first_routing,
    build_runtime_plan,
    live_review_effort,
    live_review_profile,
    llm_advisory_call,
    llm_advisory_calls_parallel,
    run_independent_validation,
    select_board_advisory_roles,
    should_run_stage_advisory,
)
from .model_router import current_critic_model
from .synthesizer import synthesize_opinion
from .verifier import apply_verifier_results, extract_atomic_claims, has_failures, verify_claims


class ComplianceSentinel:
    def __init__(self, kb: LawKnowledgeBase | None = None, audit_store: AuditStore | None = None) -> None:
        self.kb = kb or LawKnowledgeBase.from_json()
        self.audit_store = audit_store or AuditStore()
        self.model_guard = ModelGuard.from_env()
        self.llm_client = LLMClient(budget_guard=budget_guard_from_env(), model_guard=self.model_guard)
        self.memory_rag = ComplianceMemoryRAG(kb=self.kb)

    @_emit_l3_trace
    def analyze(self, input_text: str) -> ComplianceState:
        # Library-level guard: direct callers of the deterministic workflow pass
        # the same AgentShield input guard as the engine/API paths. A
        # high-confidence injection short-circuits before board/LLM runs.
        blocked = enforce_input_guard(input_text)
        if blocked is not None:
            return ComplianceState(input_text=input_text, redacted_text=input_text, final_report=blocked)
        state = ComplianceState(input_text=input_text)
        self._classify_input(state)
        self._plan_models(state)
        self._pii_guard(state)
        self._extract_user_citations(state)
        self._recall_memory(state)
        self._retrieve_context(state)
        self._parallel_board_review(state)
        self._synthesize_opinion(state)
        self._verify_with_retry(state)
        self._independent_validation(state)
        self._final_report(state)
        self._capture_memory_outcome(state)
        self._audit_log(state)
        state.final_report["audit_log_id"] = state.audit_log_id
        return state

    def _classify_input(self, state: ComplianceState) -> None:
        state.input_type = classify_input(state.input_text)
        state.add_trace("classify_input", input_type=state.input_type)

    def _plan_models(self, state: ComplianceState) -> None:
        state.routing_decision, state.model_plan = build_runtime_plan(
            state.input_text,
            deterministic_mode=self.llm_client.deterministic,
        )
        state.add_trace(
            "plan_models",
            domain=state.routing_decision.get("domain"),
            quality=state.routing_decision.get("quality"),
            base_tier=state.model_plan.get("base_tier"),
            deterministic_mode=state.model_plan.get("deterministic_mode"),
            profile=live_review_profile(),
            effort=live_review_effort(),
        )

    def _record_llm_advisory(self, state: ComplianceState, *, role: str, user_text: str, max_tokens: int = 512) -> None:
        call = llm_advisory_call(
            model_plan=state.model_plan,
            llm_client=self.llm_client,
            role=role,
            user_text=user_text,
            max_tokens=max_tokens,
        )
        state.llm_calls.append(call)
        state.add_trace(
            "llm_advisory_call",
            role=call.get("role"),
            model=call.get("model"),
            called=call.get("called"),
            deterministic_fallback=call.get("deterministic_fallback"),
            error=call.get("error"),
        )

    def _pii_guard(self, state: ComplianceState) -> None:
        state.redacted_text, state.pii_findings = redact_pii(state.input_text)
        if state.routing_decision:
            state.routing_decision["raw_input"] = state.redacted_text
        state.add_trace("pii_guard", pii_count=len(state.pii_findings), used_redacted_text=True)

    def _extract_user_citations(self, state: ComplianceState) -> None:
        # PII 마스킹 후 텍스트에서 사용자가 명시한 법령 인용을 뽑아낸다.
        # synthesizer는 이 인용을 별도 finding(verifier_status 미정)으로 변환해 verifier에 그대로 통과시킨다.
        state.user_cited_articles = extract_explicit_citations(state.redacted_text)
        state.add_trace(
            "extract_user_citations",
            count=len(state.user_cited_articles),
            citations=[f"{c.law_name} 제{c.article_no}조" for c in state.user_cited_articles],
        )

    def _recall_memory(self, state: ComplianceState) -> None:
        self.memory_rag.recall(state)

    def _retrieve_context(self, state: ComplianceState) -> None:
        bundle = self.memory_rag.retrieve_context(state)
        state.retrieved_context = bundle.law_articles
        state.add_trace("retrieve_context", retrieved=len(state.retrieved_context), laws=[a.law_name for a in state.retrieved_context])

    def _parallel_board_review(self, state: ComplianceState) -> None:
        state.board_opinions = run_compliance_board(state.redacted_text, state.retrieved_context)
        roles = select_board_advisory_roles(state.board_opinions)
        calls = llm_advisory_calls_parallel(
            model_plan=state.model_plan,
            llm_client=self.llm_client,
            roles=roles,
            user_text=state.redacted_text,
            max_tokens=128,
        )
        state.llm_calls.extend(calls)
        for call in calls:
            state.add_trace(
                "llm_advisory_call",
                role=call.get("role"),
                model=call.get("model"),
                called=call.get("called"),
                deterministic_fallback=call.get("deterministic_fallback"),
                error=call.get("error"),
            )
        state.board_opinions = apply_llm_advisory_to_board(
            state.board_opinions,
            state.llm_calls,
            enabled=os.environ.get("CS_USE_LLM_BOARD_VERDICTS") == "1",
        )
        state.add_trace(
            "parallel_board_review",
            agents=list(state.board_opinions),
            opinion_count=len(state.board_opinions),
            llm_parallelism=len(roles),
            profile=live_review_profile(),
            effort=live_review_effort(),
            roles=roles,
            llm_board_verdicts_enabled=os.environ.get("CS_USE_LLM_BOARD_VERDICTS") == "1",
        )

    def _synthesize_opinion(self, state: ComplianceState) -> None:
        state.ceo_draft = synthesize_opinion(
            state.redacted_text,
            state.board_opinions,
            user_citations=state.user_cited_articles,
        )
        risk_level = str(state.ceo_draft.get("risk_level", "LOW"))
        escalated_roles = apply_quality_first_routing(state.model_plan, risk_level=risk_level)
        effort_roles = apply_live_profile_effort(state.model_plan)
        if escalated_roles:
            state.add_trace(
                "quality_first_model_escalation",
                risk_level=risk_level,
                roles=escalated_roles,
                model=current_critic_model(),
                effort=live_review_effort(),
            )
        if effort_roles:
            state.add_trace("live_profile_effort", profile=live_review_profile(), effort=live_review_effort(), roles=effort_roles)
        max_tokens = advisory_max_tokens_for_risk(risk_level)
        if should_run_stage_advisory(role="ceo_synthesizer", has_findings=False, highest_risk=risk_level):
            self._record_llm_advisory(state, role="ceo_synthesizer", user_text=state.redacted_text, max_tokens=max_tokens)
        else:
            state.add_trace("llm_advisory_skipped", role="ceo_synthesizer", profile=live_review_profile(), risk_level=risk_level)
        state.add_trace("synthesize_opinion", findings=len(state.ceo_draft.get("findings", [])), risk_level=state.ceo_draft.get("risk_level"))

    def _verify_with_retry(self, state: ComplianceState) -> None:
        while True:
            findings = state.ceo_draft.get("findings", [])
            state.atomic_claims = extract_atomic_claims(findings)
            state.verifier_results = verify_claims(state.atomic_claims, self.kb)
            apply_verifier_results(findings, state.verifier_results)
            risk_level = str(state.ceo_draft.get("risk_level", "LOW"))
            escalated_roles = apply_quality_first_routing(state.model_plan, risk_level=risk_level)
            effort_roles = apply_live_profile_effort(state.model_plan)
            if escalated_roles:
                state.add_trace(
                    "quality_first_model_escalation",
                    risk_level=risk_level,
                    roles=escalated_roles,
                    model=current_critic_model(),
                    effort=live_review_effort(),
                )
            if effort_roles:
                state.add_trace("live_profile_effort", profile=live_review_profile(), effort=live_review_effort(), roles=effort_roles)
            max_tokens = advisory_max_tokens_for_risk(risk_level)
            failed = has_failures(state.verifier_results)
            if should_run_stage_advisory(role="verifier", has_findings=failed, highest_risk=risk_level):
                self._record_llm_advisory(state, role="verifier", user_text=state.redacted_text, max_tokens=max_tokens)
            else:
                state.add_trace("llm_advisory_skipped", role="verifier", profile=live_review_profile(), risk_level=risk_level)
            # 사용자 인용 finding이 PARTIAL이면 원문 보정 가능 → revise 발동 후 재검증
            needs_revise = failed or _has_revisable_partial(findings, self.kb)
            state.add_trace(
                "verify_atomic_claims",
                retry_count=state.retry_count,
                claims=len(state.atomic_claims),
                failed=failed,
                needs_revise=needs_revise,
            )
            if not needs_revise or state.retry_count >= 3:
                return
            state.retry_count += 1
            self._revise_opinion(state)

    def _revise_opinion(self, state: ComplianceState) -> None:
        findings = state.ceo_draft.get("findings", [])
        for finding in findings:
            if finding.verifier_status in {"FAIL", "PARTIAL"}:
                article = self.kb.get_article(finding.law_name, finding.article_no)
                if article and finding.citation_text != article.text:
                    finding.citation_text = article.text
                    finding.applicability_reason += " verifier 피드백에 따라 원문 인용을 보정했습니다."
        state.add_trace("revise_opinion", retry_count=state.retry_count)

    def _independent_validation(self, state: ComplianceState) -> None:
        risk_level = str(state.ceo_draft.get("risk_level", "LOW")) if state.ceo_draft else "LOW"
        forced_cross_model = _force_cross_model_for_high_risk_findings(state)
        if forced_cross_model:
            state.add_trace(
                "independent_validation_forced",
                reason="high_risk_or_failed_finding",
                model=(state.model_plan.get("cross_model") or {}).get("model"),
            )
        escalation_risk = "HIGH" if forced_cross_model else risk_level
        escalated_roles = apply_quality_first_routing(state.model_plan, risk_level=escalation_risk)
        effort_roles = apply_live_profile_effort(state.model_plan)
        if escalated_roles:
            state.add_trace(
                "quality_first_model_escalation",
                risk_level=escalation_risk,
                roles=escalated_roles,
                model=current_critic_model(),
                effort=live_review_effort(),
            )
        if effort_roles:
            state.add_trace("live_profile_effort", profile=live_review_profile(), effort=live_review_effort(), roles=effort_roles)
        state.cross_model_result = run_independent_validation(
            model_plan=state.model_plan,
            ceo_draft=state.ceo_draft,
            verifier_results=state.verifier_results,
            llm_client=self.llm_client,
        )
        should_add_extra_validation_advisory = os.environ.get("CS_EXTRA_VALIDATION_ADVISORY") == "1"
        cross_level = state.cross_model_result.get("level") or "NONE"
        if cross_level != "NONE" and (not state.cross_model_result.get("enabled") or should_add_extra_validation_advisory):
            calls = llm_advisory_calls_parallel(
                model_plan=state.model_plan,
                llm_client=self.llm_client,
                roles=["adversarial_critic", "independent_validator"],
                user_text=state.redacted_text,
                max_tokens=advisory_max_tokens_for_risk(escalation_risk),
            )
            state.llm_calls.extend(calls)
            for call in calls:
                state.add_trace(
                    "llm_advisory_call",
                    role=call.get("role"),
                    model=call.get("model"),
                    called=call.get("called"),
                    deterministic_fallback=call.get("deterministic_fallback"),
                    error=call.get("error"),
                )
        state.add_trace(
            "independent_validation",
            level=state.cross_model_result.get("level"),
            enabled=state.cross_model_result.get("enabled"),
            confidence=state.cross_model_result.get("cross_model_confidence"),
            fallback=state.cross_model_result.get("deterministic_fallback"),
        )

    def _final_report(self, state: ComplianceState) -> None:
        from .guardrails import ensure_disclaimer
        state.final_report = ensure_disclaimer(build_final_report(state))
        try:
            state.final_report["budget_status"] = self.llm_client.budget_guard.status_with_tier()
        except AttributeError:
            pass
        state.add_trace("final_report", status=state.final_report["status"], confidence=state.final_report["confidence"])

    def _capture_memory_outcome(self, state: ComplianceState) -> None:
        self.memory_rag.capture_outcome(state)

    def _audit_log(self, state: ComplianceState) -> None:
        state.audit_log_id = self.audit_store.write(state)
        if state.board_diagnostics is not None:
            from .models import BoardDiagnostics
            state.board_diagnostics = BoardDiagnostics(
                risk_distribution=state.board_diagnostics.risk_distribution,
                majority_risk=state.board_diagnostics.majority_risk,
                disagreement_score=state.board_diagnostics.disagreement_score,
                minority_opinions=state.board_diagnostics.minority_opinions,
                requires_human_arbitration=state.board_diagnostics.requires_human_arbitration,
                contradiction_pairs=state.board_diagnostics.contradiction_pairs,
                audit_log_id=state.audit_log_id,
            )
            state.final_report["board_diagnostics"] = {
                **state.final_report.get("board_diagnostics", {}),
                "audit_log_id": state.audit_log_id,
            }
        from .report_schema import validate_final_report
        state.final_report["audit_log_id"] = state.audit_log_id
        schema_errors = validate_final_report(state.final_report)
        state.final_report["schema_validation"] = {
            "schema_version": "compliance-sentinel-final-report/v2",
            "passed": not schema_errors,
            "errors": schema_errors,
        }
        state.add_trace("audit_log", audit_log_id=state.audit_log_id)


def analyze_text(input_text: str, *, audit_path: str | Path | None = None) -> dict:
    # Secure-by-default applies to this legacy entrypoint too — the guard cannot
    # be bypassed by calling the helper directly instead of analyze_with_engine().
    blocked = enforce_input_guard(input_text)
    if blocked is not None:
        return blocked
    audit_store = AuditStore(audit_path) if audit_path else AuditStore()
    state = ComplianceSentinel(audit_store=audit_store).analyze(input_text)
    return state.final_report


def _has_revisable_partial(findings: list, kb: LawKnowledgeBase) -> bool:
    """PARTIAL 상태의 finding 중 KB 원문으로 보정 가능한 것이 있는가?

    citation_text가 KB 원문과 다르고, KB에 article이 존재해야 revise 의미 있음.
    """
    for finding in findings:
        if finding.verifier_status != "PARTIAL":
            continue
        article = kb.get_article(finding.law_name, finding.article_no)
        if article and finding.citation_text != article.text:
            return True
    return False


def _force_cross_model_for_high_risk_findings(state: ComplianceState) -> bool:
    findings = state.ceo_draft.get("findings", []) if state.ceo_draft else []
    if not findings:
        return False
    cross_model = state.model_plan.get("cross_model") or {}
    if cross_model.get("level") not in {None, "", "NONE"}:
        return False
    should_force = any(
        getattr(finding, "verifier_status", "") == "FAIL"
        or getattr(finding, "risk_level", "") in {"HIGH", "CRITICAL"}
        or getattr(finding, "severity", "") in {"HIGH", "CRITICAL"}
        for finding in findings
    )
    if not should_force:
        return False
    state.model_plan["cross_model"] = {
        "level": "STRONG",
        "model": current_critic_model(),
        "effort": live_review_effort(),
        "reason": "forced_by_high_risk_or_failed_finding",
        "auto_attach": True,
    }
    return True
