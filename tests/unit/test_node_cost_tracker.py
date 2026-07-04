"""node_cost_tracker.py — 노드별 실측 cost attribution 단위/통합 테스트."""
from __future__ import annotations

import pytest

from compliance_sentinel.node_cost_tracker import (
    aggregate_node_cost,
    compute_cost,
    instrument_node,
    report_from_state,
)


class TestComputeCost:
    def test_basic_in_out(self):
        # gpt-5.5: in 1.25, out 10.0 per 1M
        c = compute_cost("gpt-5.5", tokens_in=1000, tokens_out=500, cached_tokens=0)
        assert c == pytest.approx((1000 * 1.25 + 500 * 10.0) / 1e6)

    def test_cached_discount(self):
        # cached 800/1000 input → 200 비-cached + 800 cached(0.125)
        c = compute_cost("gpt-5.5", tokens_in=1000, tokens_out=0, cached_tokens=800)
        assert c == pytest.approx((200 * 1.25 + 800 * 0.125) / 1e6)

    def test_mini_model(self):
        c = compute_cost("gpt-5.4-mini", 1000, 1000, 0)
        assert c == pytest.approx((1000 * 0.25 + 1000 * 2.0) / 1e6)

    def test_unknown_model_falls_back_to_deep(self):
        # 미지 gpt-5 변형 → gpt-5.5 단가(보수적)
        c = compute_cost("gpt-5-experimental", 1000, 0, 0)
        assert c == pytest.approx(1000 * 1.25 / 1e6)

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("CS_PRICE_GPT_5_5_IN", "99.0")
        c = compute_cost("gpt-5.5", 1000, 0, 0)
        assert c == pytest.approx(1000 * 99.0 / 1e6)

    def test_zero_tokens(self):
        assert compute_cost("gpt-5.5", 0, 0, 0) == 0.0


class TestAggregateNodeCost:
    def test_multi_call_aggregation(self):
        nc = aggregate_node_cost("board", [
            {"model": "gpt-5.5", "prompt_tokens": 100, "completion_tokens": 50, "cached_tokens": 0},
            {"model": "gpt-5.4-mini", "prompt_tokens": 200, "completion_tokens": 100, "cached_tokens": 0},
        ], latency_ms=42.5)
        assert nc.llm_calls == 2
        assert nc.tokens_in == 300
        assert nc.tokens_out == 150
        assert nc.latency_ms == 42.5
        assert nc.cost_usd > 0

    def test_no_llm_call_records_latency_only(self):
        nc = aggregate_node_cost("understand", [], latency_ms=12.3)
        assert nc.llm_calls == 0
        assert nc.tokens_in == 0
        assert nc.cost_usd == 0.0
        assert nc.latency_ms == 12.3


class TestReportFromState:
    def test_aggregates_by_node(self):
        report = report_from_state([
            {"node_id": "a", "tokens_in": 100, "tokens_out": 50, "latency_ms": 10.0, "llm_calls": 1, "cost_usd": 0.001},
            {"node_id": "b", "tokens_in": 200, "tokens_out": 100, "latency_ms": 20.0, "llm_calls": 1, "cost_usd": 0.002},
        ])
        d = report.as_dict()
        assert d["totals"]["nodes"] == 2
        assert d["totals"]["tokens_in"] == 300
        assert d["totals"]["cost_usd"] == pytest.approx(0.003)
        assert d["totals"]["evidence_level"] == "measured"

    def test_same_node_id_accumulates(self):
        # revise loop 백엣지: 동일 node_id 재진입 → 누적
        report = report_from_state([
            {"node_id": "rewrite_loop", "tokens_in": 100, "tokens_out": 0, "latency_ms": 10.0, "llm_calls": 1, "cost_usd": 0.001},
            {"node_id": "rewrite_loop", "tokens_in": 150, "tokens_out": 0, "latency_ms": 12.0, "llm_calls": 1, "cost_usd": 0.0015},
        ])
        assert report.by_node["rewrite_loop"].tokens_in == 250
        assert report.by_node["rewrite_loop"].llm_calls == 2
        assert report.by_node["rewrite_loop"].latency_ms == pytest.approx(22.0)


class _FakeClient:
    """call_log만 갖는 최소 llm_client stub."""
    def __init__(self):
        self.call_log: list = []


class TestInstrumentNode:
    def test_records_latency_and_token_delta(self):
        client = _FakeClient()

        def fake_node(state):
            # 노드 실행 중 LLM 2회 호출됐다고 가정
            client.call_log.append({"model": "gpt-5.5", "prompt_tokens": 100, "completion_tokens": 50, "cached_tokens": 0})
            client.call_log.append({"model": "gpt-5.5", "prompt_tokens": 80, "completion_tokens": 40, "cached_tokens": 0})
            return {"some_key": "v"}

        wrapped = instrument_node("board", fake_node, client)
        result = wrapped({"node_costs": []})
        assert result["some_key"] == "v"
        costs = result["node_costs"]
        assert len(costs) == 1
        assert costs[0]["node_id"] == "board"
        assert costs[0]["llm_calls"] == 2
        assert costs[0]["tokens_in"] == 180
        assert costs[0]["latency_ms"] >= 0

    def test_non_llm_node_zero_tokens(self):
        client = _FakeClient()
        wrapped = instrument_node("noop", lambda s: {"x": 1}, client)
        result = wrapped({})
        assert result["node_costs"][0]["llm_calls"] == 0
        assert result["node_costs"][0]["tokens_in"] == 0


@pytest.fixture
def langgraph_env(monkeypatch):
    monkeypatch.setenv("USE_LANGGRAPH", "1")
    monkeypatch.setenv("CS_ENABLE_LLM_RUNTIME", "0")
    monkeypatch.setenv("CS_DISABLE_QDRANT", "1")
    yield


class TestE2EPerNodeCost:
    def test_marketing_per_node_cost(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.marketing_langgraph_adapter import build_graph
        graph = build_graph(audit_store=AuditStore(tmp_audit_path))
        out = graph.invoke({"input_text": "원금 보장 연 8% 확정 수익 무제한", "retry_count": 0})
        pnc = out.get("final_report", {}).get("per_node_cost", {})
        assert pnc, "per_node_cost 누락"
        assert pnc["totals"]["evidence_level"] == "measured"
        assert pnc["totals"]["nodes"] >= 8
        assert pnc["totals"]["latency_ms"] >= 0
        # 모든 노드가 latency 기록 (구조 완전성)
        assert all("latency_ms" in n for n in pnc["by_node"])

    def test_compliance_per_node_cost(self, langgraph_env, tmp_audit_path):
        from compliance_sentinel.audit import AuditStore
        from compliance_sentinel.langgraph_adapter import build_graph
        graph = build_graph(audit_store=AuditStore(tmp_audit_path))
        out = graph.invoke({"input_text": "대출 약관 제3조 연체이자율 24% 검토", "retry_count": 0})
        pnc = out.get("final_report", {}).get("per_node_cost", {})
        assert pnc, "per_node_cost 누락"
        node_ids = [n["node_id"] for n in pnc["by_node"]]
        assert "final_report" in node_ids
        assert "board_review" in node_ids
        assert pnc["totals"]["nodes"] >= 12
