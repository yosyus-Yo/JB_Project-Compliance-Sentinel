"""Cross-Model Verifier independent validation wrapper.

목적:
  primary route의 컨텍스트 blind spot을 별도 CS_MODEL_CRITIC 컨텍스트로 cross-check.

활성 조건:
  - ModelRouter.plan.cross_model.level == "STRONG" (quality=critical 자동 부착)
  - 사용자 명시 --codex-review/--with-review 계열

작동:
  - CS_MODEL_CRITIC + matching provider key + CS_ENABLE_LLM_RUNTIME=1 설정 시 실제 호출
  - 부재 시 silent skip (advisory 텍스트만 반환)

출처:
  - SEAS auto-attach-codex-review.ts
  - workflows/cs-model-routing.yaml cross_model_attach_rules
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from .llm_client import LLMClient, is_deterministic_mode, is_model_available
from .model_router import CRITIC_PROVIDER_PREFIXES, current_critic_model


# cross-model critic으로 허용되는 강한 Anthropic 모델 (약한 haiku는 제외).
_STRONG_ANTHROPIC_CRITICS = frozenset({"claude-opus-4-8", "claude-sonnet-5", "claude-sonnet-4-6"})


def _default_cross_model() -> str:
    # cross-model critic은 강한 모델로 강제 (안전장치) — primary와 다른 강한 모델로
    # blind spot 교차검증해야 의미가 있으므로 약한 모델 설정은 차단한다.
    model = current_critic_model()
    # 허용: gpt-5.5 계열 · 강한 Claude(opus/sonnet) · provider(openrouter/anthropic) 모델.
    # 약한 OpenAI(gpt-5.4-mini/nano)·Claude haiku는 cross-check blind spot 검증에 부적합해 차단.
    if (
        "gpt-5.5" not in model
        and not model.startswith(CRITIC_PROVIDER_PREFIXES)
        and model not in _STRONG_ANTHROPIC_CRITICS
    ):
        raise ValueError(
            f"cross-model critic은 gpt-5.5 계열 / Claude opus·sonnet / provider 모델이어야 합니다 (현재: {model}). "
            "CS_MODEL_CRITIC을 강한 모델(gpt-5.5, claude-opus-4-8, openrouter/anthropic 등)로 설정하세요."
        )
    return model


# 모듈 로드 시점에는 검증을 우회 (잘못된 CS_MODEL_CRITIC env가 import 자체를 깨지 않도록).
# 실제 cross-model 사용 경로는 _default_cross_model()을 호출해 검증을 받는다.
DEFAULT_CROSS_MODEL = current_critic_model()


@dataclass
class CrossModelResult:
    enabled: bool
    cross_model_confidence: str  # PERFECT|VERIFIED|PARTIAL|FEEDBACK|FAILED|SKIPPED
    agreed_findings: list[str] = field(default_factory=list)
    disputed_findings: list[dict] = field(default_factory=list)
    blind_spots_caught: list[str] = field(default_factory=list)
    recommendation: str = "skipped"  # ship_ok | human_review_recommended | skipped
    error: Optional[str] = None
    deterministic_fallback: bool = False
    estimated_cost_usd: float = 0.0


def is_enabled(model: str | None = None) -> bool:
    """Cross-model 활성 조건.

    - deterministic 모드 → 비활성
    - 모델 provider SDK/API key 필요
    """
    if is_deterministic_mode():
        return False
    return is_model_available(model or _default_cross_model())


def verify(
    builder_output: dict,
    verifier_output: list[dict],
    *,
    model: str | None = None,
    effort: str = "none",
    llm_client: LLMClient | None = None,
    estimated_cost_usd: float = 0.05,
) -> CrossModelResult:
    """Builder finding + primary verifier 결과를 받아 독립 critic 컨텍스트로 cross-check.

    deterministic_fallback 시 CrossModelResult(enabled=False, ...) 반환.
    """
    selected_model = model or _default_cross_model()
    if not is_enabled(selected_model):
        return CrossModelResult(
            enabled=False,
            cross_model_confidence="SKIPPED",
            recommendation="skipped",
            deterministic_fallback=True,
            error="cross-model 비활성 (deterministic mode 또는 provider SDK/API key 부재)",
        )

    # pragma: no cover — 실제 API 호출 경로
    try:
        user_text = (
            "Return only compact JSON. Do not include markdown, prose, or citations outside JSON.\n"
            + json.dumps({
                "builder_output": builder_output,
                "verifier_output": verifier_output,
                "effort": effort,
                "output_contract": {
                    "cross_model_confidence": "PERFECT|VERIFIED|PARTIAL|FEEDBACK|FAILED",
                    "agreed_findings": [],
                    "disputed_findings": [],
                    "blind_spots_caught": [],
                    "recommendation": "ship_ok|human_review_recommended|skipped",
                },
            }, ensure_ascii=False, indent=2)
        )
        client = llm_client or LLMClient()
        result = client.call(
            "cross_model_verifier",
            user_text,
            model=selected_model,
            effort=effort,
            max_tokens=1536,
            estimated_cost_usd=estimated_cost_usd,
            response_format={"type": "json_object"},
        )
        if result.deterministic_fallback or result.error:
            return CrossModelResult(
                enabled=False,
                cross_model_confidence="SKIPPED",
                recommendation="skipped",
                deterministic_fallback=True,
                error=result.error or "provider fallback",
                estimated_cost_usd=result.estimated_cost_usd or estimated_cost_usd,
            )
        raw = result.text or "{}"
        parsed = json.loads(raw)
        return CrossModelResult(
            enabled=True,
            cross_model_confidence=parsed.get("cross_model_confidence", "PARTIAL"),
            agreed_findings=parsed.get("agreed_findings", []),
            disputed_findings=parsed.get("disputed_findings", []),
            blind_spots_caught=parsed.get("blind_spots_caught", []),
            recommendation=parsed.get("recommendation", "human_review_recommended"),
            estimated_cost_usd=result.estimated_cost_usd or estimated_cost_usd,
        )
    except Exception as e:
        return CrossModelResult(
            enabled=True,
            cross_model_confidence="SKIPPED",
            recommendation="skipped",
            error=str(e),
            estimated_cost_usd=estimated_cost_usd,
        )
