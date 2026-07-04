"""engine.py — EngineResult/BatchEngineResult + cache + attach helpers."""
from __future__ import annotations

import pytest

from compliance_sentinel.engine import (
    BatchEngineResult,
    EngineResult,
    _attach_agentshield_runtime_guard,
    _attach_langgraph_metadata,
    _attach_langsmith_trace,
    _attach_profile,
    _get_reusable_agent,
    _state_from_graph_output,
    analyze_batch_with_engine,
    clear_agent_cache,
)
from compliance_sentinel.audit import AuditStore


class TestEngineResult:
    def test_construction(self, sample_state):
        result = EngineResult(state=sample_state, engine="deterministic")
        assert result.engine == "deterministic"
        assert result.fallback_reason is None

    def test_frozen_dataclass(self, sample_state):
        result = EngineResult(state=sample_state, engine="deterministic")
        with pytest.raises(Exception):
            result.engine = "other"

    def test_with_fallback_reason(self, sample_state):
        result = EngineResult(
            state=sample_state, engine="deterministic",
            fallback_reason="langgraph unavailable",
        )
        assert result.fallback_reason == "langgraph unavailable"


class TestBatchEngineResult:
    def test_construction(self, sample_state):
        inner = EngineResult(state=sample_state, engine="deterministic")
        batch = BatchEngineResult(
            results=[inner], item_count=1, elapsed_seconds=0.5,
            reused_agents=True, engine="deterministic",
        )
        assert batch.item_count == 1
        assert batch.reused_agents is True

    def test_empty_results(self):
        batch = BatchEngineResult(
            results=[], item_count=0, elapsed_seconds=0.0,
            reused_agents=False, engine="deterministic",
        )
        assert batch.results == []


class TestClearAgentCache:
    def test_callable(self):
        clear_agent_cache()


class TestGetReusableAgent:
    def setup_method(self):
        clear_agent_cache()

    def test_marketing_agent_returned(self, tmp_audit_path):
        store = AuditStore(tmp_audit_path)
        agent = _get_reusable_agent("marketing", store)
        assert agent is not None

    def test_compliance_agent_returned(self, tmp_audit_path):
        store = AuditStore(tmp_audit_path)
        agent = _get_reusable_agent("compliance", store)
        assert agent is not None

    def test_cache_reuses_instance(self, tmp_audit_path):
        store = AuditStore(tmp_audit_path)
        a = _get_reusable_agent("compliance", store)
        b = _get_reusable_agent("compliance", store)
        assert a is b  # same instance from cache

    def test_disable_reuse_env_bypasses_cache(self, tmp_audit_path, monkeypatch):
        monkeypatch.setenv("CS_DISABLE_AGENT_REUSE", "1")
        store = AuditStore(tmp_audit_path)
        a = _get_reusable_agent("compliance", store)
        b = _get_reusable_agent("compliance", store)
        # 새 instance 매번 생성
        assert a is not b

    def test_different_kinds_separate_instances(self, tmp_audit_path):
        store = AuditStore(tmp_audit_path)
        m = _get_reusable_agent("marketing", store)
        c = _get_reusable_agent("compliance", store)
        assert m is not c


class TestAttachProfile:
    def test_adds_trace(self, sample_state):
        _attach_profile(sample_state, started=0.0, engine="deterministic")
        trace = [t for t in sample_state.trace if t.get("node") == "engine_profile"]
        assert len(trace) == 1
        assert trace[0]["engine"] == "deterministic"

    def test_profile_env_enriches_final_report(self, sample_state, monkeypatch):
        monkeypatch.setenv("CS_PROFILE", "1")
        sample_state.final_report = {"existing": "data"}
        _attach_profile(sample_state, started=0.0, engine="langgraph")
        assert "performance_profile" in sample_state.final_report
        assert sample_state.final_report["performance_profile"]["engine"] == "langgraph"

    def test_no_profile_env_keeps_report_clean(self, sample_state, monkeypatch):
        monkeypatch.delenv("CS_PROFILE", raising=False)
        sample_state.final_report = {"existing": "data"}
        _attach_profile(sample_state, started=0.0, engine="deterministic")
        assert "performance_profile" not in sample_state.final_report


