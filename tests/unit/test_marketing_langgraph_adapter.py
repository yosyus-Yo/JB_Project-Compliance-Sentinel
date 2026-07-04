"""marketing_langgraph_adapter.py — full marketing LangGraph wrapper + invoke."""
from __future__ import annotations

import pytest


@pytest.fixture
def langgraph_env(monkeypatch):
    monkeypatch.setenv("USE_LANGGRAPH", "1")
    monkeypatch.setenv("CS_ENABLE_LLM_RUNTIME", "0")
    monkeypatch.setenv("CS_DISABLE_QDRANT", "1")
    yield


class TestImport:
    def test_module_imports(self):
        import compliance_sentinel.marketing_langgraph_adapter as adapter
        assert adapter is not None


class TestIsAvailable:
    def test_returns_bool(self):
        from compliance_sentinel.marketing_langgraph_adapter import is_available
        assert isinstance(is_available(), bool)

    def test_env_disabled_returns_false(self, monkeypatch):
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        from compliance_sentinel.marketing_langgraph_adapter import is_available
        assert is_available() is False

    def test_env_enabled_returns_true(self, langgraph_env):
        from compliance_sentinel.marketing_langgraph_adapter import is_available
        assert is_available() is True


class TestStateTypedDict:
    def test_state_type_exists(self):
        from compliance_sentinel.marketing_langgraph_adapter import MarketingGraphState
        assert MarketingGraphState is not None


