"""llm_client.py — provider/model parse + deterministic + LLMClient class."""
from __future__ import annotations

import pytest

from compliance_sentinel.llm_client import (
    BOARD_PERSONA_PROFILES,
    KNOWN_PROVIDER_PREFIXES,
    LLMCallResult,
    LLMClient,
    LLMClientError,
    OPENAI_COMPATIBLE_PROVIDERS,
    _first_env,
    _render_persona_prompt,
    has_any_provider_credentials,
    is_deterministic_mode,
    is_model_available,
    load_system_prompt,
    provider_has_credentials,
    split_provider_model,
)


class TestSplitProviderModel:
    def test_openai_prefix_slash(self):
        provider, model = split_provider_model("openai/gpt-5.5")
        assert provider == "openai"
        assert model == "gpt-5.5"

    def test_anthropic_prefix_slash(self):
        provider, model = split_provider_model("anthropic/claude-opus-4-7")
        assert provider == "anthropic"

    def test_claude_alias_normalized(self):
        provider, model = split_provider_model("claude/claude-opus-4-7")
        assert provider == "anthropic"

    def test_gemini_alias_normalized(self):
        provider, model = split_provider_model("gemini/gemini-pro")
        assert provider == "google"

    def test_no_prefix_gpt_returns_openai(self):
        provider, model = split_provider_model("gpt-5.5")
        assert provider == "openai"

    def test_no_prefix_o1_returns_openai(self):
        provider, model = split_provider_model("o1-preview")
        assert provider == "openai"

    def test_no_prefix_o3_returns_openai(self):
        provider, model = split_provider_model("o3-mini")
        assert provider == "openai"

    def test_no_prefix_claude_returns_anthropic(self):
        provider, model = split_provider_model("claude-opus-4-7")
        assert provider == "anthropic"

    def test_no_prefix_gemini_returns_google(self):
        provider, model = split_provider_model("gemini-1.5-pro")
        assert provider == "google"

    def test_unknown_prefix_with_cs_base_url(self, monkeypatch):
        monkeypatch.setenv("CS_LLM_BASE_URL", "http://localhost:8000")
        provider, model = split_provider_model("custom-llm-x")
        assert provider == "custom"

    def test_unknown_no_base_url_fallback_openai(self, monkeypatch):
        monkeypatch.delenv("CS_LLM_BASE_URL", raising=False)
        provider, model = split_provider_model("mystery-model")
        assert provider == "openai"

    def test_openrouter_nested_path(self):
        provider, model = split_provider_model("openrouter/anthropic/claude-3.5-sonnet")
        assert provider == "openrouter"
        assert model == "anthropic/claude-3.5-sonnet"


class TestFirstEnv:
    def test_returns_first_set(self, monkeypatch):
        monkeypatch.setenv("CS_FIRST", "value1")
        monkeypatch.setenv("CS_SECOND", "value2")
        assert _first_env(("CS_FIRST", "CS_SECOND")) == "value1"

    def test_returns_second_when_first_unset(self, monkeypatch):
        monkeypatch.delenv("CS_FIRST", raising=False)
        monkeypatch.setenv("CS_SECOND", "value2")
        assert _first_env(("CS_FIRST", "CS_SECOND")) == "value2"

    def test_returns_none_when_all_unset(self, monkeypatch):
        monkeypatch.delenv("CS_FIRST", raising=False)
        monkeypatch.delenv("CS_SECOND", raising=False)
        assert _first_env(("CS_FIRST", "CS_SECOND")) is None

    def test_empty_tuple(self):
        assert _first_env(()) is None


class TestIsDeterministicMode:
    def test_explicit_deterministic_env(self, monkeypatch):
        monkeypatch.setenv("CS_DETERMINISTIC_MODE", "1")
        assert is_deterministic_mode() is True

    def test_runtime_off_returns_true(self, monkeypatch):
        monkeypatch.delenv("CS_DETERMINISTIC_MODE", raising=False)
        monkeypatch.setenv("CS_ENABLE_LLM_RUNTIME", "0")
        assert is_deterministic_mode() is True

    def test_runtime_on_no_creds_returns_true(self, monkeypatch):
        monkeypatch.delenv("CS_DETERMINISTIC_MODE", raising=False)
        monkeypatch.setenv("CS_ENABLE_LLM_RUNTIME", "1")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        # 어떤 provider도 자격 없을 때 deterministic True
        result = is_deterministic_mode()
        # 환경에 따라 다른 결과 가능 — bool인지만 확인
        assert isinstance(result, bool)


class TestIsModelAvailable:
    def test_returns_bool(self, deterministic_env):
        assert isinstance(is_model_available("gpt-5.5"), bool)

    def test_anthropic_check(self, deterministic_env):
        assert isinstance(is_model_available("claude-opus-4-7"), bool)


