"""Deterministic vs LLM-runtime 비교 시연.

같은 입력을 두 모드로 실행하여 차이를 보여줍니다.

- Mode A (deterministic): `deterministic_mode=True` — LLM advisory/validation 호출 비활성.
  외부 API key가 없거나 회귀 안정성이 필요한 평가 환경에서 default.
- Mode B (llm-runtime): `deterministic_mode=False` + `CS_ENABLE_LLM_RUNTIME=1` 환경변수
  + `CODEX_API_KEY` 또는 `OPENAI_API_KEY` 보유 시 실제 LLM 호출 활성. 키가 없으면
  `LLMClient`가 silently fallback (각 호출 결과의 `deterministic_fallback=True`).

핵심: API key 부재 환경에서도 Mode B는 **routing/model plan 단계는 정상 동작**하며,
LLM 호출 시점에서 deterministic fallback으로 회수됩니다. 따라서 본 스크립트의 출력은
"실제 LLM 호출이 발생했는가"가 아니라 "두 모드의 model plan / fallback 신호 차이"를
보여줍니다.

Usage:
    PYTHONPATH=src python3 scripts/run_compare_modes.py

    # 실제 LLM 호출까지 비교하려면:
    CS_ENABLE_LLM_RUNTIME=1 CODEX_API_KEY=sk-... \
      PYTHONPATH=src python3 scripts/run_compare_modes.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compliance_sentinel.runtime import build_runtime_plan  # noqa: E402
from compliance_sentinel.engine import analyze_with_engine  # noqa: E402


SAMPLE = "JB 슈퍼적금 출시! 누구나 연 8% 확정 수익, 원금 보장!"


def _summarize_plan(decision: dict, plan: dict) -> dict:
    return {
        "domain": decision.get("domain"),
        "complexity": decision.get("complexity"),
        "quality": decision.get("quality"),
        "base_tier": plan.get("base_tier"),
        "cross_model_level": (plan.get("cross_model") or {}).get("level"),
        "cross_model_auto_attach": (plan.get("cross_model") or {}).get("auto_attach"),
        "roles": sorted((plan.get("role_assignments") or {}).keys()),
        "estimated_cost_usd": plan.get("estimated_cost_usd"),
        "deterministic_mode": plan.get("deterministic_mode"),
    }


def _summarize_report(report: dict) -> dict:
    return {
        "approval_status": report.get("approval_status"),
        "risk_level": report.get("risk_level"),
        "confidence": report.get("confidence"),
        "language": report.get("language"),
        "findings_count": len(report.get("findings", [])),
        "llm_calls_count": len(report.get("llm_calls") or []),
        "llm_calls_actually_called": sum(
            1 for c in (report.get("llm_calls") or []) if c.get("called")
        ),
        "cross_model_enabled": (report.get("cross_model_result") or {}).get("enabled"),
        "cross_model_fallback": (report.get("cross_model_result") or {}).get(
            "deterministic_fallback"
        ),
    }


def main() -> None:
    print("=" * 72)
    print(f"입력: {SAMPLE}")
    print("=" * 72)

    # Environment snapshot
    env = {
        "CS_ENABLE_LLM_RUNTIME": os.environ.get("CS_ENABLE_LLM_RUNTIME", "(unset)"),
        "CODEX_API_KEY": "(set)" if os.environ.get("CODEX_API_KEY") else "(unset)",
        "OPENAI_API_KEY": "(set)" if os.environ.get("OPENAI_API_KEY") else "(unset)",
        "CS_DETERMINISTIC_MODE": os.environ.get("CS_DETERMINISTIC_MODE", "(unset)"),
    }
    print("env snapshot:", env)
    print()

    # Mode A — deterministic
    print("-" * 72)
    print("# Mode A — deterministic_mode=True (fallback default)")
    print("-" * 72)
    decision_a, plan_a = build_runtime_plan(SAMPLE, deterministic_mode=True)
    print("routing+plan:", json.dumps(_summarize_plan(decision_a, plan_a), ensure_ascii=False))
    result_a = analyze_with_engine(SAMPLE)
    print(
        "report:",
        json.dumps(_summarize_report(result_a.state.final_report), ensure_ascii=False),
    )
    print()

    # Mode B — llm-runtime enabled (still safe — falls back when no key)
    print("-" * 72)
    print("# Mode B — deterministic_mode=False (LLM runtime path)")
    print("-" * 72)
    decision_b, plan_b = build_runtime_plan(SAMPLE, deterministic_mode=False)
    print("routing+plan:", json.dumps(_summarize_plan(decision_b, plan_b), ensure_ascii=False))
    # engine은 환경변수만 따르므로 직접 분석은 envvar 의존
    if os.environ.get("CS_ENABLE_LLM_RUNTIME") == "1":
        result_b = analyze_with_engine(SAMPLE)
        print(
            "report:",
            json.dumps(_summarize_report(result_b.state.final_report), ensure_ascii=False),
        )
    else:
        print("report: (CS_ENABLE_LLM_RUNTIME=1 미설정 — engine 실행 생략)")
    print()

    # Diff summary
    print("=" * 72)
    print("# 차이 요약")
    print("=" * 72)
    diff = {
        "model_plan_identical": _summarize_plan(decision_a, plan_a)
        == _summarize_plan(decision_b, plan_b),
        "mode_a_estimated_cost": plan_a.get("estimated_cost_usd"),
        "mode_b_estimated_cost": plan_b.get("estimated_cost_usd"),
        "mode_a_deterministic_flag": plan_a.get("deterministic_mode"),
        "mode_b_deterministic_flag": plan_b.get("deterministic_mode"),
    }
    print(json.dumps(diff, ensure_ascii=False, indent=2))
    print()
    print(
        "해석: API key 부재 시에도 Mode B는 routing/model plan을 결정하지만, "
        "실제 LLM 호출은 LLMClient가 silently fallback합니다 (각 호출 결과의 "
        "deterministic_fallback=True). 실키 보유 + CS_ENABLE_LLM_RUNTIME=1 환경에서만 "
        "LLM advisory/validation이 실제 발생합니다."
    )


if __name__ == "__main__":
    main()
