"""M4 Runtime helpers 단위 테스트.

대상: src/compliance_sentinel/runtime.py
  - parse_llm_risk_signal(text) — LLM 출력에서 bounded risk/recommendation 추출
  - build_runtime_plan(input_text, deterministic_mode) -> (routing_decision, model_plan)
  - live_review_profile() — env-driven profile (turbo/fast/balanced/strict)
  - select_marketing_advisory_roles(risk) — profile/risk 기반 role 선택
  - advisory_max_tokens_for_risk(risk) — 토큰 budget
  - apply_quality_first_routing(model_plan, risk_level) — HIGH/CRITICAL 시 critic 모델로 escalate
"""
from __future__ import annotations

import pytest

from compliance_sentinel.runtime import (
    DEFAULT_LIVE_REVIEW_PROFILE,
    advisory_max_tokens_for_risk,
    apply_quality_first_routing,
    build_runtime_plan,
    live_review_profile,
    parse_llm_risk_signal,
    select_marketing_advisory_roles,
)


class TestParseLLMRiskSignal:
    def test_empty_text_returns_empty(self):
        assert parse_llm_risk_signal("") == {}

    def test_extracts_high_risk(self):
        result = parse_llm_risk_signal("This advertisement carries HIGH compliance risk.")
        assert result["risk_level"] == "HIGH"

    def test_extracts_reject_recommendation_korean(self):
        result = parse_llm_risk_signal("MEDIUM 위험, 반려 권고")
        assert result["risk_level"] == "MEDIUM"
        assert result["recommendation"] == "reject"

    def test_extracts_human_review_recommendation(self):
        result = parse_llm_risk_signal("HIGH risk, human review required")
        assert result["recommendation"] == "human_review"

    def test_extracts_approve_recommendation(self):
        result = parse_llm_risk_signal("LOW risk — approve")
        assert result["recommendation"] == "approve_with_or_without_changes"

    def test_no_signal_returns_empty(self):
        assert parse_llm_risk_signal("일반 평문") == {}

    def test_signal_source_marker(self):
        result = parse_llm_risk_signal("HIGH risk")
        assert result["signal_source"] == "llm_advisory_parsed_no_raw_text"


class TestBuildRuntimePlan:
    def test_returns_tuple_of_dicts(self):
        decision, plan = build_runtime_plan("원금 보장 광고", deterministic_mode=True)
        assert isinstance(decision, dict)
        assert isinstance(plan, dict)

    def test_deterministic_mode_consistent(self):
        d1, p1 = build_runtime_plan("동일 입력", deterministic_mode=True)
        d2, p2 = build_runtime_plan("동일 입력", deterministic_mode=True)
        # 같은 입력 → 같은 routing decision
        assert d1 == d2

    def test_plan_has_role_assignments(self):
        _, plan = build_runtime_plan("광고 검토", deterministic_mode=True)
        # ModelRouter는 role_assignments 키를 보유
        assert "role_assignments" in plan or "model" in plan


class TestLiveReviewProfile:
    def test_default_is_turbo(self, monkeypatch):
        monkeypatch.delenv("CS_LIVE_REVIEW_PROFILE", raising=False)
        assert live_review_profile() == DEFAULT_LIVE_REVIEW_PROFILE

    @pytest.mark.parametrize("profile", ["turbo", "fast", "balanced", "strict"])
    def test_valid_profiles(self, monkeypatch, profile):
        monkeypatch.setenv("CS_LIVE_REVIEW_PROFILE", profile)
        assert live_review_profile() == profile

    def test_invalid_profile_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("CS_LIVE_REVIEW_PROFILE", "invalid_xyz")
        assert live_review_profile() == DEFAULT_LIVE_REVIEW_PROFILE

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("CS_LIVE_REVIEW_PROFILE", "STRICT")
        assert live_review_profile() == "strict"


class TestSelectMarketingAdvisoryRoles:
    def test_strict_profile_returns_all_marketing_roles(self, monkeypatch):
        monkeypatch.setenv("CS_LIVE_REVIEW_PROFILE", "strict")
        roles = select_marketing_advisory_roles("LOW")
        assert len(roles) >= 6

    def test_high_risk_always_returns_full_set(self, monkeypatch):
        monkeypatch.setenv("CS_LIVE_REVIEW_PROFILE", "turbo")
        roles = select_marketing_advisory_roles("HIGH")
        # HIGH risk → profile 무관 풀 advisory
        assert "verifier" in roles

    def test_turbo_low_risk_returns_empty(self, monkeypatch):
        monkeypatch.setenv("CS_LIVE_REVIEW_PROFILE", "turbo")
        roles = select_marketing_advisory_roles("LOW")
        assert roles == []

    def test_turbo_medium_returns_verifier_only(self, monkeypatch):
        monkeypatch.setenv("CS_LIVE_REVIEW_PROFILE", "turbo")
        roles = select_marketing_advisory_roles("MEDIUM")
        assert roles == ["verifier"]


class TestAdvisoryMaxTokens:
    def test_high_risk_512_tokens(self):
        assert advisory_max_tokens_for_risk("HIGH") == 512
        assert advisory_max_tokens_for_risk("CRITICAL") == 512

    def test_low_medium_128_tokens(self):
        assert advisory_max_tokens_for_risk("LOW") == 128
        assert advisory_max_tokens_for_risk("MEDIUM") == 128

    def test_unknown_risk_defaults_to_128(self):
        assert advisory_max_tokens_for_risk("UNKNOWN") == 128


