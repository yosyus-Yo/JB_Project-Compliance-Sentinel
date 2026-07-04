"""langgraph_runtime.py — env helpers + thread_id + compile_options + HITL gate."""
from __future__ import annotations

import pytest

from compliance_sentinel.langgraph_runtime import (
    compile_options,
    config_for_input,
    env_flag,
    human_review_gate_metadata,
    make_thread_id,
)


class TestEnvFlag:
    def test_default_false(self, monkeypatch):
        monkeypatch.delenv("CS_TEST_FLAG", raising=False)
        assert env_flag("CS_TEST_FLAG", default="0") is False

    def test_true_when_1(self, monkeypatch):
        monkeypatch.setenv("CS_TEST_FLAG", "1")
        assert env_flag("CS_TEST_FLAG") is True

    def test_false_when_0(self, monkeypatch):
        monkeypatch.setenv("CS_TEST_FLAG", "0")
        assert env_flag("CS_TEST_FLAG") is False

    def test_true_when_yes(self, monkeypatch):
        monkeypatch.setenv("CS_TEST_FLAG", "yes")
        assert env_flag("CS_TEST_FLAG") is True

    def test_true_when_on(self, monkeypatch):
        monkeypatch.setenv("CS_TEST_FLAG", "on")
        assert env_flag("CS_TEST_FLAG") is True

    def test_true_when_TRUE_uppercase(self, monkeypatch):
        monkeypatch.setenv("CS_TEST_FLAG", "TRUE")
        assert env_flag("CS_TEST_FLAG") is True

    def test_whitespace_stripped(self, monkeypatch):
        monkeypatch.setenv("CS_TEST_FLAG", "  1  ")
        assert env_flag("CS_TEST_FLAG") is True


class TestMakeThreadId:
    def test_returns_string(self):
        tid = make_thread_id("input text")
        assert isinstance(tid, str)
        assert len(tid) > 0

    def test_deterministic_same_input(self):
        assert make_thread_id("same") == make_thread_id("same")

    def test_different_inputs_different_ids(self):
        assert make_thread_id("a") != make_thread_id("b")

    def test_default_prefix_cs(self):
        tid = make_thread_id("input")
        assert tid.startswith("cs-")

    def test_custom_prefix(self):
        tid = make_thread_id("text", prefix="custom")
        assert tid.startswith("custom-")

    def test_id_length_consistent(self):
        # prefix + "-" + 16 hex chars
        tid = make_thread_id("input")
        assert len(tid) == len("cs-") + 16


class TestConfigForInput:
    def test_disabled_by_default_returns_none(self, monkeypatch):
        monkeypatch.delenv("CS_LANGGRAPH_CHECKPOINT", raising=False)
        config, tid = config_for_input("text")
        assert config is None
        assert tid is None

    def test_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("CS_LANGGRAPH_CHECKPOINT", "1")
        config, tid = config_for_input("text")
        assert config is not None
        assert "configurable" in config
        assert tid is not None

    def test_explicit_enable_overrides_env(self, monkeypatch):
        monkeypatch.delenv("CS_LANGGRAPH_CHECKPOINT", raising=False)
        config, tid = config_for_input("text", enable_checkpoint=True)
        assert config is not None
        assert tid is not None

    def test_explicit_disable_overrides_env(self, monkeypatch):
        monkeypatch.setenv("CS_LANGGRAPH_CHECKPOINT", "1")
        config, tid = config_for_input("text", enable_checkpoint=False)
        assert config is None

    def test_custom_thread_id_env(self, monkeypatch):
        monkeypatch.setenv("CS_LANGGRAPH_CHECKPOINT", "1")
        monkeypatch.setenv("CS_LANGGRAPH_THREAD_ID", "custom-thread-x")
        config, tid = config_for_input("text")
        assert tid == "custom-thread-x"
        assert config["configurable"]["thread_id"] == "custom-thread-x"


class TestCompileOptions:
    def test_disabled_returns_empty_kwargs(self, monkeypatch):
        monkeypatch.delenv("CS_LANGGRAPH_CHECKPOINT", raising=False)
        monkeypatch.delenv("CS_LANGGRAPH_INTERRUPT_BEFORE_HUMAN_GATE", raising=False)
        kwargs, metadata = compile_options()
        assert kwargs == {}
        assert metadata["checkpoint_enabled"] is False
        assert metadata["checkpointer"] == "none"
        assert metadata["interrupt_before"] == []

    def test_enabled_via_env_adds_checkpointer(self, monkeypatch):
        monkeypatch.setenv("CS_LANGGRAPH_CHECKPOINT", "1")
        kwargs, metadata = compile_options()
        # checkpointer 추가됨 (InMemorySaver 가용 시)
        assert metadata["checkpoint_enabled"] is True or metadata["checkpointer"] == "unavailable"

    def test_interrupt_before_forces_checkpoint(self, monkeypatch):
        monkeypatch.delenv("CS_LANGGRAPH_CHECKPOINT", raising=False)
        kwargs, metadata = compile_options(interrupt_before=["human_review_gate"])
        assert metadata["interrupt_before"] == ["human_review_gate"]
        assert metadata["checkpoint_enabled"] is True or metadata["checkpointer"] == "unavailable"

    def test_interrupt_before_via_env(self, monkeypatch):
        monkeypatch.setenv("CS_LANGGRAPH_INTERRUPT_BEFORE_HUMAN_GATE", "1")
        kwargs, metadata = compile_options()
        assert metadata["interrupt_before"] == ["human_review_gate"]

    def test_custom_checkpointer_passed(self, monkeypatch):
        monkeypatch.delenv("CS_LANGGRAPH_CHECKPOINT", raising=False)

        class FakeCheckpointer:
            pass

        cp = FakeCheckpointer()
        kwargs, metadata = compile_options(enable_checkpoint=True, checkpointer=cp)
        assert kwargs.get("checkpointer") is cp
        assert metadata["checkpointer"] == "FakeCheckpointer"

    def test_explicit_disable_overrides_env(self, monkeypatch):
        monkeypatch.setenv("CS_LANGGRAPH_CHECKPOINT", "1")
        kwargs, metadata = compile_options(enable_checkpoint=False)
        # interrupt_before도 없으면 disabled
        if metadata["checkpoint_enabled"]:
            # interrupt_before가 env로 설정됐을 수도 있으니 확인
            assert metadata["interrupt_before"] != []


class TestHumanReviewGateMetadata:
    def test_required_true(self):
        result = human_review_gate_metadata(required=True, reasons=["HIGH_RISK"])
        assert result["required"] is True
        assert result["reasons"] == ["HIGH_RISK"]
        assert result["gate"] == "human_review_gate"

    def test_required_false(self):
        result = human_review_gate_metadata(required=False, reasons=[])
        assert result["required"] is False
        assert result["reasons"] == []

    def test_custom_gate_name(self):
        result = human_review_gate_metadata(
            required=True, reasons=["X"], gate_name="custom_gate",
        )
        assert result["gate"] == "custom_gate"

    def test_resume_instruction_present(self):
        result = human_review_gate_metadata(required=True, reasons=[])
        assert "resume_instruction" in result
        assert "audit_log_id" in result["resume_instruction"]

    def test_checkpoint_required_field(self):
        result = human_review_gate_metadata(required=True, reasons=[])
        assert result["checkpoint_required_for_interrupt_resume"] is True
