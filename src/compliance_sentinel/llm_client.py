"""LLM Client — provider-agnostic SDK wrapper with deterministic fallback.

원칙:
  - **deterministic 우선**: CS_DETERMINISTIC_MODE=1 또는 호출 대상 provider API key 부재 시
    LLM 호출은 silent skip되고 caller에게 fallback 결과 반환 — Board는 deterministic fallback 사용.
  - **Builder ≠ Verifier 격리**: call() 호출 시 role 매개변수로 system_prompt 자동 선택.
    같은 모델이라도 별도 컨텍스트 + 다른 system prompt.
  - **Budget guard 통합**: 매 호출마다 비용 추정 + 한도 초과 시 차단.
  - **agent-model-guard 통합**: 역할별 tier/critic route 위반 시 RuntimeError.
  - **Provider 다양화**: OpenAI, Anthropic, Google Gemini, OpenRouter/Groq/Together/
    Fireworks/DeepSeek/Ollama/custom OpenAI-compatible endpoint를 모델 prefix/env로 선택.

API key 없이도 import + class 인스턴스 생성 + deterministic_mode 판정까지는 동작.
실제 호출 시점에 provider를 사용할 수 없으면 deterministic fallback 결과를 반환.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .skill_injection import load_injected_skill_context

SYSTEM_PROMPTS_DIR = Path(__file__).resolve().parent / "system_prompts"

# SDK는 optional. 부재 시 해당 provider만 deterministic fallback.
try:  # pragma: no cover - optional dependency
    from openai import OpenAI  # type: ignore
    _HAS_OPENAI = True
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore
    _HAS_OPENAI = False

try:  # pragma: no cover - optional dependency
    from anthropic import Anthropic  # type: ignore
    _HAS_ANTHROPIC = True
except Exception:  # pragma: no cover
    Anthropic = None  # type: ignore
    _HAS_ANTHROPIC = False

try:  # pragma: no cover - optional dependency
    from google import genai as _google_genai  # type: ignore
    _HAS_GOOGLE_GENAI = True
except Exception:  # pragma: no cover
    _google_genai = None  # type: ignore
    _HAS_GOOGLE_GENAI = False


OPENAI_COMPATIBLE_PROVIDERS = {
    "openai": {"key_env": ("OPENAI_API_KEY",), "base_url": None},
    "codex": {"key_env": ("CODEX_API_KEY", "OPENAI_API_KEY"), "base_url": None},
    "openrouter": {"key_env": ("OPENROUTER_API_KEY",), "base_url": "https://openrouter.ai/api/v1"},
    "groq": {"key_env": ("GROQ_API_KEY",), "base_url": "https://api.groq.com/openai/v1"},
    "together": {"key_env": ("TOGETHER_API_KEY",), "base_url": "https://api.together.xyz/v1"},
    "fireworks": {"key_env": ("FIREWORKS_API_KEY",), "base_url": "https://api.fireworks.ai/inference/v1"},
    "deepseek": {"key_env": ("DEEPSEEK_API_KEY",), "base_url": "https://api.deepseek.com"},
    "ollama": {"key_env": (), "base_url_env": "OLLAMA_BASE_URL", "base_url": "http://localhost:11434/v1"},
    "custom": {"key_env": ("CS_LLM_API_KEY",), "base_url_env": "CS_LLM_BASE_URL", "base_url": None},
}

KNOWN_PROVIDER_PREFIXES = set(OPENAI_COMPATIBLE_PROVIDERS) | {"anthropic", "claude", "google", "gemini"}

BOARD_PERSONA_PROFILES: dict[str, dict[str, str]] = {
    "board_member": {
        "persona_id": "board-member",
        "persona_role": "Generic Compliance Board Member",
        "persona_focus": "한국 금융 마케팅 콘텐츠 준법 리스크를 근거 기반으로 검토",
        "persona_questions": "검색된 근거가 충분한가? 소비자 오인 가능성이 있는가? human review가 필요한가?",
        "persona_critical_rules": "근거 없는 법령 인용 금지; PII/secret 원문 보존 금지; 법률 자문이 아닌 준법 검토 보조로 한정",
    },
    "legal_counsel": {
        "persona_id": "legal-counsel",
        "persona_role": "Legal Counsel",
        "persona_focus": "금융소비자보호법, 표시광고, 약관, 전자금융, 계약 문구의 법적 명확성",
        "persona_questions": "이 문구가 법령·약관·내부 기준과 충돌하는가? 인용 가능한 근거가 있는가? 수정안에 조건·한도·예외가 명확한가?",
        "persona_critical_rules": "검색된 citation 밖의 조문을 만들지 말 것; 최종 법률 자문처럼 단정하지 말 것; HIGH 이상은 근거와 함께 HITL 권고",
    },
    "pipa_expert": {
        "persona_id": "pipa-credit-info-expert",
        "persona_role": "PIPA / Credit Info Expert",
        "persona_focus": "개인정보보호법, 신용정보법, 동의, 제3자 제공, 보유기간, 목적 제한, 민감정보/식별자 보호",
        "persona_questions": "개인정보·개인신용정보를 수집/이용/제공하는가? 별도 동의와 목적·보유기간 고지가 충분한가? 마케팅 활용이 최소필요 원칙을 넘는가?",
        "persona_critical_rules": "PII 원문을 출력하지 말 것; 동의 누락/제3자 제공/보유기간 불명확은 HIGH 이상으로 보수 판단; 데이터 활용과 광고 표현을 분리 검토",
    },
    "consumer_protection": {
        "persona_id": "consumer-protection-expert",
        "persona_role": "Consumer Protection Expert",
        "persona_focus": "금융소비자 오인, 과장광고, 보장/무위험/확정수익/승인보장 표현, 필수 고지 누락",
        "persona_questions": "소비자가 수익·승인·위험·조건을 오인할 수 있는가? 필수 고지가 누락되었는가? 더 안전한 대체 문구는 무엇인가?",
        "persona_critical_rules": "원금보장·무위험·100%승인·무조건 혜택은 기본 HIGH/CRITICAL 후보; 수정안에는 조건·한도·위험 고지를 포함",
    },
    "operational_risk": {
        "persona_id": "aml-operational-risk-expert",
        "persona_role": "AML / Operational Risk Expert",
        "persona_focus": "전자금융, 접근권한, 보안, 거래 모니터링, AML/CFT, 운영 리스크와 마케팅 실행 리스크",
        "persona_questions": "광고/랜딩이 고객 행동을 위험한 거래·권한·보안 우회로 유도하는가? 운영 프로세스가 약속한 혜택을 통제할 수 있는가? AML/전자금융 리스크가 있는가?",
        "persona_critical_rules": "실거래 실행·인증·권한·보안 약속은 운영 통제 근거 없이는 보수 판단; 고객 행동 유도 문구의 abuse path를 검토",
    },
    "business_practicality": {
        "persona_id": "business-practicality-expert",
        "persona_role": "Business Practicality Expert",
        "persona_focus": "마케팅 실행 가능성, 과잉 차단 방지, 수정 후 승인 가능성, 업무 SLA와 제작 프로세스 연계",
        "persona_questions": "위험을 낮추면서 캠페인 목적을 유지할 수 있는 수정안은 무엇인가? 과잉 해석인가? 승인 가능한 최소 수정 범위는 무엇인가?",
        "persona_critical_rules": "준법 리스크를 낮추되 무조건 반려하지 말 것; safe alternative와 workflow action을 제시; 근거가 약하면 human review로 넘김",
    },
    "contrarian": {
        "persona_id": "contrarian-agent",
        "persona_role": "Contrarian / Skeptical Reviewer",
        "persona_focus": "보드 단일 사고 방지, 과소탐지와 과잉차단 모두에 대한 반례, 근거 공백과 불확실성 검출",
        "persona_questions": "다수 의견이 놓친 반례는 무엇인가? 이 판단이 과잉 차단 또는 과소 탐지일 수 있는가? 추가 근거 없이는 단정할 수 없는 부분은 무엇인가?",
        "persona_critical_rules": "무조건 반대가 아니라 증거 기반 반대; 확신 부족·근거 공백·minority risk를 명확히 표시; 필요 시 HITL 권고",
    },
}


def _render_persona_prompt(role: str, template: str) -> str:
    profile = BOARD_PERSONA_PROFILES.get(role)
    if not profile:
        return template
    rendered = template
    for key, value in profile.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    rendered = rendered.replace(
        "{{persona_questions}}",
        profile.get("persona_questions", "근거, 리스크, 수정안, human review 필요성을 검토합니다."),
    )
    if "{{" not in rendered:
        return rendered
    # Defensive cleanup for future placeholders: keep prompts production-safe rather
    # than leaking template syntax to live LLM calls.
    return rendered.replace("{{persona_role}}", profile["persona_role"]).replace("{{persona_focus}}", profile["persona_focus"])


@dataclass
class LLMCallResult:
    text: str
    model: str
    role: str
    deterministic_fallback: bool = False
    estimated_cost_usd: float = 0.0
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    # prompt caching 측정 (OpenAI 자동 캐싱 hit 추적). cached_tokens는 prompt_tokens 중
    # 캐시에서 재사용된 입력 토큰 수 (50% 할인 대상). prompt caching 미적용 provider는 0.
    cached_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMClientError(Exception):
    pass


def _extract_openai_usage(response: Any) -> dict:
    """OpenAI 응답 usage에서 prompt caching 측정값을 추출한다.

    OpenAI는 1024토큰+ prefix를 자동 캐시하고 usage.prompt_tokens_details.cached_tokens로
    실제 hit량을 보고한다. 이 값으로 자동 prompt caching이 실제 작동하는지 검증 가능.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) if details is not None else 0
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "cached_tokens": int(cached or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
    }


