"""model_router.py — env-based model resolution + tier mapping."""
from __future__ import annotations

import pytest

from compliance_sentinel.model_router import (
    ALLOWED_OPENAI_MODELS,
    MODEL_CODEX,
    MODEL_CODEX_MINI,
    MODEL_CRITIC,
    MODEL_DEEP,
    MODEL_HAIKU,
    MODEL_OPENAI_NANO,
    MODEL_SHALLOW,
    MODEL_SONNET,
    MODEL_STANDARD,
    TIER_BASE_MODEL,
    VALIDATION_ROLES,
    _fixed_model_env,
    _model_env,
    refresh_model_config_from_env,
)


class TestAllowedModels:
    def test_only_3_openai_models(self):
        assert ALLOWED_OPENAI_MODELS == frozenset({"gpt-5.5", "gpt-5.4-mini", "gpt-5.4-nano"})


class TestModelConstants:
    # 2026-07-03: tier 기본값 Anthropic Claude 전환. 상수명은 하위호환 유지, 값은 Claude.
    def test_shallow_default_is_haiku(self):
        assert MODEL_OPENAI_NANO == "claude-haiku-4-5"

    def test_standard_default_is_sonnet(self):
        assert MODEL_CODEX_MINI == "claude-sonnet-4-6"

    def test_deep_default_is_opus(self):
        assert MODEL_CODEX == "claude-opus-4-8"

    def test_critic_default_is_opus(self):
        assert MODEL_CRITIC == "claude-opus-4-8"

    def test_tier_aliases(self):
        assert MODEL_SHALLOW == MODEL_OPENAI_NANO
        assert MODEL_STANDARD == MODEL_CODEX_MINI
        assert MODEL_DEEP == MODEL_CODEX


class TestClaudeModels:
    def test_haiku(self):
        assert MODEL_HAIKU == "claude-haiku-4-5"

    def test_sonnet(self):
        assert MODEL_SONNET == "claude-sonnet-4-6"


class TestTierBaseModel:
    def test_dict_structure(self):
        assert isinstance(TIER_BASE_MODEL, dict)
        # 최소 shallow/standard/deep 매핑 보유
        assert len(TIER_BASE_MODEL) > 0


class TestValidationRoles:
    def test_includes_verifier(self):
        assert "verifier" in VALIDATION_ROLES

    def test_includes_cross_model(self):
        assert "cross_model_verifier" in VALIDATION_ROLES


class TestFixedModelEnv:
    def test_returns_default_when_no_env(self, monkeypatch):
        monkeypatch.delenv("CS_TEST_FIXED_XYZ", raising=False)
        result = _fixed_model_env("CS_TEST_FIXED_XYZ", default="gpt-5.5")
        assert result == "gpt-5.5"

    def test_allowlisted_env_overrides_default(self, monkeypatch):
        # 2026-07-03: allowlist(OpenAI+Anthropic) 내 값이면 default와 달라도 허용 (env override).
        monkeypatch.setenv("CS_TEST_FIXED_XYZ", "gpt-5.4-mini")
        assert _fixed_model_env("CS_TEST_FIXED_XYZ", default="claude-opus-4-8") == "gpt-5.4-mini"

    def test_off_allowlist_env_raises(self, monkeypatch):
        # allowlist 밖 값(오타/downgrade)은 ValueError로 차단 (재현성 보존).
        monkeypatch.setenv("CS_TEST_FIXED_XYZ", "gpt-4o-mini")
        with pytest.raises(ValueError) as exc:
            _fixed_model_env("CS_TEST_FIXED_XYZ", default="claude-opus-4-8")
        assert "not an allowed tier model" in str(exc.value)


