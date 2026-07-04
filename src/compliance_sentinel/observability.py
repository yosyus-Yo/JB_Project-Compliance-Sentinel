"""Observability — LangSmith / Phoenix trace export wrapper.

Offline-first 원칙:
  - LANGSMITH_API_KEY 또는 PHOENIX_ENDPOINT 환경변수 존재 시 외부 trace export 활성
  - 부재 시 audit_logs/trace.jsonl 로컬 trace만 (silent fallback)

용도:
  - 각 LLM 호출, board member 의견, verifier 결과, revise loop 등 모든 의사결정 trace
  - layer별 fire 측정 → ablation-report에서 8-layer 활성 비율 추적

설계:
  - 함수형 wrapper: trace_event(node, data) 단일 entry
  - 외부 SDK 부재 시 LangSmith/Phoenix 경로는 silent skip
  - 본 turn은 인프라 wiring만 — workflow.py 통합은 P5+ option
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_TRACE_LOG = PROJECT_ROOT / "audit_logs" / "trace.jsonl"

# LangSmith optional
try:  # pragma: no cover
    from langsmith import Client as _LangSmithClient  # type: ignore
    _HAS_LANGSMITH = True
except Exception:  # pragma: no cover
    _HAS_LANGSMITH = False


@dataclass
class TraceEvent:
    trace_id: str
    timestamp: str
    node: str  # classify_input | pii_guard | retrieve_context | board_review | synthesize | verify | revise | report | audit
    data: dict = field(default_factory=dict)
    duration_ms: Optional[float] = None
    layer: Optional[str] = None  # L1-L8 보안 layer 매핑

    def to_dict(self) -> dict:
        return asdict(self)


class Tracer:
    """Single-session tracer. ComplianceSentinel.analyze() 호출당 1개 instance.

    외부 export:
      - LangSmith 활성 시: 매 trace_event() → LangSmith Run 생성
      - Phoenix 활성 시: OTLP endpoint로 export (P5+)
      - 둘 다 부재: 로컬 jsonl만
    """

    def __init__(self, *, session_id: Optional[str] = None, langsmith_project: str = "compliance-sentinel") -> None:
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.events: list[TraceEvent] = []
        self.langsmith_project = langsmith_project
        self._langsmith: Optional[Any] = None
        if _HAS_LANGSMITH and os.environ.get("LANGSMITH_API_KEY"):
            try:  # pragma: no cover
                self._langsmith = _LangSmithClient()
            except Exception:
                self._langsmith = None

    @property
    def langsmith_enabled(self) -> bool:
        return self._langsmith is not None

    @property
    def phoenix_enabled(self) -> bool:
        # P5+ — OTLP exporter wiring
        return bool(os.environ.get("PHOENIX_ENDPOINT"))

    def trace(self, node: str, *, layer: Optional[str] = None, **data: Any) -> TraceEvent:
        """단일 trace 이벤트 기록.

        Args:
            node: workflow node name
            layer: 8-layer 매핑 (L1-L8). None이면 미분류.
            data: 임의 metadata
        """
        event = TraceEvent(
            trace_id=f"{self.session_id}-{len(self.events) + 1:03d}",
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            node=node,
            data=data,
            layer=layer,
        )
        self.events.append(event)

        # 로컬 jsonl append (항상)
        LOCAL_TRACE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOCAL_TRACE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

        # LangSmith export (활성 시)
        if self._langsmith is not None:  # pragma: no cover
            try:
                self._langsmith.create_run(
                    name=node,
                    run_type="chain",
                    inputs={"layer": layer, **{k: v for k, v in data.items() if not callable(v)}},
                    project_name=self.langsmith_project,
                )
            except Exception:
                pass  # silent fail — 로컬은 이미 기록

        return event

    def summary(self) -> dict:
        layer_counts: dict[str, int] = {}
        for ev in self.events:
            if ev.layer:
                layer_counts[ev.layer] = layer_counts.get(ev.layer, 0) + 1
        return {
            "session_id": self.session_id,
            "total_events": len(self.events),
            "layer_fires": layer_counts,
            "langsmith_enabled": self.langsmith_enabled,
            "phoenix_enabled": self.phoenix_enabled,
            "local_trace": str(LOCAL_TRACE_LOG),
        }


def get_default_tracer() -> Tracer:
    """편의: 모듈 단일 tracer (전체 세션 공유)."""
    global _default_tracer
    try:
        return _default_tracer  # type: ignore
    except NameError:
        _default_tracer = Tracer()
        return _default_tracer
