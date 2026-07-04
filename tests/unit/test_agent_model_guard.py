"""S1 Agent Model Guard 단위 테스트.

대상: src/compliance_sentinel/agent_model_guard.py
  - MODEL_NANO / MODEL_MINI / MODEL_DEEP 상수
  - allowed_models_for_role(role) — 역할별 허용 모델 set
  - ModelGuard.check(role, model) — 위반 시 ModelGuardViolation
  - CS_BYPASS_MODEL_GUARD=1 우회 (stderr 경고)
"""
from __future__ import annotations

import pytest

from compliance_sentinel.agent_model_guard import (
    MODEL_DEEP,
    MODEL_MINI,
    MODEL_NANO,
    BOARD_PRIMARY_MODELS,
    CRITICAL_VALIDATION_MODELS,
    FAST_PRIMARY_MODELS,
    ModelGuard,
    ModelGuardViolation,
    PRIMARY_OPENAI_MODELS,
    allowed_models_for_role,
)


class TestModelConstants:
    def test_fixed_tier_models(self):
        assert MODEL_NANO == "gpt-5.4-nano"
        assert MODEL_MINI == "gpt-5.4-mini"
        assert MODEL_DEEP == "gpt-5.5"

    def test_primary_set_contains_3_tiers(self):
        assert PRIMARY_OPENAI_MODELS == {MODEL_NANO, MODEL_MINI, MODEL_DEEP}

    def test_critical_validation_deep_tier_only(self):
        """cross_model_verifier는 deep-tier(gpt-5.5 / claude-opus-4-8)만 허용 — downgrade 차단."""
        assert CRITICAL_VALIDATION_MODELS == {MODEL_DEEP, "claude-opus-4-8"}


class TestAllowedModelsForRole:
    @pytest.mark.parametrize("role", ["classifier", "documenter"])
    def test_fast_roles_allow_all_3_tiers(self, role):
        allowed = allowed_models_for_role(role)
        assert MODEL_NANO in allowed
        assert MODEL_MINI in allowed
        assert MODEL_DEEP in allowed

    @pytest.mark.parametrize(
        "role",
        [
            "legal_counsel",
            "pipa_expert",
            "consumer_protection",
            "operational_risk",
            "business_practicality",
            "contrarian",
            "board_member",
        ],
    )
    def test_board_roles_exclude_nano(self, role):
        """6 보드는 mini/deep만 허용 — nano 사용 금지 (품질 보존)."""
        allowed = allowed_models_for_role(role)
        assert MODEL_NANO not in allowed
        assert MODEL_MINI in allowed
        assert MODEL_DEEP in allowed
        assert allowed == BOARD_PRIMARY_MODELS

    def test_cross_model_verifier_deep_tier(self):
        """Cross-model은 deep-tier(gpt-5.5 / claude-opus-4-8) hard pin."""
        allowed = allowed_models_for_role("cross_model_verifier")
        assert allowed == {MODEL_DEEP, "claude-opus-4-8"}

    def test_unknown_role_returns_none(self):
        assert allowed_models_for_role("unknown_role_xyz") is None


class TestModelGuardCheck:
    def test_check_allowed_model_passes(self):
        guard = ModelGuard()
        # 정상 — board_member에 mini 사용 OK
        guard.check(role="legal_counsel", model=MODEL_MINI)
        guard.check(role="cross_model_verifier", model=MODEL_DEEP)

    def test_check_disallowed_model_raises(self):
        guard = ModelGuard()
        # legal_counsel에 nano 사용 → 위반
        with pytest.raises(ModelGuardViolation) as exc:
            guard.check(role="legal_counsel", model=MODEL_NANO)
        assert "legal_counsel" in str(exc.value)
        assert MODEL_NANO in str(exc.value)

    def test_cross_model_silent_downgrade_blocked(self):
        """cross_model_verifier가 mini로 downgrade 시 즉시 차단 (LP-CS-030 핵심)."""
        guard = ModelGuard()
        with pytest.raises(ModelGuardViolation):
            guard.check(role="cross_model_verifier", model=MODEL_MINI)

    def test_unknown_role_passes_silently(self):
        """본 guard가 모르는 role은 통과 (확장성 보존)."""
        guard = ModelGuard()
        guard.check(role="unknown_role_xyz", model="any-model")

    def test_unknown_model_for_known_role_raises(self):
        guard = ModelGuard()
        with pytest.raises(ModelGuardViolation):
            guard.check(role="ceo_synthesizer", model="claude-haiku")


class TestBypass:
    def test_bypass_allows_violation_with_stderr_warning(self, capsys, monkeypatch):
        """CS_BYPASS_MODEL_GUARD=1 시 위반해도 통과 + stderr 경고."""
        monkeypatch.setenv("CS_BYPASS_MODEL_GUARD", "1")
        guard = ModelGuard.from_env()
        assert guard.bypass_allowed is True

        # 위반인데도 raise 안 됨
        guard.check(role="cross_model_verifier", model=MODEL_NANO)
        captured = capsys.readouterr()
        assert "BYPASS" in captured.err
        assert "Violation" in captured.err

    def test_bypass_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("CS_BYPASS_MODEL_GUARD", raising=False)
        guard = ModelGuard.from_env()
        assert guard.bypass_allowed is False
