"""Node-level cost attribution — LangGraph 노드별 토큰/지연시간/비용 실측 집계.

AgentCompiler `agentcompiler/observability/cost_attribution.py`의 NodeCost/CostAttribution
인터페이스와 호환되도록 설계 (record/report). 단 AgentCompiler는 shadow/dry-run 도구라
production 경로에 의존성을 넣지 않고 JB 내부에 자립 구현한다.

핵심 차이 (vs AgentCompiler shadow):
- AgentCompiler = simulated backend 추정 (evidence_level=simulated)
- 본 모듈 = 실제 llm_client.call_log 기반 **실측** 토큰 × 단가표 = 실측 비용

비용($)은 MODEL_PRICING(공개 가격 기반 [추정], 환경변수 override)로 환산.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from time import perf_counter
from typing import Optional

# ──────────────────────────────────────────────────────────────────
# 모델 단가표 (USD per 1M tokens). 공개 가격 기반 [추정] — 환경변수로 override.
#   CS_PRICE_<MODEL>_IN / _OUT / _CACHED (예: CS_PRICE_GPT_5_5_IN=1.25)
# cached input은 OpenAI 자동 prompt caching 할인 (gpt-5 계열 표준 input의 ~0.1x [추정]).
# ──────────────────────────────────────────────────────────────────

# (input_per_1m, output_per_1m, cached_input_per_1m)
_DEFAULT_PRICING: dict[str, tuple[float, float, float]] = {
    "gpt-5.5": (1.25, 10.00, 0.125),
    "gpt-5.4-mini": (0.25, 2.00, 0.025),
    "gpt-5.4-nano": (0.05, 0.40, 0.005),
}
# 모델명 prefix fallback (버전 suffix 변형 흡수).
_PREFIX_FALLBACK: list[tuple[str, str]] = [
    ("gpt-5.5", "gpt-5.5"),
    ("gpt-5.4-mini", "gpt-5.4-mini"),
    ("gpt-5.4-nano", "gpt-5.4-nano"),
    ("gpt-5", "gpt-5.5"),  # 알 수 없는 gpt-5 변형 → deep 단가로 보수적 추정
]


def _env_price(model: str, idx: int, default: float) -> float:
    key = "CS_PRICE_" + model.upper().replace(".", "_").replace("-", "_") + ("_IN", "_OUT", "_CACHED")[idx]
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _pricing_for(model: Optional[str]) -> tuple[float, float, float]:
    """모델명 → (input, output, cached) per-1M 단가. 미지 모델은 prefix fallback."""
    name = (model or "").strip()
    base = _DEFAULT_PRICING.get(name)
    if base is None:
        for prefix, mapped in _PREFIX_FALLBACK:
            if name.startswith(prefix):
                base = _DEFAULT_PRICING[mapped]
                break
    if base is None:
        base = _DEFAULT_PRICING["gpt-5.5"]  # 완전 미지 → 보수적(최고가)
    return (
        _env_price(name, 0, base[0]),
        _env_price(name, 1, base[1]),
        _env_price(name, 2, base[2]),
    )


def compute_cost(model: Optional[str], tokens_in: int, tokens_out: int, cached_tokens: int = 0) -> float:
    """실측 토큰 × 단가표 → USD. cached 입력 토큰은 할인 단가 적용.

    tokens_in은 cached_tokens를 포함한 전체 prompt 토큰이라 가정 (OpenAI usage 규약).
    비-cached 입력 = tokens_in - cached_tokens.
    """
    price_in, price_out, price_cached = _pricing_for(model)
    cached = max(0, min(cached_tokens, tokens_in))
    non_cached_in = max(0, tokens_in - cached)
    cost = (
        non_cached_in * price_in
        + cached * price_cached
        + max(0, tokens_out) * price_out
    ) / 1_000_000.0
    return round(cost, 6)


# ──────────────────────────────────────────────────────────────────
# 노드별 cost 집계 (AgentCompiler NodeCost/CostAttribution 호환)
# ──────────────────────────────────────────────────────────────────

@dataclass
class NodeCost:
    """단일 노드의 누적 실측 cost."""
    node_id: str
    tokens_in: int = 0
    tokens_out: int = 0
    cached_tokens: int = 0
    latency_ms: float = 0.0
    llm_calls: int = 0
    cost_usd: float = 0.0

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cached_tokens": self.cached_tokens,
            "latency_ms": round(self.latency_ms, 3),
            "llm_calls": self.llm_calls,
            "cost_usd": round(self.cost_usd, 6),
        }


def aggregate_node_cost(node_id: str, call_records: list, latency_ms: float) -> NodeCost:
    """노드가 발생시킨 llm_client.call_log 항목들 → NodeCost 실측 집계.

    call_records: [{model, prompt_tokens, completion_tokens, cached_tokens}, ...]
    LLM을 호출하지 않은 노드도 latency만 기록된 NodeCost를 반환 (구조 완전성).
    """
    nc = NodeCost(node_id=node_id, latency_ms=latency_ms, llm_calls=len(call_records))
    for rec in call_records:
        tin = int(rec.get("prompt_tokens", 0) or 0)
        tout = int(rec.get("completion_tokens", 0) or 0)
        cached = int(rec.get("cached_tokens", 0) or 0)
        nc.tokens_in += tin
        nc.tokens_out += tout
        nc.cached_tokens += cached
        nc.cost_usd += compute_cost(rec.get("model"), tin, tout, cached)
    nc.cost_usd = round(nc.cost_usd, 6)
    return nc


@dataclass
class CostReport:
    """전체 워크플로의 노드별 cost 집계 + 합계."""
    by_node: dict[str, NodeCost] = field(default_factory=dict)

    def total_tokens_in(self) -> int:
        return sum(n.tokens_in for n in self.by_node.values())

    def total_tokens_out(self) -> int:
        return sum(n.tokens_out for n in self.by_node.values())

    def total_latency_ms(self) -> float:
        return round(sum(n.latency_ms for n in self.by_node.values()), 3)

    def total_cost_usd(self) -> float:
        return round(sum(n.cost_usd for n in self.by_node.values()), 6)

    def as_dict(self) -> dict:
        return {
            "by_node": [n.as_dict() for n in self.by_node.values()],
            "totals": {
                "nodes": len(self.by_node),
                "tokens_in": self.total_tokens_in(),
                "tokens_out": self.total_tokens_out(),
                "latency_ms": self.total_latency_ms(),
                "cost_usd": self.total_cost_usd(),
                "evidence_level": "measured",  # vs AgentCompiler "simulated"
            },
        }


def instrument_node(node_id: str, fn, llm_client):
    """노드 실행을 감싸 실측 latency + llm_client.call_log 토큰 델타를 node_costs에 누적.

    공유 헬퍼 (compliance/marketing adapter 공용). per_node_cost report를 자체 생성하는
    final 노드는 본 래퍼로 감싸지 말 것 (이중 집계). LLM 미호출 노드도 latency 기록.
    """
    def wrapped(state: dict) -> dict:
        before = len(llm_client.call_log)
        t0 = perf_counter()
        result = fn(state) or {}
        latency_ms = (perf_counter() - t0) * 1000
        nc = aggregate_node_cost(node_id, llm_client.call_log[before:], latency_ms)
        costs = list(state.get("node_costs") or [])
        costs.append(nc.as_dict())
        result = dict(result)
        result["node_costs"] = costs
        return result
    return wrapped


def report_from_state(node_costs: list) -> CostReport:
    """state["node_costs"](list[dict]) → CostReport. 동일 node_id는 누적(루프 백엣지 대응)."""
    report = CostReport()
    for item in node_costs or []:
        nid = item.get("node_id", "?")
        existing = report.by_node.get(nid)
        if existing is None:
            report.by_node[nid] = NodeCost(
                node_id=nid,
                tokens_in=int(item.get("tokens_in", 0) or 0),
                tokens_out=int(item.get("tokens_out", 0) or 0),
                cached_tokens=int(item.get("cached_tokens", 0) or 0),
                latency_ms=float(item.get("latency_ms", 0.0) or 0.0),
                llm_calls=int(item.get("llm_calls", 0) or 0),
                cost_usd=float(item.get("cost_usd", 0.0) or 0.0),
            )
        else:  # 루프 재진입 노드 (revise loop) — 누적
            existing.tokens_in += int(item.get("tokens_in", 0) or 0)
            existing.tokens_out += int(item.get("tokens_out", 0) or 0)
            existing.cached_tokens += int(item.get("cached_tokens", 0) or 0)
            existing.latency_ms += float(item.get("latency_ms", 0.0) or 0.0)
            existing.llm_calls += int(item.get("llm_calls", 0) or 0)
            existing.cost_usd += float(item.get("cost_usd", 0.0) or 0.0)
    return report