class _FakeLLMResult:
    """LLMClient.call() 반환값 stub."""

    def __init__(self, text="", model="gpt-5.5", deterministic_fallback=False, error=None):
        self.text = text
        self.model = model
        self.deterministic_fallback = deterministic_fallback
        self.error = error
        self.role = "verifier"
        self.estimated_cost_usd = 0.05
        self.metadata = {}
        # LLMCallResult 실측 토큰 필드 (llm_advisory_call이 접근 — mock 일관성).
        self.cached_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0


class _FakeLLMClient:
    """LLMClient stub — deterministic mode toggle."""

    def __init__(self, deterministic=True, response_text=""):
        self.deterministic = deterministic
        self._response_text = response_text
        self.calls = []

    def call(self, role, user_text, *, model, effort, max_tokens, estimated_cost_usd):
        self.calls.append({"role": role, "model": model, "effort": effort})
        if self.deterministic:
            return _FakeLLMResult(text="", deterministic_fallback=True)
        return _FakeLLMResult(text=self._response_text, model=model)


class TestLLMAdvisoryCall:
    def test_role_not_in_plan_returns_fallback(self):
        from compliance_sentinel.runtime import llm_advisory_call
        result = llm_advisory_call(
            model_plan={"role_assignments": {}},
            llm_client=_FakeLLMClient(),
            role="legal_counsel",
            user_text="text",
        )
        assert result["called"] is False
        assert result["deterministic_fallback"] is True
        assert result["error"] == "role_not_in_model_plan"

    def test_deterministic_client_returns_fallback(self):
        from compliance_sentinel.runtime import llm_advisory_call
        plan = {"role_assignments": {"legal_counsel": {"model": "gpt-5.4-mini",
                                                       "effort": "low",
                                                       "cost_multiplier": 1.0}}}
        result = llm_advisory_call(
            model_plan=plan, llm_client=_FakeLLMClient(deterministic=True),
            role="legal_counsel", user_text="text",
        )
        assert result["called"] is False
        assert result["deterministic_fallback"] is True

    def test_real_call_parses_risk_signal(self):
        from compliance_sentinel.runtime import llm_advisory_call
        plan = {"role_assignments": {"legal_counsel": {"model": "gpt-5.5",
                                                       "effort": "high",
                                                       "cost_multiplier": 1.0}}}
        client = _FakeLLMClient(deterministic=False, response_text="HIGH risk — reject")
        result = llm_advisory_call(
            model_plan=plan, llm_client=client,
            role="legal_counsel", user_text="원금 보장 광고",
        )
        assert result["called"] is True
        assert result["risk_level"] == "HIGH"
        assert result["recommendation"] == "reject"
        assert len(client.calls) == 1


class TestLLMAdvisoryCallsParallel:
    def test_empty_roles_returns_empty(self):
        from compliance_sentinel.runtime import llm_advisory_calls_parallel
        result = llm_advisory_calls_parallel(
            model_plan={}, llm_client=_FakeLLMClient(),
            roles=[], user_text="x",
        )
        assert result == []

    def test_parallel_preserves_role_order(self):
        from compliance_sentinel.runtime import llm_advisory_calls_parallel
        plan = {"role_assignments": {
            "legal_counsel": {"model": "gpt-5.4-mini", "effort": "low", "cost_multiplier": 1.0},
            "pipa_expert": {"model": "gpt-5.4-mini", "effort": "low", "cost_multiplier": 1.0},
            "consumer_protection": {"model": "gpt-5.4-mini", "effort": "low", "cost_multiplier": 1.0},
        }}
        client = _FakeLLMClient(deterministic=False, response_text="LOW")
        roles = ["legal_counsel", "pipa_expert", "consumer_protection"]
        result = llm_advisory_calls_parallel(
            model_plan=plan, llm_client=client, roles=roles, user_text="x",
        )
        # 결과 길이 = 입력 roles 길이, 순서 보존
        assert len(result) == 3
        assert [r["role"] for r in result] == roles


class TestApplyQualityFirstRouting:
    def test_low_risk_no_escalation(self):
        plan = {
            "role_assignments": {
                "ceo_synthesizer": {"model": "gpt-5.4-mini", "effort": "low", "tier": "standard"},
            }
        }
        escalated = apply_quality_first_routing(plan, risk_level="LOW")
        assert escalated == []
        # plan 변경 없음
        assert plan["role_assignments"]["ceo_synthesizer"]["model"] == "gpt-5.4-mini"

    def test_high_risk_escalates_critic_roles(self):
        plan = {
            "role_assignments": {
                "ceo_synthesizer": {"model": "gpt-5.4-mini", "effort": "low", "tier": "standard"},
                "verifier": {"model": "gpt-5.4-mini", "effort": "low", "tier": "standard"},
            }
        }
        escalated = apply_quality_first_routing(plan, risk_level="HIGH")
        assert "ceo_synthesizer" in escalated
        assert "verifier" in escalated
        # 모델 escalate 확인
        assert plan["role_assignments"]["ceo_synthesizer"]["tier"] == "critical"

    def test_critical_also_escalates(self):
        plan = {
            "role_assignments": {
                "adversarial_critic": {"model": "gpt-5.4-mini", "effort": "low", "tier": "standard"},
            }
        }
        escalated = apply_quality_first_routing(plan, risk_level="CRITICAL")
        assert "adversarial_critic" in escalated

    def test_missing_role_skipped(self):
        plan = {"role_assignments": {}}
        escalated = apply_quality_first_routing(plan, risk_level="HIGH")
        assert escalated == []
