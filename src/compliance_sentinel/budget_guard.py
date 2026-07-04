"""Budget Guard — LLM 호출 비용 추적 + 한도 초과 시 차단.

출처:
  - workflows/cs-model-routing.yaml `budget_guards` 섹션
  - SEAS scripts/token-tracker.ts 패턴
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

DEFAULT_LOG = Path("audit_logs") / "llm_cost_ledger.jsonl"

# Budget tier (BG Phase A — spec/budget-guard-enforcement.md §3-tier)
Tier = Literal["green", "yellow", "red", "blocked"]
TIER_THRESHOLDS = {
    "yellow": 0.90,   # 90% 도달 시 warning
    "red": 1.00,      # 100% 도달 시 deterministic fallback 강제
    "blocked": 1.10,  # 110% 도달 시 BudgetExceeded raise
}

# 모델별 추정 비용 ($/1K tokens) — OpenAI standard short-context pricing (BG-006)
# OpenAI standard short-context pricing checked 2026-05-27.
MODEL_COST_PER_1K_TOKENS = {
    "claude-haiku":     {"prompt": 0.0008, "completion": 0.0040},
    "claude-sonnet":    {"prompt": 0.003,  "completion": 0.015},
    "claude-opus":      {"prompt": 0.015,  "completion": 0.075},
    "gpt-5.5":          {"prompt": 0.0025,  "completion": 0.015},
    "gpt-5.4-mini":     {"prompt": 0.000375, "completion": 0.00225},
    "gpt-5.4-nano":     {"prompt": 0.0001,  "completion": 0.000625},
    "default":          {"prompt": 0.01,   "completion": 0.03},  # 미지 모델 보수적
}


def estimate_cost(model: str, *, prompt_tokens: int = 0, completion_tokens: int = 0) -> float:
    """모델별 추정 비용 산출 (BG-006). 미지 모델은 default (over-estimate)."""
    pricing = MODEL_COST_PER_1K_TOKENS.get(model.lower(), MODEL_COST_PER_1K_TOKENS["default"])
    prompt_cost = (prompt_tokens / 1000.0) * pricing["prompt"]
    completion_cost = (completion_tokens / 1000.0) * pricing["completion"]
    return round(prompt_cost + completion_cost, 6)

# 기본 한도 (workflows/cs-model-routing.yaml budget_guards single source)
DEFAULT_BUDGETS = {
    "per_demo": 0.40,      # USD, 시연 1회 (단일 analyze() 호출)
    "per_batch_100": 20.00,  # 100건 일괄
    "monthly_dev": 80.00,    # 개발 월간 누적
}


@dataclass
class CostRecord:
    timestamp: str
    role: str
    model: str
    cost_usd: float
    scope: str = "single"  # single | batch | session

    def to_dict(self) -> dict:
        return asdict(self)


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class BudgetGuard:
    """Session-level + persistent monthly budget tracker.

    인스턴스화: 한 analyze() 또는 한 batch 작업 단위로 새로 생성 권장.
    """
    per_demo_limit_usd: float = DEFAULT_BUDGETS["per_demo"]
    monthly_limit_usd: float = DEFAULT_BUDGETS["monthly_dev"]
    session_spent_usd: float = 0.0
    monthly_log: Path = field(default_factory=lambda: DEFAULT_LOG)
    fail_on_exceed: bool = False  # True면 BudgetExceeded raise, False면 can_spend() False 반환

    def can_spend(self, cost_usd: float) -> bool:
        """다음 호출이 한도 내인가? 차단 시 False."""
        if self.session_spent_usd + cost_usd > self.per_demo_limit_usd:
            if self.fail_on_exceed:
                raise BudgetExceeded(
                    f"per_demo limit exceeded: would spend ${self.session_spent_usd + cost_usd:.3f} "
                    f"vs limit ${self.per_demo_limit_usd:.2f}"
                )
            return False
        if self._monthly_total() + cost_usd > self.monthly_limit_usd:
            if self.fail_on_exceed:
                raise BudgetExceeded(
                    f"monthly_dev limit exceeded: would total ${self._monthly_total() + cost_usd:.3f} "
                    f"vs limit ${self.monthly_limit_usd:.2f}"
                )
            return False
        return True

    def record_spend(self, cost_usd: float, *, role: str = "unknown", model: str = "unknown") -> None:
        self.session_spent_usd += cost_usd
        record = CostRecord(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            role=role,
            model=model,
            cost_usd=cost_usd,
            scope="single",
        )
        self.monthly_log.parent.mkdir(parents=True, exist_ok=True)
        with self.monthly_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def _monthly_total(self) -> float:
        """월간 누적 (현재 월의 ledger 합산)."""
        if not self.monthly_log.exists():
            return 0.0
        current_month_prefix = time.strftime("%Y-%m", time.gmtime())
        total = 0.0
        try:
            for line in self.monthly_log.read_text(encoding="utf-8").strip().split("\n"):
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("timestamp", "").startswith(current_month_prefix):
                        total += float(rec.get("cost_usd", 0))
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            return 0.0
        return total

    def summary(self) -> dict:
        return {
            "session_spent_usd": round(self.session_spent_usd, 3),
            "per_demo_limit_usd": self.per_demo_limit_usd,
            "monthly_total_usd": round(self._monthly_total(), 3),
            "monthly_limit_usd": self.monthly_limit_usd,
            "session_remaining_usd": round(self.per_demo_limit_usd - self.session_spent_usd, 3),
            "monthly_remaining_usd": round(self.monthly_limit_usd - self._monthly_total(), 3),
        }

    # === BG Phase A 신규 메서드 (spec/budget-guard-enforcement.md) ===

    def check_tier(self, cost_usd: float = 0.0) -> Tier:
        """BG-002/003: 다음 호출이 어느 tier에 해당하는가?

        - green:   현재 + 추정 비용 < 90% (정상)
        - yellow:  90~100% (warning)
        - red:     100~110% (deterministic fallback 권장)
        - blocked: ≥110% (BudgetExceeded 권장)
        """
        if self.per_demo_limit_usd <= 0:
            return "green"  # 한도 없음 = always green
        projected = (self.session_spent_usd + cost_usd) / self.per_demo_limit_usd
        if projected >= TIER_THRESHOLDS["blocked"]:
            return "blocked"
        if projected >= TIER_THRESHOLDS["red"]:
            return "red"
        if projected >= TIER_THRESHOLDS["yellow"]:
            return "yellow"
        return "green"

    def should_fallback(self, cost_usd: float = 0.0) -> bool:
        """BG-007: tier=red 또는 blocked 시 deterministic fallback 권장."""
        return self.check_tier(cost_usd) in ("red", "blocked")

    def check_before_call(self, estimated_cost: float, *, raise_on_blocked: bool = False) -> Tier:
        """BG-101: LLM 호출 직전 사전 check. tier 반환.

        raise_on_blocked=True 시 tier=blocked → BudgetExceeded raise.
        """
        tier = self.check_tier(estimated_cost)
        if tier == "blocked" and raise_on_blocked:
            raise BudgetExceeded(
                f"budget blocked tier: session ${self.session_spent_usd:.3f} + estimated ${estimated_cost:.4f} "
                f">= {TIER_THRESHOLDS['blocked'] * 100:.0f}% of limit ${self.per_demo_limit_usd:.2f}"
            )
        return tier

    def status_with_tier(self) -> dict:
        """BG-005/201: final_report에 inline용 tier 포함 status dict."""
        base = self.summary()
        tier = self.check_tier(0.0)  # 현재 시점 (추가 비용 0)
        base["tier"] = tier
        if self.per_demo_limit_usd > 0:
            base["session_percentage"] = round(
                self.session_spent_usd / self.per_demo_limit_usd * 100, 1
            )
        else:
            base["session_percentage"] = 0.0
        return base


def from_env() -> BudgetGuard:
    """환경변수로 한도 override 가능. CS_PER_DEMO_USD, CS_MONTHLY_USD."""
    per_demo = float(os.environ.get("CS_PER_DEMO_USD", DEFAULT_BUDGETS["per_demo"]))
    monthly = float(os.environ.get("CS_MONTHLY_USD", DEFAULT_BUDGETS["monthly_dev"]))
    return BudgetGuard(per_demo_limit_usd=per_demo, monthly_limit_usd=monthly)
