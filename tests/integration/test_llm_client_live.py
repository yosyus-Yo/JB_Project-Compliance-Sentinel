"""llm_client LIVE integration test — 실제 API 호출.

⚠️ **비용 발생 가능**:
  - OPENAI_API_KEY + CS_ENABLE_LLM_RUNTIME=1 환경에서만 실제 호출
  - 1회 호출당 ~$0.001-0.05 (모델/토큰에 따라)

목적:
  - llm_client의 실제 OpenAI SDK 호출 path가 정상 동작 검증
  - unit test deterministic fallback path가 production과 일치하는지 contract 확인
  - 회귀 시점: SDK 업데이트 / 모델 ID 변경 / API 응답 schema 변경

실행:
  CS_ENABLE_LLM_RUNTIME=1 OPENAI_API_KEY=sk-... pytest tests/integration/test_llm_client_live.py -v
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestLLMClientLiveCall:
    """실제 OpenAI 호출 — fixture skip 가드로 안전."""

    def test_basic_call_returns_text(self, require_openai, live_llm_env):
        from compliance_sentinel.budget_guard import from_env as budget_guard_from_env
        from compliance_sentinel.agent_model_guard import ModelGuard
        from compliance_sentinel.llm_client import LLMClient

        client = LLMClient(
            budget_guard=budget_guard_from_env(),
            model_guard=ModelGuard.from_env(),
        )
        # CS_ENABLE_LLM_RUNTIME=1 + 실제 key → deterministic=False
        assert client.deterministic is False

        result = client.call(
            role="classifier",  # shallow tier, 가장 저렴
            user_text="다음 텍스트를 한 단어로 분류하세요: 광고",
            model="gpt-5.4-nano",  # shallow 모델
            effort="low",
            max_tokens=20,
            estimated_cost_usd=0.001,
        )

        # 실제 응답 받음
        assert result.text  # non-empty
        assert result.deterministic_fallback is False
        assert result.model == "gpt-5.4-nano"
        assert result.error is None
        assert result.estimated_cost_usd > 0

    def test_response_structure_contract(self, require_openai, live_llm_env):
        """LLMCallResult 객체가 unit test 가정과 동일한 구조인지 contract 검증."""
        from compliance_sentinel.budget_guard import from_env as budget_guard_from_env
        from compliance_sentinel.agent_model_guard import ModelGuard
        from compliance_sentinel.llm_client import LLMCallResult, LLMClient

        client = LLMClient(
            budget_guard=budget_guard_from_env(),
            model_guard=ModelGuard.from_env(),
        )
        result = client.call(
            role="documenter",
            user_text="요약: 이 문장은 테스트입니다.",
            model="gpt-5.4-nano",
            effort="low",
            max_tokens=30,
            estimated_cost_usd=0.001,
        )

        # contract: LLMCallResult dataclass 필드 모두 존재
        assert isinstance(result, LLMCallResult)
        assert hasattr(result, "text")
        assert hasattr(result, "model")
        assert hasattr(result, "role")
        assert hasattr(result, "deterministic_fallback")
        assert hasattr(result, "estimated_cost_usd")
        assert hasattr(result, "error")
        assert hasattr(result, "metadata")
        assert isinstance(result.metadata, dict)


class TestLLMClientDeterministicContract:
    """LIVE 환경에서도 deterministic mode 토글 시 fallback 동작 검증."""

    def test_deterministic_mode_forced_off_via_env(self, monkeypatch):
        """env로 deterministic 강제 → 실제 키 없어도 fallback."""
        monkeypatch.setenv("CS_DETERMINISTIC_MODE", "1")
        monkeypatch.delenv("CS_ENABLE_LLM_RUNTIME", raising=False)

        from compliance_sentinel.budget_guard import from_env as budget_guard_from_env
        from compliance_sentinel.agent_model_guard import ModelGuard
        from compliance_sentinel.llm_client import LLMClient

        client = LLMClient(
            budget_guard=budget_guard_from_env(),
            model_guard=ModelGuard.from_env(),
        )
        assert client.deterministic is True

        result = client.call(
            role="verifier", user_text="x", model="gpt-5.5",
            effort="low", max_tokens=10, estimated_cost_usd=0.001,
        )
        assert result.deterministic_fallback is True
        assert result.text == ""  # deterministic fallback은 empty text


class TestProviderAvailability:
    """is_model_available + has_any_provider_credentials 실제 환경 검증."""

    def test_openai_available_when_key_set(self, require_openai):
        from compliance_sentinel.llm_client import is_model_available
        assert is_model_available("gpt-5.4-nano") is True

    def test_unknown_provider_not_available(self):
        from compliance_sentinel.llm_client import is_model_available
        assert is_model_available("nonexistent/model") is False
