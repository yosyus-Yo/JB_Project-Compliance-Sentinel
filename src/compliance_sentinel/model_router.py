"""Model Router — 4-tier 매트릭스로 역할별 모델·effort를 결정.

목적:
  RoutingDecision (5축 분류 결과)을 받아 각 역할 (classifier/board/ceo/verifier)별
  모델 + effort + cross-model verifier 추천을 반환.

원칙:
  - Builder ≠ Verifier 격리 (역할별 다른 prompt + 컨텍스트)
  - tier 모델 기본값은 Anthropic Claude (2026-07-03 전환): shallow=haiku, standard=sonnet, deep=opus.
    OpenAI(gpt-5.x) tier도 allowlist에 남겨 env override 가능 — ALLOWED_TIER_MODELS 참조.
  - verifier/적대적 비평가/독립 검증자는 별도 CS_MODEL_CRITIC 경로로 격리
  - 결정론적: 동일 입력 → 동일 출력 (재현성)
  - SEAS depth-tier-routing 패턴 차용

출처:
  - workflows/cs-model-routing.yaml (single source for tier 정의)
  - .claude/rules/depth-tier-routing.md (SEAS)
  - .claude/rules/selective-subagent.md Rule 3 (SEAS)
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Optional

# ──────────────────────────────────────────────────────────────────
# Model identifiers (실제 API 호출 시 사용)
# ──────────────────────────────────────────────────────────────────

ALLOWED_OPENAI_MODELS = frozenset({"gpt-5.5", "gpt-5.4-mini", "gpt-5.4-nano"})
# 2026-07-03: 6인 보드 기본 경로를 Anthropic Claude로 전환 (사용자 ANTHROPIC_API_KEY).
# tier env override는 아래 allowlist(OpenAI + Anthropic) 내에서만 허용 — 임의 오타/downgrade 차단.
ALLOWED_ANTHROPIC_MODELS = frozenset(
    {"claude-opus-4-8", "claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-4-5"}
)
ALLOWED_TIER_MODELS = ALLOWED_OPENAI_MODELS | ALLOWED_ANTHROPIC_MODELS
CRITIC_PROVIDER_PREFIXES = ("openrouter/anthropic/", "anthropic/claude-")


def _fixed_model_env(*names: str, default: str) -> str:
    """Return an env-configured tier model, restricted to the allowed set.

    허용: OpenAI 고정 tier(gpt-5.5/mini/nano) 또는 Anthropic Claude tier 모델.
    임의 값(오타 / 저비용 downgrade)은 ValueError로 차단하여 재현성을 보존한다.
    """
    for name in names:
        value = os.environ.get(name)
        if not value:
            continue
        if value not in ALLOWED_TIER_MODELS and not value.startswith(CRITIC_PROVIDER_PREFIXES):
            allowed = ", ".join(sorted(ALLOWED_TIER_MODELS))
            raise ValueError(
                f"{name}={value!r} is not an allowed tier model. "
                f"Allowed: [{allowed}] or an OpenRouter/Anthropic critic prefix."
            )
        return value
    return default


def _is_allowed_critic_model(value: str) -> bool:
    return (
        value in ALLOWED_OPENAI_MODELS
        or value in ALLOWED_ANTHROPIC_MODELS
        or value.startswith(CRITIC_PROVIDER_PREFIXES)
    )


def _critic_model_env(*names: str, default: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if not value:
            continue
        if not _is_allowed_critic_model(value):
            raise ValueError(
                f"{name}={value!r} is not allowed. "
                "Critic routing allows fixed OpenAI models or OpenRouter/Anthropic Claude critic models."
            )
        return value
    return default


def _model_env(primary: str, legacy: str, default: str) -> str:
    return _fixed_model_env(primary, legacy, default=default)


# 기본 tier 모델 = Anthropic Claude (2026-07-03). 상수명(MODEL_OPENAI_NANO 등)은
# 하위 호환을 위해 유지하나 실제 값은 Claude tier이다: haiku=shallow, sonnet=standard, opus=deep.
MODEL_OPENAI_NANO = _model_env("CS_MODEL_SHALLOW", "CS_MODEL_OPENAI_NANO", "claude-haiku-4-5")
MODEL_CODEX_MINI = _model_env("CS_MODEL_STANDARD", "CS_MODEL_CODEX_MINI", "claude-sonnet-5")
MODEL_CODEX = _model_env("CS_MODEL_DEEP", "CS_MODEL_CODEX_DEEP", "claude-opus-4-8")
MODEL_CRITIC = _critic_model_env("CS_MODEL_CRITIC", default="claude-opus-4-8")

# Provider-neutral aliases for new integrations. Backward-compatible constants
# above remain because tests and downstream code import them.
MODEL_SHALLOW = MODEL_OPENAI_NANO
MODEL_STANDARD = MODEL_CODEX_MINI
MODEL_DEEP = MODEL_CODEX


def refresh_model_config_from_env() -> None:
    """Refresh module-level routing constants after UI/env changes.

    Streamlit settings can update environment variables after this module is
    imported. Refreshing keeps ModelRouter plans aligned with the latest UI
    configuration without requiring a process restart.
    """
    global MODEL_OPENAI_NANO, MODEL_CODEX_MINI, MODEL_CODEX, MODEL_CRITIC
    global MODEL_SHALLOW, MODEL_STANDARD, MODEL_DEEP
    global TIER_BASE_MODEL, VALIDATION_MODEL
    MODEL_OPENAI_NANO = _model_env("CS_MODEL_SHALLOW", "CS_MODEL_OPENAI_NANO", "claude-haiku-4-5")
    MODEL_CODEX_MINI = _model_env("CS_MODEL_STANDARD", "CS_MODEL_CODEX_MINI", "claude-sonnet-5")
    MODEL_CODEX = _model_env("CS_MODEL_DEEP", "CS_MODEL_CODEX_DEEP", "claude-opus-4-8")
    MODEL_CRITIC = _critic_model_env("CS_MODEL_CRITIC", default="claude-opus-4-8")
    MODEL_SHALLOW = MODEL_OPENAI_NANO
    MODEL_STANDARD = MODEL_CODEX_MINI
    MODEL_DEEP = MODEL_CODEX
    TIER_BASE_MODEL = {
        "shallow": (MODEL_OPENAI_NANO, "none"),
        "standard": (MODEL_CODEX_MINI, "none"),
        "deep": (MODEL_CODEX, "none"),
        "critical": (MODEL_CODEX, "none"),
    }
    VALIDATION_MODEL = MODEL_CRITIC


def current_critic_model() -> str:
    return _critic_model_env("CS_MODEL_CRITIC", default="claude-opus-4-8")


def current_deep_model() -> str:
    return _model_env("CS_MODEL_DEEP", "CS_MODEL_CODEX_DEEP", "claude-opus-4-8")

# Backward-compatible aliases for tests/imports. These are no longer the primary route.
MODEL_HAIKU = "claude-haiku-4-5"
MODEL_SONNET = "claude-sonnet-5"

# Tier별 base model — fixed OpenAI route.
TIER_BASE_MODEL = {
    "shallow": (MODEL_OPENAI_NANO, "none"),
    "standard": (MODEL_CODEX_MINI, "none"),
    "deep": (MODEL_CODEX, "none"),
    "critical": (MODEL_CODEX, "none"),
}

# 검증/비평 계열은 별도 critic model 경로로 고정.
VALIDATION_ROLES = {"verifier", "adversarial_critic", "independent_validator", "cross_model_verifier"}
VALIDATION_MODEL = MODEL_CRITIC

# 역할별 model_tier override.
ROLE_MIN_TIER = {
    "classifier": "shallow",
    "board_member": "standard",
    "ceo_synthesizer": "standard",
    "verifier": "standard",
    "adversarial_critic": "standard",
    "independent_validator": "standard",
    "cross_model_verifier": "deep",
    "documenter": "shallow",
    "router": "shallow",         # 결정론적 CLI라 LLM 호출 거의 없음
}

# Cost multiplier (Codex deep = 1.0 기준 추정)
TIER_COST_MULTIPLIER = {
    "shallow": 0.04,
    "standard": 0.15,
    "deep": 1.00,
    "critical": 1.00,
}

VALIDATION_COST_MULTIPLIER = 1.00  # gpt-5.5 validation path

# Cross-model verifier 추천 매트릭스 (SEAS auto-delegate codex_review_recommendation)
CROSS_MODEL_RULES = [
    # (quality, complexity_in, domain_in, level)
    # critical + team-like domain → STRONG (auto-attach)
    ("critical", {"any"}, {"terms_review", "ad_review", "contract_review", "transaction", "bulk_audit"}, "STRONG"),
    # critical + complex/massive any → STRONG
    ("critical", {"complex", "massive"}, {"any"}, "STRONG"),
    # non-critical complex/massive + implementation domain → ADVISORY
    ("non_critical", {"complex", "massive"}, {"terms_review", "ad_review", "contract_review", "transaction"}, "ADVISORY"),
    # critical simple/medium non-team → ADVISORY
    ("critical", {"simple", "medium"}, {"law_question", "policy_change"}, "ADVISORY"),
]


# ──────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────

@dataclass
class RoleAssignment:
    role: str
    model: str
    effort: str
    tier: str
    cost_multiplier: float
    system_prompt_key: str  # system_prompts/{key}.md
    isolation_required: bool = False  # Builder/Verifier 같은 모델이라도 별도 context

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CrossModelRecommendation:
    level: str  # NONE | ADVISORY | STRONG
    model: Optional[str] = None
    effort: Optional[str] = None
    reason: str = ""
    auto_attach: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ModelRoutingPlan:
    """라우팅 결정에 대한 전체 모델 plan."""
    domain: str
    complexity: str
    quality: str
    base_tier: str  # routing decision의 routed_model_tier
    role_assignments: dict[str, RoleAssignment] = field(default_factory=dict)
    cross_model: CrossModelRecommendation = field(default_factory=lambda: CrossModelRecommendation(level="NONE"))
    deterministic_mode: bool = False  # CS_DETERMINISTIC_MODE=1 또는 API key 부재 시 True
    estimated_cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "complexity": self.complexity,
            "quality": self.quality,
            "base_tier": self.base_tier,
            "role_assignments": {k: v.to_dict() for k, v in self.role_assignments.items()},
            "cross_model": self.cross_model.to_dict(),
            "deterministic_mode": self.deterministic_mode,
            "estimated_cost_usd": self.estimated_cost_usd,
        }


# ──────────────────────────────────────────────────────────────────
# Core router
# ──────────────────────────────────────────────────────────────────

class ModelRouter:
    """RoutingDecision → ModelRoutingPlan 변환.

    LLM 호출은 하지 않는다 — plan 결정만. 실제 호출은 LLMClient + Board가 plan을 받아 수행.
    """

    def __init__(self, *, deterministic_mode: bool = False) -> None:
        refresh_model_config_from_env()
        self.deterministic_mode = deterministic_mode

    def plan_from_decision(self, decision_dict: dict) -> ModelRoutingPlan:
        """RoutingDecision.to_dict()를 받아 ModelRoutingPlan 생성."""
        domain = decision_dict["domain"]
        complexity = decision_dict["complexity"]
        quality = decision_dict["quality"]
        base_tier = decision_dict.get("routed_model_tier", "standard")

        plan = ModelRoutingPlan(
            domain=domain,
            complexity=complexity,
            quality=quality,
            base_tier=base_tier,
            deterministic_mode=self.deterministic_mode,
        )

        # 1. Role assignments
        plan.role_assignments = self._assign_roles(base_tier, quality)

        # 2. Cross-model recommendation
        plan.cross_model = self._recommend_cross_model(quality, complexity, domain)

        # 3. Estimated cost
        plan.estimated_cost_usd = self._estimate_cost(plan)

        return plan

    def _assign_roles(self, base_tier: str, quality: str) -> dict[str, RoleAssignment]:
        """각 역할(classifier/board_member/ceo/verifier/...)에 model+effort 할당."""
        assignments: dict[str, RoleAssignment] = {}

        # classifier — 항상 shallow (저비용 입력 분류)
        assignments["classifier"] = self._make_role("classifier", "shallow", "classifier")

        # 6인 보드 보드원 — base_tier 따름 (critical에서도 board는 standard 유지, CEO만 critical)
        board_tier = base_tier if base_tier in {"shallow", "standard"} else "standard"
        for member in [
            "legal_counsel",
            "pipa_expert",
            "consumer_protection",
            "operational_risk",
            "business_practicality",
            "contrarian",
        ]:
            assignments[member] = self._make_role(member, board_tier, "board_member")

        # CEO uses mini for non-critical synthesis; critical still escalates.
        ceo_tier = "critical" if base_tier == "critical" else "standard"
        assignments["ceo_synthesizer"] = self._make_role("ceo_synthesizer", ceo_tier, "ceo_synthesizer")

        # Non-critical verification stays isolated but uses mini; critical uses gpt-5.5.
        verifier_tier = "critical" if base_tier == "critical" else "standard"
        assignments["verifier"] = self._make_role(
            "verifier", verifier_tier, "verifier", isolation_required=True,
        )
        assignments["adversarial_critic"] = self._make_role(
            "adversarial_critic", verifier_tier, "verifier", isolation_required=True,
        )
        assignments["independent_validator"] = self._make_role(
            "independent_validator", verifier_tier, "codex_verifier", isolation_required=True,
        )

        # Documenter — shallow
        assignments["documenter"] = self._make_role("documenter", "shallow", "documenter")

        return assignments

    def _make_role(
        self,
        role: str,
        tier: str,
        system_prompt_key: str,
        isolation_required: bool = False,
    ) -> RoleAssignment:
        # ROLE_MIN_TIER 강제
        min_tier = ROLE_MIN_TIER.get(role, tier)
        effective_tier = self._max_tier(tier, min_tier)
        if role in VALIDATION_ROLES:
            if role == "cross_model_verifier" or effective_tier == "critical":
                model = VALIDATION_MODEL
                effort = "none"
                cost_multiplier = VALIDATION_COST_MULTIPLIER
            else:
                model, effort = TIER_BASE_MODEL[effective_tier]
                cost_multiplier = TIER_COST_MULTIPLIER[effective_tier]
        else:
            model, effort = TIER_BASE_MODEL[effective_tier]
            cost_multiplier = TIER_COST_MULTIPLIER[effective_tier]
        return RoleAssignment(
            role=role,
            model=model,
            effort=effort,
            tier=effective_tier,
            cost_multiplier=cost_multiplier,
            system_prompt_key=system_prompt_key,
            isolation_required=isolation_required,
        )

    @staticmethod
    def _max_tier(t1: str, t2: str) -> str:
        order = {"shallow": 0, "standard": 1, "deep": 2, "critical": 3}
        return t1 if order[t1] >= order[t2] else t2

    def _recommend_cross_model(self, quality: str, complexity: str, domain: str) -> CrossModelRecommendation:
        """Cross-model verifier 추천 매트릭스 적용. first-match wins."""
        for q_rule, comp_set, dom_set, level in CROSS_MODEL_RULES:
            q_match = (q_rule == "any") or (q_rule == "critical" and quality == "critical") or (q_rule == "non_critical" and quality != "critical")
            c_match = ("any" in comp_set) or (complexity in comp_set)
            d_match = ("any" in dom_set) or (domain in dom_set)
            if q_match and c_match and d_match:
                return CrossModelRecommendation(
                    level=level,
                    model=VALIDATION_MODEL,
                    effort="none",
                    reason=f"quality={quality}, complexity={complexity}, domain={domain} → {level}",
                    auto_attach=(level == "STRONG"),
                )
        return CrossModelRecommendation(level="NONE", reason="no rule matched", auto_attach=False)

    def _estimate_cost(self, plan: ModelRoutingPlan) -> float:
        """시연 1회 추정 비용 (USD). deep 모델 1회 호출 ~$0.05 기준 어림."""
        if plan.deterministic_mode:
            return 0.0
        # 추정: 각 역할이 평균 1회 호출, Codex deep 1.0x = $0.05
        BASE_OPUS_CALL = 0.05
        total = 0.0
        for assignment in plan.role_assignments.values():
            total += BASE_OPUS_CALL * assignment.cost_multiplier
        if plan.cross_model.auto_attach:
            total += BASE_OPUS_CALL * VALIDATION_COST_MULTIPLIER  # independent critic validation
        return round(total, 3)


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    """compliance-sentinel model-router plan "<text>" """
    import argparse
    import json
    import os

    from .router import Router

    parser = argparse.ArgumentParser(description="Compliance Sentinel Model Router")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="입력에서 라우팅 결정 → 모델 plan 생성")
    p_plan.add_argument("text", help="분석할 텍스트")
    p_plan.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "plan":
        from .llm_client import has_any_provider_credentials

        det = os.environ.get("CS_DETERMINISTIC_MODE") == "1" or os.environ.get("CS_ENABLE_LLM_RUNTIME") != "1" or not has_any_provider_credentials()
        router = Router()
        decision = router.classify(args.text)
        mr = ModelRouter(deterministic_mode=det)
        plan = mr.plan_from_decision(decision.to_dict())
        if args.json:
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"domain:       {plan.domain}")
            print(f"complexity:   {plan.complexity}")
            print(f"quality:      {plan.quality}")
            print(f"base_tier:    {plan.base_tier}")
            print(f"deterministic: {plan.deterministic_mode}")
            print(f"est_cost:     ${plan.estimated_cost_usd}")
            print()
            print("role assignments:")
            for role, a in plan.role_assignments.items():
                isolation = " [ISOLATED]" if a.isolation_required else ""
                print(f"  {role:25s} → {a.model} effort={a.effort} tier={a.tier} (×{a.cost_multiplier}){isolation}")
            print()
            print(f"cross_model:  level={plan.cross_model.level}, auto_attach={plan.cross_model.auto_attach}")
            if plan.cross_model.reason:
                print(f"              reason: {plan.cross_model.reason}")
        return 0

    parser.error(f"unknown command: {args.cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