class TestBuildGraph:
    def test_basic_build(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.marketing_langgraph_adapter import build_graph
        store = AuditStore(tmp_audit_path)
        graph = build_graph(audit_store=store)
        assert graph is not None

    def test_graph_invoke_basic_marketing(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.marketing_langgraph_adapter import build_graph
        store = AuditStore(tmp_audit_path)
        graph = build_graph(audit_store=store)
        output = graph.invoke({"input_text": "정기예금 광고 카피", "retry_count": 0})
        assert "final_report" in output or "approval_status" in output

    def test_graph_invoke_high_risk_marketing(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.marketing_langgraph_adapter import build_graph
        store = AuditStore(tmp_audit_path)
        graph = build_graph(audit_store=store)
        output = graph.invoke({
            "input_text": "100% 보장 무위험 확정 수익 상품",
            "retry_count": 0,
        })
        # findings 발생
        assert output.get("findings") is not None or output.get("approval_status")

    def test_graph_attaches_runtime_metadata(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.marketing_langgraph_adapter import build_graph
        store = AuditStore(tmp_audit_path)
        graph = build_graph(audit_store=store)
        output = graph.invoke({"input_text": "광고 텍스트", "retry_count": 0})
        # langgraph_runtime metadata 또는 final_report에 attach됨
        assert "langgraph_runtime" in output or "final_report" in output


class TestUnderstandNode:
    def test_understand_returns_classifications(self):
        from compliance_sentinel.marketing_langgraph_adapter import _understand
        result = _understand({
            "redacted_content": "정기예금 가입 안내 광고",
            "input_text": "정기예금 가입 안내 광고",
        })
        assert "language" in result
        assert "channel" in result
        assert "findings" in result
        assert "approval_status" in result


class TestIntakeNode:
    def test_intake_redacts_and_plans(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.llm_client import LLMClient
        from compliance_sentinel.budget_guard import from_env as budget_guard_from_env
        from compliance_sentinel.agent_model_guard import ModelGuard
        from compliance_sentinel.marketing_langgraph_adapter import _make_intake

        llm = LLMClient(
            budget_guard=budget_guard_from_env(),
            model_guard=ModelGuard.from_env(),
        )
        node = _make_intake(llm)
        result = node({"input_text": "홍길동 광고 카피 010-1234-5678"})
        assert "redacted_content" in result
        assert "routing_decision" in result
        assert "model_plan" in result


class _StubFinding:
    """severity 속성만 필요한 finding stub (조건 함수는 getattr(item, 'severity', '') 사용)."""

    def __init__(self, severity: str):
        self.severity = severity


class TestReviseLoop:
    """자가교정 폐쇄 루프 (방식 C 하이브리드) — PDF F-04."""

    # --- 조건 함수 단위 테스트 (순수 함수) ---

    def test_revise_gate_severe_finding_enters_loop(self):
        # revise 루프는 수정 제안 토글(include_revision=True)에서만 진입
        from compliance_sentinel.marketing_langgraph_adapter import _revise_gate
        assert _revise_gate({"findings": [_StubFinding("CRITICAL")], "retry_count": 0, "include_revision": True}) == "revise"

    def test_revise_gate_rejected_enters_loop(self):
        from compliance_sentinel.marketing_langgraph_adapter import _revise_gate
        assert _revise_gate({"findings": [], "approval_status": "REJECTED", "retry_count": 0, "include_revision": True}) == "revise"

    def test_revise_gate_review_only_skips_loop(self):
        # 수정 제안 토글 OFF(기본) → 심각해도 revise 루프 미진입 (심의만)
        from compliance_sentinel.marketing_langgraph_adapter import _revise_gate
        assert _revise_gate({"findings": [_StubFinding("CRITICAL")], "retry_count": 0}) == "validate"
        assert _revise_gate({"findings": [], "approval_status": "REJECTED", "retry_count": 0, "include_revision": False}) == "validate"

    def test_revise_gate_mild_skips_loop(self):
        from compliance_sentinel.marketing_langgraph_adapter import _revise_gate
        assert _revise_gate({"findings": [_StubFinding("LOW")], "approval_status": "APPROVED", "retry_count": 0}) == "validate"

    def test_revise_gate_retry_limit_skips_loop(self):
        # 한도 도달 시 gate는 직선 통과 (human_review_gate가 후속 HITL 처리)
        from compliance_sentinel.marketing_langgraph_adapter import _revise_gate
        assert _revise_gate({"findings": [_StubFinding("HIGH")], "retry_count": 3}) == "validate"

    def test_revise_branch_no_new_risk_passes(self):
        from compliance_sentinel.marketing_langgraph_adapter import _revise_branch
        assert _revise_branch({"delta_findings": [], "retry_count": 1}) == "validate"

    def test_revise_branch_new_risk_retries(self):
        from compliance_sentinel.marketing_langgraph_adapter import _revise_branch
        assert _revise_branch({"delta_findings": [_StubFinding("HIGH")], "retry_count": 1}) == "revise"

    def test_revise_branch_retry_limit_forces_hitl(self):
        # PDF F-04: "통과까지 ≤3회, 초과 시 HUMAN_REVIEW_REQUIRED"
        from compliance_sentinel.marketing_langgraph_adapter import _revise_branch
        assert _revise_branch({"delta_findings": [_StubFinding("CRITICAL")], "retry_count": 3}) == "human"

    # --- 그래프 무결성 ---

    def test_revise_nodes_registered(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.marketing_langgraph_adapter import build_graph
        graph = build_graph(audit_store=AuditStore(tmp_audit_path))
        nodes = set(graph.get_graph().nodes)
        assert "rewrite_loop" in nodes
        assert "delta_screen" in nodes

    # --- E2E (deterministic — 무한루프 없음) ---

    def test_deterministic_e2e_no_infinite_loop(self, langgraph_env, tmp_audit_path):
        # CASE A: severe 입력 → revise 진입하나 deterministic rewrite=None → 즉시 탈출
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.marketing_langgraph_adapter import build_graph
        graph = build_graph(audit_store=AuditStore(tmp_audit_path))
        output = graph.invoke({
            "input_text": "원금 보장 연 8% 확정 수익! 지금 가입하면 무제한 혜택",
            "retry_count": 0,
            "include_revision": True,  # revise 루프 진입 (수정 제안 토글 ON)
        })
        assert "final_report" in output
        assert int(output.get("retry_count", 0)) <= 3  # 하드 바운드 — 무한루프 없음

    def test_deterministic_revise_trace_recorded(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.marketing_langgraph_adapter import build_graph
        graph = build_graph(audit_store=AuditStore(tmp_audit_path))
        output = graph.invoke({
            "input_text": "원금 보장 연 8% 확정 수익! 무제한 혜택 보장",
            "retry_count": 0,
            "include_revision": True,  # revise 루프 진입 (수정 제안 토글 ON)
        })
        # revise 루프 진입 시 trace가 보고서에 노출됨 (T4 audit 추적)
        if int(output.get("retry_count", 0)) >= 1:
            assert "revise_trace" in output.get("final_report", {})