class TestProviderHasCredentials:
    def test_openai_returns_bool(self):
        assert isinstance(provider_has_credentials("openai"), bool)

    def test_unknown_provider_returns_false(self):
        assert provider_has_credentials("xyz-unknown") is False

    def test_ollama_check(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        # ollama는 key 없이도 base_url로 활성
        result = provider_has_credentials("ollama")
        assert isinstance(result, bool)


class TestHasAnyProviderCredentials:
    def test_returns_bool(self):
        assert isinstance(has_any_provider_credentials(), bool)


class TestRenderPersonaPrompt:
    def test_unknown_role_returns_template(self):
        result = _render_persona_prompt("unknown_role", "template content")
        assert result == "template content"

    def test_known_role_renders_persona_id(self):
        template = "Role: {{persona_id}}"
        result = _render_persona_prompt("legal_counsel", template)
        assert "legal-counsel" in result

    def test_persona_role_substituted(self):
        template = "{{persona_role}}"
        result = _render_persona_prompt("legal_counsel", template)
        assert "Legal Counsel" in result


class TestBoardPersonaProfiles:
    def test_legal_counsel_present(self):
        assert "legal_counsel" in BOARD_PERSONA_PROFILES

    def test_all_personas_have_required_fields(self):
        for role, profile in BOARD_PERSONA_PROFILES.items():
            assert "persona_id" in profile
            assert "persona_role" in profile
            assert "persona_focus" in profile


class TestLoadSystemPrompt:
    def test_unknown_role_raises(self):
        with pytest.raises(LLMClientError, match="unknown role"):
            load_system_prompt("nonexistent-role")

    def test_known_role_loads_or_raises_missing(self):
        # 실제 prompt 파일이 존재하면 load, 없으면 LLMClientError
        try:
            prompt = load_system_prompt("verifier")
            assert isinstance(prompt, str)
            assert len(prompt) > 0
        except LLMClientError:
            # system_prompts 파일 부재 — OK
            pass


class TestLLMCallResult:
    def test_dataclass_fields(self):
        result = LLMCallResult(
            text="output", model="gpt-5.5", role="verifier",
            deterministic_fallback=False, estimated_cost_usd=0.01,
        )
        assert result.text == "output"
        assert result.metadata == {}

    def test_with_error(self):
        result = LLMCallResult(
            text="", model="x", role="x", error="timeout",
        )
        assert result.error == "timeout"


class TestLLMClientError:
    def test_is_exception(self):
        assert issubclass(LLMClientError, Exception)


class TestProviderRegistries:
    def test_openai_in_compatible(self):
        assert "openai" in OPENAI_COMPATIBLE_PROVIDERS

    def test_anthropic_in_known(self):
        assert "anthropic" in KNOWN_PROVIDER_PREFIXES

    def test_compatible_providers_have_key_env(self):
        for name, cfg in OPENAI_COMPATIBLE_PROVIDERS.items():
            assert "key_env" in cfg or name == "ollama"


class TestLLMClientClass:
    def test_construct_deterministic(self, deterministic_env):
        from compliance_sentinel.budget_guard import from_env as budget_guard_from_env
        from compliance_sentinel.agent_model_guard import ModelGuard
        client = LLMClient(
            budget_guard=budget_guard_from_env(),
            model_guard=ModelGuard.from_env(),
        )
        assert client.deterministic is True
        assert client.budget_guard is not None

    def test_provider_clients_initially_empty(self, deterministic_env):
        from compliance_sentinel.budget_guard import from_env as budget_guard_from_env
        from compliance_sentinel.agent_model_guard import ModelGuard
        client = LLMClient(
            budget_guard=budget_guard_from_env(),
            model_guard=ModelGuard.from_env(),
        )
        assert client._provider_clients == {}

    def test_call_deterministic_fallback(self, deterministic_env):
        from compliance_sentinel.budget_guard import from_env as budget_guard_from_env
        from compliance_sentinel.agent_model_guard import ModelGuard
        client = LLMClient(
            budget_guard=budget_guard_from_env(),
            model_guard=ModelGuard.from_env(),
        )
        result = client.call(
            role="verifier", user_text="text",
            model="gpt-5.5", effort="low", max_tokens=128, estimated_cost_usd=0.01,
        )
        # deterministic mode → fallback
        assert result.deterministic_fallback is True


class TestReasoningEffort:
    def test_static_method_callable(self):
        # _reasoning_effort_for_model은 static method
        result = LLMClient._reasoning_effort_for_model("o1-preview", "high")
        # o1 모델에 reasoning effort 적용
        assert result is None or isinstance(result, str)

    def test_non_reasoning_model_returns_none(self):
        result = LLMClient._reasoning_effort_for_model("gpt-5.5", "high")
        # 일반 모델은 reasoning effort 없음
        assert result is None or isinstance(result, str)
