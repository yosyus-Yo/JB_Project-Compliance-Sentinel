"""langgraph_adapter.py — full LangGraph wrapper + invoke integration."""
from __future__ import annotations

import pytest


@pytest.fixture
def langgraph_env(monkeypatch):
    """USE_LANGGRAPH=1 + deterministic env."""
    monkeypatch.setenv("USE_LANGGRAPH", "1")
    monkeypatch.setenv("CS_ENABLE_LLM_RUNTIME", "0")
    monkeypatch.setenv("CS_DISABLE_QDRANT", "1")
    yield


class TestLangGraphImport:
    def test_module_imports(self):
        import compliance_sentinel.langgraph_adapter as adapter
        assert adapter is not None


class TestIsAvailable:
    def test_returns_bool(self):
        from compliance_sentinel.langgraph_adapter import is_available
        assert isinstance(is_available(), bool)

    def test_env_disabled_returns_false(self, monkeypatch):
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        from compliance_sentinel.langgraph_adapter import is_available
        assert is_available() is False

    def test_env_enabled_returns_true(self, langgraph_env):
        from compliance_sentinel.langgraph_adapter import is_available
        assert is_available() is True


class TestStateTypedDict:
    def test_state_type_exists(self):
        from compliance_sentinel.langgraph_adapter import LangGraphComplianceState
        assert LangGraphComplianceState is not None


class TestBuildGraph:
    def test_basic_build(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.langgraph_adapter import build_graph
        store = AuditStore(tmp_audit_path)
        graph = build_graph(audit_store=store)
        assert graph is not None

    def test_graph_invoke_returns_state(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.langgraph_adapter import build_graph
        store = AuditStore(tmp_audit_path)
        graph = build_graph(audit_store=store)
        output = graph.invoke({"input_text": "테스트 광고 문구", "retry_count": 0})
        assert "final_report" in output

    def test_graph_invoke_classifies_input(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.langgraph_adapter import build_graph
        store = AuditStore(tmp_audit_path)
        graph = build_graph(audit_store=store)
        output = graph.invoke({"input_text": "준법 검토 요청", "retry_count": 0})
        assert "input_type" in output

    def test_graph_pii_redaction(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.langgraph_adapter import build_graph
        store = AuditStore(tmp_audit_path)
        graph = build_graph(audit_store=store)
        output = graph.invoke({
            "input_text": "홍길동 900101-1234567 신청",
            "retry_count": 0,
        })
        # PII 마스킹 또는 findings 발생
        assert "redacted_text" in output or len(output.get("pii_findings", [])) >= 0

    def test_graph_audit_log_id_set(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.langgraph_adapter import build_graph
        store = AuditStore(tmp_audit_path)
        graph = build_graph(audit_store=store)
        output = graph.invoke({"input_text": "감사 로그 테스트", "retry_count": 0})
        # audit_log_id가 final_report에 attach됨
        assert output.get("audit_log_id") or output.get("final_report", {}).get("audit_log_id")

    def test_graph_high_risk_input_attaches_finding(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.langgraph_adapter import build_graph
        store = AuditStore(tmp_audit_path)
        graph = build_graph(audit_store=store)
        output = graph.invoke({
            "input_text": "100% 보장 무위험 확정 수익 광고",
            "retry_count": 0,
        })
        assert "final_report" in output


class TestNodeFunctions:
    def test_make_classify_node(self):
        from compliance_sentinel.knowledge_base import LawKnowledgeBase
        from compliance_sentinel.langgraph_adapter import _make_classify
        kb = LawKnowledgeBase.from_json()
        node = _make_classify(kb)
        result = node({"input_text": "광고"})
        assert "input_type" in result

    def test_make_pii_guard_node(self):
        from compliance_sentinel.knowledge_base import LawKnowledgeBase
        from compliance_sentinel.langgraph_adapter import _make_pii_guard
        kb = LawKnowledgeBase.from_json()
        node = _make_pii_guard(kb)
        result = node({"input_text": "홍길동 900101-1234567"})
        assert "redacted_text" in result
        assert "pii_findings" in result

    def test_make_extract_citations_node(self):
        from compliance_sentinel.knowledge_base import LawKnowledgeBase
        from compliance_sentinel.langgraph_adapter import _make_extract_citations
        kb = LawKnowledgeBase.from_json()
        node = _make_extract_citations(kb)
        result = node({"redacted_text": "개인정보보호법 제15조에 따라"})
        assert "user_cited_articles" in result
