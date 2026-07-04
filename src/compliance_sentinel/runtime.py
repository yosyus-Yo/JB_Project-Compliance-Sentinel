"""Runtime helpers that connect routing plans to optional LLM execution.

The deterministic workflow remains the source of truth. These helpers add
observable LLM advisory calls and independent validation without making the
system depend on live model availability. If API keys/SDKs are absent or a call
fails, callers receive structured fallback metadata and continue safely.
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .cross_model_verifier import verify as cross_model_verify
from .llm_client import LLMClient
from .model_router import ModelRouter, current_critic_model, current_deep_model
from .models import to_plain
from .router import Router

BASE_CALL_COST_USD = 0.05
DEFAULT_LIVE_REVIEW_PROFILE = "turbo"
_PROFILE_EFFORT = {"turbo": "none", "fast": "low", "balanced": "medium", "strict": "high"}
_RISK_WORDS = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
_RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
_BOARD_ADVISORY_ROLES = [
    "legal_counsel",
    "pipa_expert",
    "consumer_protection",
    "operational_risk",
    "business_practicality",
    "contrarian",
]
_MARKETING_ADVISORY_ROLES = [*_BOARD_ADVISORY_ROLES, "ceo_synthesizer", "verifier"]
_BOARD_AGENT_TO_ROLE = {
    "legal-counsel": "legal_counsel",
    "pipa-credit-info-expert": "pipa_expert",
    "consumer-protection-expert": "consumer_protection",
    "aml-operational-risk-expert": "operational_risk",
    "business-practicality-expert": "business_practicality",
    "contrarian-agent": "contrarian",
}
_FAST_LOW_RISK_MARKETING_ROLES = ["legal_counsel", "consumer_protection", "verifier"]
_FAST_MEDIUM_RISK_MARKETING_ROLES = [
    "legal_counsel",
    "consumer_protection",
    "business_practicality",
    "verifier",
]
_TURBO_MEDIUM_RISK_MARKETING_ROLES = ["verifier"]
_FAST_LOW_RISK_BOARD_ROLES = ["legal_counsel", "consumer_protection"]
_QUALITY_FIRST_ESCALATION_ROLES = (
    "ceo_synthesizer",
    "verifier",
    "adversarial_critic",
    "independent_validator",
)


def parse_llm_risk_signal(text: str) -> dict:
    """Extract a bounded, non-PII board signal from optional LLM output.

    Raw LLM text is intentionally not retained in reports/audit logs. This parser
    keeps only a small structured verdict so live advisory calls can influence the
    board path without storing generated prose.
    """
    if not text:
        return {}
    upper = text.upper()
    risk_level = next((risk for risk in _RISK_WORDS if re.search(rf"\b{risk}\b", upper)), "")
    recommendation = ""
    lowered = text.lower()
    if "reject" in lowered or "반려" in text or "차단" in text:
        recommendation = "reject"
    elif "human" in lowered or "review" in lowered or "검토" in text:
        recommendation = "human_review"
    elif "approve" in lowered or "승인" in text:
        recommendation = "approve_with_or_without_changes"
    if not risk_level and not recommendation:
        return {}
    return {
        "risk_level": risk_level,
        "recommendation": recommendation,
        "signal_source": "llm_advisory_parsed_no_raw_text",
    }


def build_runtime_plan(input_text: str, *, deterministic_mode: bool) -> tuple[dict, dict]:
    """Return request routing decision + model routing plan as plain dicts."""

    decision = Router().classify(input_text)
    plan = ModelRouter(deterministic_mode=deterministic_mode).plan_from_decision(decision.to_dict())
    plan_dict = plan.to_dict()
    apply_live_profile_effort(plan_dict)
    return decision.to_dict(), plan_dict


def live_review_profile() -> str:
    """Return the live LLM review profile.

    turbo keeps the default runtime cost-bounded. balanced keeps the historical call surface. fast trims low-risk advisory
    calls. turbo uses deterministic review for LOW and one verifier call for
    MEDIUM while keeping high-risk and verifier-failure paths strict.
    """

    profile = os.environ.get("CS_LIVE_REVIEW_PROFILE", DEFAULT_LIVE_REVIEW_PROFILE).strip().lower()
    if profile in {"turbo", "fast", "balanced", "strict"}:
        return profile
    return DEFAULT_LIVE_REVIEW_PROFILE


def live_review_effort() -> str:
    """Return profile-bound effort, with an explicit env override."""

    override = os.environ.get("CS_LIVE_REVIEW_EFFORT", "").strip().lower()
    if override in {"none", "low", "medium", "high"}:
        return override
    return _PROFILE_EFFORT[live_review_profile()]


def apply_live_profile_effort(model_plan: dict) -> list[str]:
    """Apply live review effort to advisory and validation role assignments."""

    effort = live_review_effort()
    assignments = model_plan.get("role_assignments") or {}
    changed: list[str] = []
    for role in (*_MARKETING_ADVISORY_ROLES, "adversarial_critic", "independent_validator"):
        assignment = assignments.get(role)
        if assignment and assignment.get("effort") != effort:
            assignment["effort"] = effort
            changed.append(role)
    cross_model = model_plan.get("cross_model") or {}
    if cross_model.get("level") not in {None, "", "NONE"} and cross_model.get("effort") != effort:
        cross_model["effort"] = effort
        changed.append("cross_model")
    return changed


def select_marketing_advisory_roles(review_risk: str) -> list[str]:
    """Choose marketing advisory roles for the active live review profile."""

    profile = live_review_profile()
    risk_rank = _RISK_RANK.get(str(review_risk).upper(), 0)
    if profile in {"balanced", "strict"} or risk_rank >= _RISK_RANK["HIGH"]:
        return list(_MARKETING_ADVISORY_ROLES)
    if profile == "turbo":
        if risk_rank == _RISK_RANK["MEDIUM"]:
            return list(_TURBO_MEDIUM_RISK_MARKETING_ROLES)
        return []
    if risk_rank == _RISK_RANK["MEDIUM"]:
        return list(_FAST_MEDIUM_RISK_MARKETING_ROLES)
    return list(_FAST_LOW_RISK_MARKETING_ROLES)


def advisory_max_tokens_for_risk(risk_level: str) -> int:
    """Give high-risk live reviews enough room without expanding low-risk calls."""

    risk_rank = _RISK_RANK.get(str(risk_level).upper(), 0)
    return 512 if risk_rank >= _RISK_RANK["HIGH"] else 128


def apply_quality_first_routing(model_plan: dict, *, risk_level: str) -> list[str]:
    """Escalate high-risk synthesis/validation roles without mixing contexts.

    The first-pass router only sees the raw request. Domain rules can later reveal
    HIGH/CRITICAL risk, so runtime needs a deterministic promotion path before
    any live CEO/verifier/critic advisory calls. Board drafting remains on mini,
    classifier/documenter remain on nano, CEO stays on the deep synthesis model,
    and verifier/critic roles move to the isolated critic route.
    """

    risk_rank = _RISK_RANK.get(str(risk_level).upper(), 0)
    if risk_rank < _RISK_RANK["HIGH"]:
        return []

    assignments = model_plan.get("role_assignments") or {}
    escalated: list[str] = []
    for role in _QUALITY_FIRST_ESCALATION_ROLES:
        assignment = assignments.get(role)
        if not assignment:
            continue
        target_model = current_deep_model() if role == "ceo_synthesizer" else current_critic_model()
        changed = False
        for key, value in {
            "model": target_model,
            "effort": live_review_effort(),
            "tier": "critical",
            "cost_multiplier": 1.0,
        }.items():
            if assignment.get(key) != value:
                assignment[key] = value
                changed = True
        if changed:
            escalated.append(role)
    return escalated


def select_board_advisory_roles(board_opinions: dict[str, Any]) -> list[str]:
    """Choose general board advisory roles for the active live review profile."""

    profile = live_review_profile()
    if profile in {"balanced", "strict"}:
        return list(_BOARD_ADVISORY_ROLES)

    max_rank = 0
    selected: list[str] = []
    for agent_id, opinion in board_opinions.items():
        role = _BOARD_AGENT_TO_ROLE.get(str(agent_id))
        if not role:
            continue
        risk = str(getattr(opinion, "risk_level", "LOW")).upper()
        rank = _RISK_RANK.get(risk, 0)
        max_rank = max(max_rank, rank)
        if rank >= _RISK_RANK["MEDIUM"]:
            selected.append(role)

    if max_rank >= _RISK_RANK["HIGH"]:
        return list(_BOARD_ADVISORY_ROLES)

    if profile == "turbo":
        return []

    roles = list(dict.fromkeys([*_FAST_LOW_RISK_BOARD_ROLES, *selected]))
    return roles or list(_FAST_LOW_RISK_BOARD_ROLES)


def should_run_stage_advisory(*, role: str, has_findings: bool, highest_risk: str = "LOW") -> bool:
    """Gate sequential CEO/verifier advisory calls in fast mode."""

    profile = live_review_profile()
    if profile in {"balanced", "strict"}:
        return True
    risk_rank = _RISK_RANK.get(str(highest_risk).upper(), 0)
    if risk_rank >= _RISK_RANK["HIGH"] or has_findings:
        return True
    if profile == "turbo":
        return role == "verifier" and risk_rank >= _RISK_RANK["MEDIUM"]
    return role == "verifier"


def llm_advisory_call(
    *,
    model_plan: dict,
    llm_client: LLMClient,
    role: str,
    user_text: str,
    max_tokens: int = 512,
) -> dict:
    """Execute one optional LLM call for observability/advisory use.

    The text output is intentionally not stored in audit logs to avoid leaking
    generated content or accidentally retaining sensitive context. The caller can
    later add parser-specific handling behind explicit tests.
    """

    assignment = (model_plan.get("role_assignments") or {}).get(role)
    if not assignment:
        return {
            "role": role,
            "model": None,
            "called": False,
            "deterministic_fallback": True,
            "error": "role_not_in_model_plan",
        }

    estimated_cost = round(BASE_CALL_COST_USD * float(assignment.get("cost_multiplier", 1.0)), 4)
    result = llm_client.call(
        role,
        user_text,
        model=assignment["model"],
        effort=assignment.get("effort", "none"),
        max_tokens=max_tokens,
        estimated_cost_usd=estimated_cost,
    )
    structured_signal = parse_llm_risk_signal(result.text or "") if not result.deterministic_fallback and result.error is None else {}
    return {
        "role": role,
        "model": result.model,
        "effort": assignment.get("effort", "none"),
        "called": not result.deterministic_fallback and result.error is None,
        "deterministic_fallback": result.deterministic_fallback,
        "error": result.error,
        "text_length": len(result.text or ""),
        "estimated_cost_usd": estimated_cost,
        "cached_tokens": result.cached_tokens,
        "prompt_tokens": result.prompt_tokens,
        **structured_signal,
    }


def llm_advisory_calls_parallel(
    *,
    model_plan: dict,
    llm_client: LLMClient,
    roles: list[str],
    user_text: str,
    max_tokens: int = 512,
) -> list[dict]:
    """Execute independent advisory calls concurrently while preserving role order.

    Board members and independent validators do not feed each other's outputs in the
    deterministic MVP. Running them in parallel removes the main live-runtime bottleneck
    without changing final decision semantics.
    """
    if not roles:
        return []
    try:
        max_workers = max(1, int(os.environ.get("CS_LLM_PARALLELISM", "8")))
    except ValueError:
        max_workers = 8
    max_workers = min(max_workers, len(roles))
    indexed: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                llm_advisory_call,
                model_plan=model_plan,
                llm_client=llm_client,
                role=role,
                user_text=user_text,
                max_tokens=max_tokens,
            ): idx
            for idx, role in enumerate(roles)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                indexed[idx] = future.result()
            except Exception as exc:  # defensive: preserve workflow progress
                indexed[idx] = {
                    "role": roles[idx],
                    "model": None,
                    "called": False,
                    "deterministic_fallback": True,
                    "error": f"parallel_call_error:{type(exc).__name__}:{str(exc)[:200]}",
                }
    return [indexed[i] for i in range(len(roles))]


def run_independent_validation(
    *,
    model_plan: dict,
    ceo_draft: dict,
    verifier_results: list[Any],
    llm_client: LLMClient | None = None,
) -> dict:
    """Run critical/advisory independent validation when the plan requests it."""

    recommendation = model_plan.get("cross_model") or {}
    if recommendation.get("level") == "NONE":
        return {
            "enabled": False,
            "cross_model_confidence": "SKIPPED",
            "recommendation": "skipped",
            "reason": "cross_model_level_none",
            "level": "NONE",
        }

    result = cross_model_verify(
        builder_output=to_plain(ceo_draft),
        verifier_output=to_plain(verifier_results),
        model=recommendation.get("model") or current_critic_model(),
        effort=recommendation.get("effort") or live_review_effort(),
        llm_client=llm_client,
        estimated_cost_usd=BASE_CALL_COST_USD,
    )
    return {
        "enabled": result.enabled,
        "cross_model_confidence": result.cross_model_confidence,
        "agreed_findings": result.agreed_findings,
        "disputed_findings": result.disputed_findings,
        "blind_spots_caught": result.blind_spots_caught,
        "recommendation": result.recommendation,
        "error": result.error,
        "deterministic_fallback": result.deterministic_fallback,
        "level": recommendation.get("level", "NONE"),
        "model": recommendation.get("model"),
        "effort": recommendation.get("effort"),
        "estimated_cost_usd": result.estimated_cost_usd,
    }
