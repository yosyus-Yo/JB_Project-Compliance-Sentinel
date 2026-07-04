"""Agent Model Guard — 역할별 모델 hard route 강제.

목적 (LP-CS-030 확장, 2026-07-03 Anthropic 확장):
  tier별 허용 모델 family만 허용한다 — 기본 Anthropic Claude(haiku/sonnet/opus) +
  OpenAI gpt-5.x tier도 env override로 허용. tier 등가를 벗어난 downgrade는 차단한다.
  저비용/빠른 경로, 일반 보드 경로, 심층 주 작업, 검증/비평 경로를 분리한다.
  비용 절감 의도로 검증자를 shallow/standard 모델로 내리거나 역할별 격리를 깨는 회귀를 차단한다.
  본 guard가 런타임에 매 LLM 호출 직전에 model을 검사 → 위반 시 RuntimeError.

설계:
  - **Hard pin** — CS_BYPASS_MODEL_GUARD=1 환경변수로만 우회 가능, 사용 시 stderr 경고
  - **테스트 가능** — 외부 환경변수 의존성 분리, 인스턴스화 시 설정 freeze
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

MODEL_NANO = "gpt-5.4-nano"
MODEL_MINI = "gpt-5.4-mini"
MODEL_DEEP = "gpt-5.5"

# 2026-07-03: Anthropic Claude 기본 경로 허용 (사용자 ANTHROPIC_API_KEY 6인 보드).
# tier 등가: haiku=shallow, sonnet=standard/board, opus=deep/critical.
# 검증자 downgrade 차단 원칙 유지 — board/verifier는 sonnet 이상만, critical은 opus만 허용.
MODEL_HAIKU = "claude-haiku-4-5"
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_SONNET5 = "claude-sonnet-5"
MODEL_OPUS = "claude-opus-4-8"

ANTHROPIC_SHALLOW = {MODEL_HAIKU, MODEL_SONNET, MODEL_SONNET5, MODEL_OPUS}
ANTHROPIC_BOARD = {MODEL_SONNET, MODEL_SONNET5, MODEL_OPUS}
ANTHROPIC_DEEP = {MODEL_OPUS}

PRIMARY_OPENAI_MODELS = {MODEL_NANO, MODEL_MINI, MODEL_DEEP}
CRITIC_PROVIDER_PREFIXES = ("openrouter/anthropic/", "anthropic/claude-")
FAST_PRIMARY_MODELS = {MODEL_NANO, MODEL_MINI, MODEL_DEEP} | ANTHROPIC_SHALLOW
BOARD_PRIMARY_MODELS = {MODEL_MINI, MODEL_DEEP} | ANTHROPIC_BOARD
SYNTHESIS_MODELS = {MODEL_MINI, MODEL_DEEP} | ANTHROPIC_BOARD
VALIDATION_MODELS = {MODEL_MINI, MODEL_DEEP} | ANTHROPIC_BOARD
CRITICAL_VALIDATION_MODELS = {MODEL_DEEP} | ANTHROPIC_DEEP

ROLE_ALLOWED_MODELS = {
    "classifier": FAST_PRIMARY_MODELS,
    "documenter": FAST_PRIMARY_MODELS,
    "legal_counsel": BOARD_PRIMARY_MODELS,
    "pipa_expert": BOARD_PRIMARY_MODELS,
    "consumer_protection": BOARD_PRIMARY_MODELS,
    "operational_risk": BOARD_PRIMARY_MODELS,
    "business_practicality": BOARD_PRIMARY_MODELS,
    "contrarian": BOARD_PRIMARY_MODELS,
    "board_member": BOARD_PRIMARY_MODELS,
    "ceo_synthesizer": SYNTHESIS_MODELS,
    # Non-critical validation can use mini; cross-model validation remains deep.
    "verifier": VALIDATION_MODELS,
    "adversarial_critic": VALIDATION_MODELS,
    "independent_validator": VALIDATION_MODELS,
    "cross_model_verifier": CRITICAL_VALIDATION_MODELS,
}


def _env_model_set(*names: str) -> set[str]:
    return {
        os.environ[name]
        for name in names
        if os.environ.get(name) in PRIMARY_OPENAI_MODELS
    }


def _critic_env_model_set(*names: str) -> set[str]:
    out: set[str] = set()
    for name in names:
        value = os.environ.get(name, "").strip()
        if value in PRIMARY_OPENAI_MODELS or value.startswith(CRITIC_PROVIDER_PREFIXES):
            out.add(value)
    return out


SHALLOW_ENV_NAMES = ("CS_MODEL_SHALLOW", "CS_MODEL_OPENAI_NANO")
STANDARD_ENV_NAMES = ("CS_MODEL_STANDARD", "CS_MODEL_CODEX_MINI")
DEEP_ENV_NAMES = ("CS_MODEL_DEEP", "CS_MODEL_CODEX_DEEP")
CRITIC_ENV_NAMES = ("CS_MODEL_CRITIC",)


def allowed_models_for_role(role: str) -> set[str] | None:
    """Return allowed models, including UI-configured route models.

    Defaults keep the original hard pins. UI-selected models are allowed only for
    their matching tier so validation cannot silently downgrade to shallow/mini.
    """
    if role in {"classifier", "documenter"}:
        return FAST_PRIMARY_MODELS | _env_model_set(*SHALLOW_ENV_NAMES, *STANDARD_ENV_NAMES, *DEEP_ENV_NAMES)
    if role in {
        "legal_counsel", "pipa_expert", "consumer_protection", "operational_risk",
        "business_practicality", "contrarian", "board_member",
    }:
        return BOARD_PRIMARY_MODELS
    if role == "ceo_synthesizer":
        return SYNTHESIS_MODELS
    if role == "cross_model_verifier":
        return CRITICAL_VALIDATION_MODELS | _critic_env_model_set(*CRITIC_ENV_NAMES)
    if role in {"verifier", "adversarial_critic", "independent_validator"}:
        return VALIDATION_MODELS | _critic_env_model_set(*CRITIC_ENV_NAMES)
    return ROLE_ALLOWED_MODELS.get(role)


class ModelGuardViolation(RuntimeError):
    """Hard pin 위반 — bypass 환경변수 없으면 raise."""
    pass


@dataclass(frozen=True)
class ModelGuard:
    bypass_allowed: bool = False  # CS_BYPASS_MODEL_GUARD=1 인지 freeze 시점에 확정

    @classmethod
    def from_env(cls) -> "ModelGuard":
        return cls(bypass_allowed=os.environ.get("CS_BYPASS_MODEL_GUARD") == "1")

    def check(self, *, role: str, model: str) -> None:
        """role에 대한 model family/pin 검증. 위반 시 ModelGuardViolation 또는 stderr 경고."""
        allowed = allowed_models_for_role(role)
        if not allowed:
            return  # 본 guard가 모르는 role — pass

        if model not in allowed:
            allowed_list = ", ".join(sorted(allowed))
            msg = (
                f"🔴 Model Guard Violation: role='{role}' allows only [{allowed_list}], "
                f"got '{model}' (LP-CS-030 tier/provider routing guard)"
            )
            if self.bypass_allowed:
                print(f"⚠️  [BYPASS] {msg}", file=sys.stderr)
                return
            raise ModelGuardViolation(msg)
