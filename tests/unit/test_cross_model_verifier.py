"""M10 Cross-Model Verifier 단위 테스트.

대상: src/compliance_sentinel/cross_model_verifier.py
  - _default_cross_model() — CS_MODEL_CRITIC 검증 (gpt-5.5만 허용)
  - CrossModelResult dataclass
  - is_enabled(model) — deterministic 모드 / api 키 부재 시 False
  - verify(builder_output, verifier_output, ...) — deterministic fallback 시 SKIPPED

LLM 호출 없음 (deterministic mode에서 작동 확인).
"""
from __future__ import annotations

import pytest

from compliance_sentinel.cross_model_verifier import (
    DEFAULT_CROSS_MODEL,
    CrossModelResult,
    _default_cross_model,
    is_enabled,
    verify,
)


class TestDefaultCrossModel:
    def test_returns_default_critic(self):
        # 2026-07-04: critic 기본값 = claude-opus-4-8 (Claude 최신 tier 전환)
        assert _default_cross_model() == "claude-opus-4-8"

    def test_unset_env_returns_default(self, monkeypatch):
        # 2026-07-03: 기본 critic = claude-opus-4-8 (Anthropic 전환)
        monkeypatch.delenv("CS_MODEL_CRITIC", raising=False)
        assert _default_cross_model() == "claude-opus-4-8"

    def test_correct_value_passes(self, monkeypatch):
        monkeypatch.setenv("CS_MODEL_CRITIC", "gpt-5.5")
        assert _default_cross_model() == "gpt-5.5"

    def test_wrong_model_raises(self, monkeypatch):
        monkeypatch.setenv("CS_MODEL_CRITIC", "gpt-5.4-mini")
        with pytest.raises(ValueError) as exc:
            _default_cross_model()
        assert "gpt-5.5" in str(exc.value)


class TestIsEnabled:
    def test_deterministic_mode_disabled(self, deterministic_env):
        """deterministic mode (CS_ENABLE_LLM_RUNTIME=0) → 비활성."""
        assert is_enabled() is False

    def test_no_api_key_disabled(self, monkeypatch):
        """API key 부재 시 비활성."""
        monkeypatch.setenv("CS_ENABLE_LLM_RUNTIME", "1")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert is_enabled("gpt-5.5") is False


class TestCrossModelResult:
    def test_default_fields(self):
        result = CrossModelResult(enabled=False, cross_model_confidence="SKIPPED")
        assert result.enabled is False
        assert result.cross_model_confidence == "SKIPPED"
        assert result.agreed_findings == []
        assert result.disputed_findings == []
        assert result.blind_spots_caught == []
        assert result.recommendation == "skipped"
        assert result.error is None
        assert result.deterministic_fallback is False
        assert result.estimated_cost_usd == 0.0

    def test_custom_fields(self):
        result = CrossModelResult(
            enabled=True,
            cross_model_confidence="VERIFIED",
            agreed_findings=["F-001"],
            recommendation="ship_ok",
            estimated_cost_usd=0.05,
        )
        assert result.enabled is True
        assert result.agreed_findings == ["F-001"]
        assert result.recommendation == "ship_ok"


class TestVerifyDeterministicFallback:
    """deterministic 환경에서 verify() — 외부 호출 없이 SKIPPED 결과."""

    def test_skipped_when_deterministic(self, deterministic_env):
        result = verify(
            builder_output={"findings": []},
            verifier_output=[],
        )
        assert result.enabled is False
        assert result.cross_model_confidence == "SKIPPED"
        assert result.deterministic_fallback is True
        assert result.recommendation == "skipped"

    def test_default_model_constant(self):
        assert DEFAULT_CROSS_MODEL == "claude-opus-4-8"