def _first_env(names: tuple[str, ...] | list[str]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def split_provider_model(model: str) -> tuple[str, str]:
    """Return ``(provider, api_model)`` from a model id.

    Supported forms:
      - ``gpt-4o`` → (openai, gpt-4o)
      - ``openai/gpt-4o`` → (openai, gpt-4o)
      - ``anthropic/claude-3-5-sonnet-latest`` → (anthropic, claude-...)
      - ``google/gemini-1.5-pro`` → (google, gemini-...)
      - ``openrouter/anthropic/claude-3.5-sonnet`` → (openrouter, anthropic/claude-...)
    """

    if "/" in model:
        provider, api_model = model.split("/", 1)
        if provider in KNOWN_PROVIDER_PREFIXES:
            provider = "anthropic" if provider == "claude" else provider
            provider = "google" if provider == "gemini" else provider
            return provider, api_model
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai", model
    if model.startswith("claude-"):
        return "anthropic", model
    if model.startswith("gemini-"):
        return "google", model
    if os.environ.get("CS_LLM_BASE_URL"):
        return "custom", model
    return "openai", model


def provider_has_credentials(provider: str) -> bool:
    """Return whether the provider has SDK/env needed for a live call."""

    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        if not _HAS_OPENAI:
            return False
        cfg = OPENAI_COMPATIBLE_PROVIDERS[provider]
        base_url = os.environ.get(str(cfg.get("base_url_env", ""))) or cfg.get("base_url")
        if provider in {"ollama"}:
            return bool(base_url)
        return bool(_first_env(tuple(cfg.get("key_env", ())))) and bool(base_url or provider in {"openai", "codex"})
    if provider == "anthropic":
        return _HAS_ANTHROPIC and bool(os.environ.get("ANTHROPIC_API_KEY"))
    if provider == "google":
        return _HAS_GOOGLE_GENAI and bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
    return False


def has_any_provider_credentials() -> bool:
    """Return true if any supported provider can make live calls."""

    return any(provider_has_credentials(provider) for provider in sorted(KNOWN_PROVIDER_PREFIXES - {"claude", "gemini"}))


def is_model_available(model: str) -> bool:
    provider, _ = split_provider_model(model)
    return provider_has_credentials(provider)


def is_deterministic_mode() -> bool:
    """결정론적 모드 여부.

    - CS_DETERMINISTIC_MODE=1 명시 설정 시 True
    - CS_ENABLE_LLM_RUNTIME=1 이 아니면 자동 True (비용/비밀키 안전 기본값)
    - 지원 provider SDK/API key가 모두 없으면 자동 True
    """
    if os.environ.get("CS_DETERMINISTIC_MODE") == "1":
        return True
    if os.environ.get("CS_ENABLE_LLM_RUNTIME") != "1":
        return True
    return not has_any_provider_credentials()


def load_system_prompt(role: str) -> str:
    """role별 system prompt 파일 로드. 부재 시 RuntimeError.

    role 매핑:
      ceo_synthesizer → ceo_synthesizer.md (alias for builder)
      verifier → verifier.md
      board_member → board_member.md
      classifier → classifier.md
      documenter → documenter.md
      cross_model_verifier → codex_verifier.md
      adversarial_critic/independent_validator → verifier/codex_verifier.md
      builder → builder.md
    """
    role_to_file = {
        "ceo_synthesizer": "ceo_synthesizer.md",
        "verifier": "verifier.md",
        "board_member": "board_member.md",
        "classifier": "classifier.md",
        "triage": "triage.md",
        "documenter": "documenter.md",
        "cross_model_verifier": "codex_verifier.md",
        "adversarial_critic": "verifier.md",
        "independent_validator": "codex_verifier.md",
        "builder": "builder.md",
        "marketing_rewriter": "marketing_rewriter.md",
        "marketing_risk_scanner": "marketing_risk_scanner.md",
        # 광고 원고 제안/검토 에이전트 — marketing_rewriter 템플릿 재사용 + role별 SKILL 주입(skill_injection)
        "ad_copy_proposer": "marketing_rewriter.md",
        "ad_copy_reviewer": "marketing_rewriter.md",
        # 6인 보드 페르소나 — 공통 prompt template + role-specific profile rendering
        "legal_counsel": "board_member.md",
        "pipa_expert": "board_member.md",
        "consumer_protection": "board_member.md",
        "operational_risk": "board_member.md",
        "business_practicality": "board_member.md",
        "contrarian": "board_member.md",
    }
    fname = role_to_file.get(role)
    if not fname:
        raise LLMClientError(f"unknown role: {role}")
    path = SYSTEM_PROMPTS_DIR / fname
    if not path.exists():
        raise LLMClientError(f"system prompt missing: {path}")
    template = path.read_text(encoding="utf-8")
    return _render_persona_prompt(role, template) + load_injected_skill_context(role)


class LLMClient:
    """Thin wrapper. deterministic_mode이면 모든 call() → LLMCallResult(deterministic_fallback=True)."""

    def __init__(self, *, budget_guard=None, model_guard=None) -> None:
        self.deterministic = is_deterministic_mode()
        self.budget_guard = budget_guard
        self.model_guard = model_guard
        self._provider_clients: dict[str, Any] = {}
        self._init_error: str | None = None
        # 노드별 cost attribution용 실측 call 로그 (node_cost_tracker가 인덱스 델타로 집계).
        self.call_log: list[dict] = []
        if not self.deterministic and not has_any_provider_credentials():
            self.deterministic = True

    def _openai_compatible_client(self, provider: str) -> Any:
        if provider in self._provider_clients:
            return self._provider_clients[provider]
        if not _HAS_OPENAI:
            raise LLMClientError("openai SDK unavailable for OpenAI-compatible provider")
        cfg = OPENAI_COMPATIBLE_PROVIDERS[provider]
        api_key = _first_env(tuple(cfg.get("key_env", ()))) or "ollama"
        base_url = os.environ.get(str(cfg.get("base_url_env", ""))) or cfg.get("base_url")
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)  # type: ignore[misc]
        self._provider_clients[provider] = client
        return client

    @staticmethod
    def _reasoning_effort_for_model(model: str, effort: str) -> str | None:
        if not model.startswith("gpt-5"):
            return None
        normalized = (effort or "none").lower()
        if normalized in {"none", "low", "medium", "high"}:
            return normalized
        if normalized in {"xhigh", "critical"}:
            return "high"
        return "medium"

    def _call_openai_compatible(
        self,
        provider: str,
        model: str,
        system_prompt: str,
        user_text: str,
        *,
        max_tokens: int,
        effort: str = "none",
        response_format: dict | None = None,
    ) -> tuple[str, dict]:
        # gpt-5 계열은 reasoning 모델 — 추론 토큰이 max_completion_tokens 한도에 포함된다.
        # 4096으론 추론 도중 한도가 소진되어 응답을 끝내지 못하고 "Could not finish the
        # message" 400이 간헐 발생한다. max_tokens는 상한일 뿐 실제 출력량만 과금되므로
        # 상향해도 비용은 증가하지 않는다.
        if "gpt-5" in model.lower():
            max_tokens = max(max_tokens, 32000)
        client = self._openai_compatible_client(provider)
        request: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        }
        # 명시적 standard tier 강제 (priority tier 자동 사용 차단)
        # - OpenAI 계정/조직 default가 priority면 호출당 2배 가격 청구됨
        # - service_tier="default" 명시 시 standard pricing 강제
        # - groq 등 다른 OpenAI-호환 provider는 이 파라미터 받지 않으므로 openai에만 적용
        if provider == "openai":
            request["service_tier"] = "default"
        if response_format is not None:
            request["response_format"] = response_format
        reasoning_effort = self._reasoning_effort_for_model(model, effort)
        token_params = ("max_completion_tokens", "max_tokens") if model.startswith("gpt-5") else ("max_tokens", "max_completion_tokens")
        last_error: Exception | None = None
        for include_reasoning in (True, False):
            candidate = dict(request)
            if include_reasoning and reasoning_effort:
                candidate["reasoning_effort"] = reasoning_effort
            for token_param in token_params:
                try:
                    response = client.chat.completions.create(**candidate, **{token_param: max_tokens})
                    return (response.choices[0].message.content or ""), _extract_openai_usage(response)
                except Exception as exc:
                    message = str(exc)
                    last_error = exc
                    if include_reasoning and "reasoning_effort" in message:
                        break
                    if "max_tokens" in message and "max_completion_tokens" in message:
                        continue
                    raise
        if last_error is not None:
            raise last_error
        raise LLMClientError("OpenAI-compatible request failed without an exception")

    def _call_anthropic(self, model: str, system_prompt: str, user_text: str, *, max_tokens: int) -> str:
        if "anthropic" not in self._provider_clients:
            if not _HAS_ANTHROPIC:
                raise LLMClientError("anthropic SDK unavailable")
            self._provider_clients["anthropic"] = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])  # type: ignore[misc]
        client = self._provider_clients["anthropic"]
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_text}],
        )
        chunks = []
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                chunks.append(text)
        return "\n".join(chunks)

    def _call_google(self, model: str, system_prompt: str, user_text: str, *, max_tokens: int) -> str:
        if "google" not in self._provider_clients:
            if not _HAS_GOOGLE_GENAI:
                raise LLMClientError("google-genai SDK unavailable")
            api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
            self._provider_clients["google"] = _google_genai.Client(api_key=api_key)  # type: ignore[union-attr]
        client = self._provider_clients["google"]
        try:
            response = client.models.generate_content(
                model=model,
                contents=user_text,
                config={"system_instruction": system_prompt, "max_output_tokens": max_tokens},
            )
        except TypeError:
            response = client.models.generate_content(
                model=model,
                contents=f"{system_prompt}\n\n{user_text}",
            )
        return getattr(response, "text", "") or ""

    def call(
        self,
        role: str,
        user_text: str,
        *,
        model: str,
        effort: str = "none",
        max_tokens: int = 4096,
        estimated_cost_usd: float = 0.05,
        response_format: dict | None = None,
    ) -> LLMCallResult:
        """role에 맞는 system_prompt + user_text로 LLM 호출.

        Builder ≠ Verifier 격리: role 따라 system_prompt 자동 선택.
        """
        # agent-model-guard 검증 (역할별 tier/critic route pin)
        if self.model_guard is not None:
            self.model_guard.check(role=role, model=model)

        if self.deterministic:
            return LLMCallResult(
                text="",
                model=model,
                role=role,
                deterministic_fallback=True,
                error=None,
                metadata={"reason": "CS_DETERMINISTIC_MODE or no matching API key"},
            )

        # BG Phase B (spec/budget-guard-enforcement.md BG-101): 4-tier check_before_call
        budget_tier = None
        if self.budget_guard is not None:
            budget_tier = self.budget_guard.check_tier(estimated_cost_usd)
            session_pct = round(
                (self.budget_guard.session_spent_usd + estimated_cost_usd)
                / max(self.budget_guard.per_demo_limit_usd, 0.0001) * 100, 1
            )
            # tier=red 또는 blocked 시 deterministic fallback (사전 차단)
            if budget_tier in ("red", "blocked"):
                return LLMCallResult(
                    text="",
                    model=model,
                    role=role,
                    deterministic_fallback=True,
                    error="budget_exceeded" if budget_tier == "blocked" else "budget_fallback_red",
                    metadata={
                        "reason": f"budget guard tier={budget_tier} (session {session_pct:.1f}%)",
                        "budget_tier": budget_tier,
                        "session_percentage": session_pct,
                    },
                )
            # tier=yellow 시 warning 로그 (stderr) — 진행은 함
            if budget_tier == "yellow":
                import sys
                print(
                    f"⚠️ budget yellow tier (session {session_pct:.1f}%): role={role} model={model} est_cost=${estimated_cost_usd:.4f}",
                    file=sys.stderr,
                )

        system_prompt = load_system_prompt(role)

        try:  # pragma: no cover - 외부 API 호출, 단위 테스트에서는 deterministic_mode로 우회
            provider, api_model = split_provider_model(model)
            if not provider_has_credentials(provider):
                raise LLMClientError(f"provider unavailable or missing credentials: {provider}")
            usage: dict = {}
            if provider in OPENAI_COMPATIBLE_PROVIDERS:
                text, usage = self._call_openai_compatible(
                    provider,
                    api_model,
                    system_prompt,
                    user_text,
                    max_tokens=max_tokens,
                    effort=effort,
                    response_format=response_format,
                )
            elif provider == "anthropic":
                text = self._call_anthropic(api_model, system_prompt, user_text, max_tokens=max_tokens)
            elif provider == "google":
                text = self._call_google(api_model, system_prompt, user_text, max_tokens=max_tokens)
            else:
                raise LLMClientError(f"unknown provider for model: {model}")
        except Exception as e:
            return LLMCallResult(
                text="",
                model=model,
                role=role,
                deterministic_fallback=True,
                error=str(e),
            )

        # 비용 기록
        if self.budget_guard is not None:
            self.budget_guard.record_spend(estimated_cost_usd, role=role, model=model)

        result = LLMCallResult(
            text=text,
            model=model,
            role=role,
            deterministic_fallback=False,
            estimated_cost_usd=estimated_cost_usd,
            cached_tokens=int(usage.get("cached_tokens", 0)),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        )
        # 노드별 cost attribution: 실측 call 1건 기록 (deterministic/error 경로는 미기록 = 비용 0).
        self.call_log.append({
            "model": model,
            "role": role,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cached_tokens": result.cached_tokens,
            "estimated_cost_usd": estimated_cost_usd,
        })
        return result
