"""M13 Budget Guard 단위 테스트.

대상: src/compliance_sentinel/budget_guard.py
  - MODEL_COST_PER_1K_TOKENS — 6 모델 가격표
  - estimate_cost(model, prompt_tokens, completion_tokens) -> float
  - BudgetGuard(per_demo_limit_usd, monthly_limit_usd, ...)
  - BudgetExceeded raise
  - check_tier (green/yellow/red/blocked)
  - from_env()
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from compliance_sentinel.budget_guard import (
    DEFAULT_BUDGETS,
    MODEL_COST_PER_1K_TOKENS,
    TIER_THRESHOLDS,
    BudgetExceeded,
    BudgetGuard,
    CostRecord,
    estimate_cost,
    from_env,
)


class TestModelPricing:
    def test_pricing_table_has_required_models(self):
        required = {"gpt-5.5", "gpt-5.4-mini", "gpt-5.4-nano", "default"}
        assert required.issubset(MODEL_COST_PER_1K_TOKENS.keys())

    def test_pricing_table_structure(self):
        for model, pricing in MODEL_COST_PER_1K_TOKENS.items():
            assert "prompt" in pricing, f"{model} missing prompt price"
            assert "completion" in pricing, f"{model} missing completion price"
            assert pricing["prompt"] >= 0
            assert pricing["completion"] >= 0

    def test_nano_cheaper_than_mini_cheaper_than_deep(self):
        nano = MODEL_COST_PER_1K_TOKENS["gpt-5.4-nano"]["prompt"]
        mini = MODEL_COST_PER_1K_TOKENS["gpt-5.4-mini"]["prompt"]
        deep = MODEL_COST_PER_1K_TOKENS["gpt-5.5"]["prompt"]
        assert nano < mini < deep


class TestEstimateCost:
    def test_zero_tokens_zero_cost(self):
        assert estimate_cost("gpt-5.5") == 0.0

    def test_known_model_cost(self):
        # gpt-5.4-mini: $0.000375/1K prompt + $0.00225/1K completion
        # 1000 prompt + 1000 completion → 0.000375 + 0.00225 = 0.002625
        cost = estimate_cost("gpt-5.4-mini", prompt_tokens=1000, completion_tokens=1000)
        assert cost == pytest.approx(0.002625, abs=1e-6)

    def test_unknown_model_uses_default_conservative(self):
        cost_unknown = estimate_cost("xyz-model", prompt_tokens=1000)
        cost_default = estimate_cost("default", prompt_tokens=1000)
        assert cost_unknown == cost_default

    def test_case_insensitive_model_lookup(self):
        a = estimate_cost("GPT-5.5", prompt_tokens=1000)
        b = estimate_cost("gpt-5.5", prompt_tokens=1000)
        assert a == b


class TestBudgetGuardCanSpend:
    def test_within_limit_returns_true(self, tmp_path):
        guard = BudgetGuard(
            per_demo_limit_usd=1.00,
            monthly_limit_usd=100.00,
            monthly_log=tmp_path / "ledger.jsonl",
        )
        assert guard.can_spend(0.50) is True

    def test_exceeds_per_demo_returns_false_when_not_strict(self, tmp_path):
        guard = BudgetGuard(
            per_demo_limit_usd=0.10,
            monthly_log=tmp_path / "ledger.jsonl",
        )
        assert guard.can_spend(0.50) is False

    def test_exceeds_per_demo_raises_when_strict(self, tmp_path):
        guard = BudgetGuard(
            per_demo_limit_usd=0.10,
            fail_on_exceed=True,
            monthly_log=tmp_path / "ledger.jsonl",
        )
        with pytest.raises(BudgetExceeded) as exc:
            guard.can_spend(0.50)
        assert "per_demo" in str(exc.value)


class TestRecordSpend:
    def test_record_appends_to_ledger(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        guard = BudgetGuard(per_demo_limit_usd=1.00, monthly_log=ledger)
        guard.record_spend(0.05, role="legal_counsel", model="gpt-5.4-mini")

        assert guard.session_spent_usd == pytest.approx(0.05)
        assert ledger.exists()
        line = ledger.read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        assert rec["role"] == "legal_counsel"
        assert rec["model"] == "gpt-5.4-mini"
        assert rec["cost_usd"] == pytest.approx(0.05)

    def test_session_accumulates(self, tmp_path):
        guard = BudgetGuard(per_demo_limit_usd=1.00, monthly_log=tmp_path / "l.jsonl")
        guard.record_spend(0.05, model="gpt-5.4-mini")
        guard.record_spend(0.10, model="gpt-5.5")
        assert guard.session_spent_usd == pytest.approx(0.15)


class TestTierClassification:
    def test_green_tier_under_90_percent(self, tmp_path):
        guard = BudgetGuard(per_demo_limit_usd=1.00, monthly_log=tmp_path / "l.jsonl")
        guard.session_spent_usd = 0.50  # 50%
        assert guard.check_tier(0.10) == "green"

    def test_yellow_tier_at_90_percent(self, tmp_path):
        guard = BudgetGuard(per_demo_limit_usd=1.00, monthly_log=tmp_path / "l.jsonl")
        guard.session_spent_usd = 0.85
        assert guard.check_tier(0.05) == "yellow"  # 0.90

    def test_red_tier_at_100_percent(self, tmp_path):
        guard = BudgetGuard(per_demo_limit_usd=1.00, monthly_log=tmp_path / "l.jsonl")
        guard.session_spent_usd = 0.95
        assert guard.check_tier(0.05) == "red"  # 1.00

    def test_blocked_tier_at_110_percent(self, tmp_path):
        guard = BudgetGuard(per_demo_limit_usd=1.00, monthly_log=tmp_path / "l.jsonl")
        guard.session_spent_usd = 1.05
        assert guard.check_tier(0.05) == "blocked"  # 1.10

    def test_should_fallback_when_red_or_blocked(self, tmp_path):
        guard = BudgetGuard(per_demo_limit_usd=1.00, monthly_log=tmp_path / "l.jsonl")
        guard.session_spent_usd = 0.99
        assert guard.should_fallback(0.05) is True

    def test_check_before_call_blocked_raises(self, tmp_path):
        guard = BudgetGuard(per_demo_limit_usd=1.00, monthly_log=tmp_path / "l.jsonl")
        guard.session_spent_usd = 1.05
        with pytest.raises(BudgetExceeded):
            guard.check_before_call(0.10, raise_on_blocked=True)


class TestSummary:
    def test_summary_keys(self, tmp_path):
        guard = BudgetGuard(per_demo_limit_usd=1.00, monthly_log=tmp_path / "l.jsonl")
        guard.record_spend(0.10)
        s = guard.summary()
        for k in ["session_spent_usd", "per_demo_limit_usd", "monthly_total_usd",
                  "monthly_limit_usd", "session_remaining_usd", "monthly_remaining_usd"]:
            assert k in s

    def test_status_with_tier_includes_tier(self, tmp_path):
        guard = BudgetGuard(per_demo_limit_usd=1.00, monthly_log=tmp_path / "l.jsonl")
        s = guard.status_with_tier()
        assert "tier" in s
        assert "session_percentage" in s
        assert s["tier"] == "green"


class TestFromEnv:
    def test_default_when_no_env(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CS_PER_DEMO_USD", raising=False)
        monkeypatch.delenv("CS_MONTHLY_USD", raising=False)
        guard = from_env()
        assert guard.per_demo_limit_usd == DEFAULT_BUDGETS["per_demo"]
        assert guard.monthly_limit_usd == DEFAULT_BUDGETS["monthly_dev"]

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("CS_PER_DEMO_USD", "2.50")
        monkeypatch.setenv("CS_MONTHLY_USD", "200.00")
        guard = from_env()
        assert guard.per_demo_limit_usd == 2.50
        assert guard.monthly_limit_usd == 200.00