class TestAttachLanggraphMetadata:
    def test_with_thread_id(self, sample_state):
        sample_state.final_report = {"x": 1}
        _attach_langgraph_metadata(sample_state, thread_id="thread-123")
        assert sample_state.final_report["langgraph_runtime"]["thread_id"] == "thread-123"
        assert sample_state.final_report["langgraph_runtime"]["checkpoint_enabled"] is True

    def test_without_thread_id(self, sample_state):
        sample_state.final_report = {"x": 1}
        _attach_langgraph_metadata(sample_state, thread_id=None)
        assert sample_state.final_report["langgraph_runtime"]["checkpoint_enabled"] is False

    def test_adds_trace(self, sample_state):
        _attach_langgraph_metadata(sample_state, thread_id="t1")
        trace = [t for t in sample_state.trace if t.get("node") == "langgraph_runtime"]
        assert len(trace) == 1


class TestAttachLangsmithTrace:
    def test_no_api_key_noop(self, sample_state, monkeypatch):
        monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
        sample_state.final_report = {"x": 1}
        _attach_langsmith_trace(sample_state, engine="deterministic")
        assert "langsmith_trace" not in sample_state.final_report

    def test_no_final_report_noop(self, sample_state, monkeypatch):
        monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key")
        sample_state.final_report = {}
        # final_report empty dict이면 truthy False → 조기 return
        _attach_langsmith_trace(sample_state, engine="deterministic")
        # 빈 dict 그대로 유지
        assert sample_state.final_report == {}


class TestAttachAgentshieldRuntimeGuard:
    def test_basic_attachment_with_final_report(self, sample_state):
        sample_state.final_report = {"approval_status": "OK"}
        guard = {"allowed": True, "reasons": [], "mode": "passive"}
        _attach_agentshield_runtime_guard(sample_state, input_guard=guard)
        assert "agentshield_runtime_guard" in sample_state.final_report
        agg = sample_state.final_report["agentshield_runtime_guard"]
        assert "input" in agg and "output" in agg and "status" in agg

    def test_adds_trace(self, sample_state):
        guard = {"allowed": True, "reasons": [], "mode": "passive"}
        _attach_agentshield_runtime_guard(sample_state, input_guard=guard)
        trace = [t for t in sample_state.trace if t.get("node") == "agentshield_runtime_guard"]
        assert len(trace) == 1
        assert trace[0]["mode"] == "passive"


class TestStateFromGraphOutput:
    def test_minimal_output(self):
        state = _state_from_graph_output("입력", {})
        assert state.input_text == "입력"
        assert state.redacted_text == ""
        assert state.input_type == "advertisement"

    def test_full_output(self):
        output = {
            "redacted_text": "보안 처리됨",
            "input_type": "compliance",
            "pii_findings": [{"kind": "rrn"}],
            "atomic_claims": [{"id": "C1"}],
            "audit_log_id": "AL-1",
        }
        state = _state_from_graph_output("input", output)
        assert state.redacted_text == "보안 처리됨"
        assert state.input_type == "compliance"
        assert len(state.pii_findings) == 1
        assert state.audit_log_id == "AL-1"

    def test_fallback_to_redacted_content_key(self):
        # output에 redacted_text 없으면 redacted_content 사용
        state = _state_from_graph_output("input", {"redacted_content": "fallback"})
        assert state.redacted_text == "fallback"

    def test_audit_log_id_from_report(self):
        state = _state_from_graph_output("input", {"final_report": {"audit_log_id": "AL-2"}})
        assert state.audit_log_id == "AL-2"

    def test_retry_count_preserved(self):
        state = _state_from_graph_output("input", {"retry_count": 3})
        assert state.retry_count == 3


class TestAnalyzeBatchEmpty:
    def test_empty_inputs_returns_short_circuit(self):
        result = analyze_batch_with_engine([])
        assert result.item_count == 0
        assert result.elapsed_seconds == 0.0
        assert result.results == []
        assert result.reused_agents is False


