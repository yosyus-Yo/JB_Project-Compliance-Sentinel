"""오류회복(resilience) 배선 테스트 — 가이드 제2장 회복 5종.

agent_shield_bridge.resilient_tool_call이 외부 도구 호출에 retry·timeout·fallback·
circuit을 적용하는지(AgentShield resilience 위임 + fail-safe) 검증.
"""
from __future__ import annotations

import pytest

from compliance_sentinel import agent_shield_bridge as bridge


@pytest.fixture(autouse=True)
def _reset():
    bridge.reset_resilience_circuits()
    yield
    bridge.reset_resilience_circuits()


def test_success_passthrough():
    assert bridge.resilient_tool_call(lambda: 42, tool_name="ok", idempotent=True) == 42


def test_idempotent_retry_then_fallback():
    """멱등 read는 retry(backoff) 후 최종 실패 시 fallback으로 graceful degradation."""
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("down")

    result = bridge.resilient_tool_call(
        boom, tool_name="retry", idempotent=True, max_attempts=3, fallback=lambda: "FB"
    )
    assert result == "FB"
    assert calls["n"] == 3  # retry 적용(3회 시도)


def test_non_idempotent_no_retry():
    """비멱등(POST 등)은 재시도하지 않는다 — 가이드 "비가역 작업 중복 방지"."""
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("down")

    result = bridge.resilient_tool_call(
        boom, tool_name="nonidem", idempotent=False, fallback=lambda: "FB"
    )
    assert result == "FB"
    assert calls["n"] == 1  # 단 1회(재시도 없음)


def test_failsafe_without_agentshield(monkeypatch):
    """AgentShield 미설치/미접근 시 fail-safe: 직접 호출 + fallback(회복 없이도 동작)."""
    monkeypatch.setattr(bridge, "_ensure_agent_shield_importable", lambda: False)
    assert bridge.resilient_tool_call(lambda: 7, tool_name="x", idempotent=True) == 7

    def boom():
        raise RuntimeError("down")

    assert bridge.resilient_tool_call(boom, tool_name="x", idempotent=True, fallback=lambda: "FB") == "FB"


def test_circuit_breaker_opens_on_repeated_failure():
    """반복 실패 시 circuit이 open → 이후 호출은 fn을 실행하지 않고 즉시 fallback(연쇄 장애 차단)."""
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("down")

    # 기본 failure_threshold=5 — 비멱등(1회/호출)으로 충분히 실패시켜 circuit open 유도.
    for _ in range(8):
        bridge.resilient_tool_call(boom, tool_name="cb", idempotent=False, fallback=lambda: "FB")
    before = calls["n"]

    # circuit open 상태 — fn 미실행하고 fast fallback이어야 함.
    result = bridge.resilient_tool_call(boom, tool_name="cb", idempotent=False, fallback=lambda: "FB")
    assert result == "FB"
    assert calls["n"] == before  # circuit open으로 fn이 호출되지 않음