class TestModelEnv:
    def test_returns_default_when_no_env(self, monkeypatch):
        monkeypatch.delenv("CS_PRIMARY_TEST_XYZ", raising=False)
        monkeypatch.delenv("CS_LEGACY_TEST_XYZ", raising=False)
        result = _model_env("CS_PRIMARY_TEST_XYZ", "CS_LEGACY_TEST_XYZ", "gpt-5.4-nano")
        assert result == "gpt-5.4-nano"

    def test_allowlisted_env_overrides_default(self, monkeypatch):
        # allowlist 내 값이면 default와 달라도 허용
        monkeypatch.setenv("CS_PRIMARY_TEST_XYZ", "claude-sonnet-5")
        assert _model_env("CS_PRIMARY_TEST_XYZ", "CS_LEGACY_TEST_XYZ", "claude-haiku-4-5") == "claude-sonnet-5"

    def test_off_allowlist_env_raises(self, monkeypatch):
        # allowlist 밖 값은 ValueError (silent downgrade 차단)
        monkeypatch.setenv("CS_PRIMARY_TEST_XYZ", "gpt-3.5-turbo")
        with pytest.raises(ValueError):
            _model_env("CS_PRIMARY_TEST_XYZ", "CS_LEGACY_TEST_XYZ", "claude-haiku-4-5")


class TestRefreshConfig:
    def test_callable(self):
        refresh_model_config_from_env()


class TestModelRouterClass:
    def test_construct_deterministic(self):
        from compliance_sentinel.model_router import ModelRouter
        router = ModelRouter(deterministic_mode=True)
        assert router.deterministic_mode is True

    def test_plan_from_decision_standard(self):
        from compliance_sentinel.model_router import ModelRouter
        router = ModelRouter(deterministic_mode=True)
        decision = {
            "domain": "advertisement", "complexity": "medium",
            "quality": "standard", "routed_model_tier": "standard",
        }
        plan = router.plan_from_decision(decision)
        assert plan.domain == "advertisement"
        assert plan.base_tier == "standard"
        assert plan.deterministic_mode is True
        # 분류/board/verifier/ceo/documenter 역할 모두 할당
        assert "classifier" in plan.role_assignments
        assert "verifier" in plan.role_assignments
        assert "ceo_synthesizer" in plan.role_assignments

    def test_plan_critical_escalates_ceo_and_verifier(self):
        from compliance_sentinel.model_router import ModelRouter
        router = ModelRouter(deterministic_mode=True)
        decision = {
            "domain": "payment", "complexity": "complex",
            "quality": "critical", "routed_model_tier": "critical",
        }
        plan = router.plan_from_decision(decision)
        assert plan.role_assignments["ceo_synthesizer"].tier == "critical"
        assert plan.role_assignments["verifier"].tier == "critical"

    def test_cross_model_recommendation_present(self):
        from compliance_sentinel.model_router import ModelRouter
        router = ModelRouter(deterministic_mode=True)
        plan = router.plan_from_decision({
            "domain": "advertisement", "complexity": "medium",
            "quality": "standard", "routed_model_tier": "standard",
        })
        assert plan.cross_model is not None
        assert plan.cross_model.level in {"STRONG", "ADVISORY", "NONE"}

    def test_estimated_cost_deterministic_zero(self):
        from compliance_sentinel.model_router import ModelRouter
        router = ModelRouter(deterministic_mode=True)
        plan = router.plan_from_decision({
            "domain": "x", "complexity": "simple",
            "quality": "standard", "routed_model_tier": "standard",
        })
        assert plan.estimated_cost_usd == 0.0

    def test_estimated_cost_non_deterministic_positive(self):
        from compliance_sentinel.model_router import ModelRouter
        router = ModelRouter(deterministic_mode=False)
        plan = router.plan_from_decision({
            "domain": "x", "complexity": "simple",
            "quality": "standard", "routed_model_tier": "standard",
        })
        assert plan.estimated_cost_usd > 0


class TestMain:
    def test_plan_subcommand_deterministic(self, capsys, monkeypatch):
        from compliance_sentinel.model_router import main
        monkeypatch.setenv("CS_DETERMINISTIC_MODE", "1")
        try:
            result = main(["plan", "광고 텍스트"])
        except Exception as e:
            if "Routing table" in str(e):
                pytest.skip("routing table missing")
            raise
        assert result == 0
        captured = capsys.readouterr()
        assert "domain" in captured.out

    def test_plan_json(self, capsys, monkeypatch):
        from compliance_sentinel.model_router import main
        monkeypatch.setenv("CS_DETERMINISTIC_MODE", "1")
        try:
            result = main(["plan", "광고", "--json"])
        except Exception as e:
            if "Routing table" in str(e):
                pytest.skip("routing table missing")
            raise
        assert result == 0
        captured = capsys.readouterr()
        assert "{" in captured.out