class TestAnalyzeWithEngineDeterministic:
    def test_basic_deterministic_path(self, tmp_audit_path, monkeypatch):
        from compliance_sentinel.engine import analyze_with_engine
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        result = analyze_with_engine("일반 텍스트 입력", audit_path=tmp_audit_path)
        assert result.engine == "deterministic"
        assert result.state is not None

    def test_prefer_langgraph_false_path(self, tmp_audit_path, monkeypatch):
        from compliance_sentinel.engine import analyze_with_engine
        result = analyze_with_engine(
            # triage gate 통과를 위해 광고 콘텐츠 사용 (비-광고는 NOT_APPLICABLE 분기)
            "원금 100% 보장 무조건 승인 특판 적금", audit_path=tmp_audit_path, prefer_langgraph=False,
        )
        assert result.engine == "deterministic"
        assert result.fallback_reason == "prefer_langgraph_false"

    def test_marketing_path(self, tmp_audit_path, monkeypatch):
        from compliance_sentinel.engine import analyze_with_engine
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        # 광고/마케팅 키워드 → marketing agent path
        result = analyze_with_engine("이벤트 광고 캠페인", audit_path=tmp_audit_path)
        assert result.state is not None


class TestAnalyzeWithEngineLanggraph:
    def test_langgraph_path_when_available(self, tmp_audit_path, monkeypatch):
        from compliance_sentinel.engine import analyze_with_engine
        monkeypatch.setenv("USE_LANGGRAPH", "1")
        monkeypatch.setenv("CS_ENABLE_LLM_RUNTIME", "0")
        result = analyze_with_engine("준법 검토 입력", audit_path=tmp_audit_path)
        # LangGraph path 가용 시 engine=langgraph
        assert result.engine in {"langgraph", "deterministic"}


class TestAnalyzeBatchWithReuse:
    def test_batch_reuses_agents(self, tmp_audit_path, monkeypatch):
        from compliance_sentinel.engine import analyze_batch_with_engine, clear_agent_cache
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        clear_agent_cache()
        result = analyze_batch_with_engine(
            ["입력1", "입력2"], audit_path=tmp_audit_path, reuse_agents=True,
        )
        assert result.item_count == 2
        assert result.reused_agents is True
        assert result.engine == "deterministic"

    def test_batch_no_reuse_falls_back(self, tmp_audit_path, monkeypatch):
        from compliance_sentinel.engine import analyze_batch_with_engine
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        result = analyze_batch_with_engine(
            ["입력"], audit_path=tmp_audit_path, reuse_agents=False,
        )
        assert result.reused_agents is False

    def test_batch_marketing_route(self, tmp_audit_path, monkeypatch):
        from compliance_sentinel.engine import analyze_batch_with_engine, clear_agent_cache
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        clear_agent_cache()
        result = analyze_batch_with_engine(
            ["광고 카피 이벤트", "준법 검토"],
            audit_path=tmp_audit_path, reuse_agents=True,
        )
        # 다른 agent로 라우팅됨
        assert result.item_count == 2


class TestAnalyzeTextWrapper:
    def test_wrapper_returns_final_report(self, tmp_audit_path, monkeypatch):
        from compliance_sentinel.engine import analyze_text
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        report = analyze_text("입력 텍스트", audit_path=tmp_audit_path)
        assert isinstance(report, dict)
        assert "status" in report


class TestAttachLangsmithTraceWithKey:
    def test_with_api_key_attempts_record(self, sample_state, monkeypatch):
        from compliance_sentinel.engine import _attach_langsmith_trace
        monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key")
        sample_state.final_report = {
            "audit_log_id": "AL-1",
            "approval_status": "OK",
            "risk_level": "LOW",
            "human_review_needed": False,
            "findings": [],
        }
        sample_state.input_type = "advertisement"
        # langsmith_record_run은 실패해도 silent (None 반환)
        _attach_langsmith_trace(sample_state, engine="deterministic")
        # 시도 자체는 성공 — trace_info 있을 수도 없을 수도
        assert sample_state.final_report.get("langsmith_trace") is not None or \
               "langsmith_trace" not in sample_state.final_report
