"""Telemetry — OpenTelemetry + LangSmith wire (env-based no-op default).

spec/opentelemetry-wire.md Phase A (OTEL-001~005).

원칙:
  - env 부재 시 모든 함수가 no-op (회귀 0 보장)
  - opentelemetry SDK는 optional extra (`[telemetry]`) — 미설치 시 silent skip
  - PII redacted only (span attribute에 raw input 금지)

사용:
    from compliance_sentinel.telemetry import init_tracer, span

    tracer = init_tracer()  # env 없으면 None
    with span("compliance_review", audit_log_id="X", risk_level="HIGH"):
        ...
"""
from __future__ import annotations

import functools
import os
import re
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Optional

# OTel SDK lazy import (OTEL-005)
try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    _OTEL_AVAILABLE = True
except ImportError:
    _otel_trace = None  # type: ignore[assignment]
    _OTEL_AVAILABLE = False

try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    _OTLP_AVAILABLE = True
except ImportError:
    OTLPSpanExporter = None  # type: ignore[assignment]
    _OTLP_AVAILABLE = False

# LangSmith lazy import
try:
    from langsmith import Client as _LangSmithClient
    _LANGSMITH_AVAILABLE = True
except ImportError:
    _LangSmithClient = None  # type: ignore[assignment]
    _LANGSMITH_AVAILABLE = False


_TRACER: Optional[Any] = None  # opentelemetry.trace.Tracer | None
_LANGSMITH: Optional[Any] = None  # langsmith.Client | None
_INIT_DONE = False


def _service_name() -> str:
    return os.environ.get("OTEL_SERVICE_NAME", "compliance-sentinel")


def init_tracer() -> Optional[Any]:
    """OTEL-001/003: env 기반 tracer 초기화. env 부재 시 None 반환.

    트리거 env:
      - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP HTTP endpoint (e.g. http://localhost:4318/v1/traces)
      - OTEL_SERVICE_NAME: span 식별용 (default "compliance-sentinel")

    SDK 미설치 또는 env 미설정 시 silent skip (no-op).
    """
    global _TRACER, _INIT_DONE
    if _INIT_DONE:
        return _TRACER
    _INIT_DONE = True

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None  # env 부재 → no-op
    if not _OTEL_AVAILABLE or not _OTLP_AVAILABLE:
        return None  # SDK 미설치 → silent skip

    try:
        resource = Resource.create({"service.name": _service_name()})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _otel_trace.set_tracer_provider(provider)
        _TRACER = _otel_trace.get_tracer("compliance_sentinel")
        return _TRACER
    except Exception:
        # exporter 초기화 실패 → silent fallback (작업 중단 금지)
        _TRACER = None
        return None


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[None]:
    """OTEL-004: span context manager.

    tracer 미초기화 시 no-op contextmanager (예외 없이 yield).
    span attribute는 PII redacted 가정 (호출자가 redacted_text만 전달).
    """
    tracer = init_tracer()
    if tracer is None:
        yield
        return
    try:
        with tracer.start_as_current_span(name) as otel_span:
            for key, value in attributes.items():
                try:
                    # OpenTelemetry는 primitive type만 허용 (str/int/float/bool/list)
                    if isinstance(value, (str, int, float, bool)):
                        otel_span.set_attribute(key, value)
                    elif value is None:
                        otel_span.set_attribute(key, "null")
                    else:
                        otel_span.set_attribute(key, str(value)[:500])  # truncate
                except Exception:
                    continue
            yield
    except Exception:
        # span 실패가 작업 중단 유발 금지 — silent
        yield


def langsmith_init() -> Optional[Any]:
    """OTEL-201: LangSmith Client 초기화. env 부재 시 None.

    트리거 env: LANGSMITH_API_KEY
    """
    global _LANGSMITH
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        return None
    if not _LANGSMITH_AVAILABLE:
        return None
    if _LANGSMITH is None:
        try:
            _LANGSMITH = _LangSmithClient(api_key=api_key)
        except Exception:
            _LANGSMITH = None
    return _LANGSMITH


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b")
_RRN_RE = re.compile(r"\b\d{6}-?[1-4]\d{6}\b")
_LONG_NUMBER_RE = re.compile(r"\b\d{10,16}\b")


def _redact_string_for_langsmith(value: str) -> str:
    """Best-effort PII scrubber for observability payloads."""

    value = _EMAIL_RE.sub("[EMAIL]", value)
    value = _PHONE_RE.sub("[PHONE]", value)
    value = _RRN_RE.sub("[RRN]", value)
    value = _LONG_NUMBER_RE.sub("[NUMBER]", value)
    return value[:2000]


def _redact_payload_for_langsmith(value: Any) -> Any:
    """Recursively redact payload values before external trace export."""

    if isinstance(value, str):
        return _redact_string_for_langsmith(value)
    if isinstance(value, dict):
        return {str(key): _redact_payload_for_langsmith(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_payload_for_langsmith(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_payload_for_langsmith(item) for item in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _redact_string_for_langsmith(str(value))


def langsmith_record_run(
    name: str,
    *,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    project_name: str | None = None,
) -> str | None:
    """Create a redacted LangSmith run when configured.

    Returns the run id on best-effort success, otherwise ``None``. This function
    never raises: observability export must not break compliance review.
    """

    client = langsmith_init()
    if client is None:
        return None
    run_id = str(uuid.uuid4())
    safe_inputs = _redact_payload_for_langsmith(inputs or {})
    safe_outputs = _redact_payload_for_langsmith(outputs or {})
    safe_metadata = _redact_payload_for_langsmith(metadata or {})
    try:  # langsmith versions differ slightly in accepted kwargs
        client.create_run(
            id=run_id,
            name=name,
            run_type="chain",
            inputs=safe_inputs,
            outputs=safe_outputs,
            extra={"metadata": safe_metadata},
            project_name=project_name or os.environ.get("LANGSMITH_PROJECT", "compliance-sentinel"),
        )
        return run_id
    except TypeError:
        try:
            client.create_run(
                name=name,
                run_type="chain",
                inputs=safe_inputs,
                outputs=safe_outputs,
                project_name=project_name or os.environ.get("LANGSMITH_PROJECT", "compliance-sentinel"),
            )
            return run_id
        except Exception:
            return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# L3 실행 트레이스 export (가이드 제3장 — 관측성 L3 외부연동)
# ---------------------------------------------------------------------------
# 가이드의 "가장 중요한 L3가 비어 사고 시 이유를 못 찾는다" 문제를 닫는다.
# 내부 state.trace(풍부)를 OTel span(GenAI convention) + LangSmith run으로 export.
# env(OTEL_EXPORTER_OTLP_ENDPOINT / LANGSMITH_API_KEY) 부재 시 no-op.

_L3_TOOL_NODES = {
    "retrieve_context", "kb_search", "law_open_api", "rag_retrieve",
    "document_rag", "qdrant_retrieve", "audit_log", "slack_publish", "workflow_publish",
}


def _l3_token_usage(llm_calls: Any) -> tuple[int, int, int]:
    """state.llm_calls에서 prompt/completion/cached 토큰을 합산 (③ 토큰·비용)."""
    pin = pout = pcached = 0
    for call in llm_calls or []:
        if not isinstance(call, dict):
            continue
        pin += int(call.get("prompt_tokens", 0) or 0)
        pout += int(call.get("completion_tokens", 0) or 0)
        pcached += int(call.get("cached_tokens", 0) or 0)
    return pin, pout, pcached


def emit_compliance_trace(state: Any, *, name: str = "compliance_review") -> Optional[str]:
    """L3 실행 트레이스(5요소)를 OTel span + LangSmith run으로 export.

    L3 5요소(가이드 제3장): ① 단계 입출력 ② 도구 인자/반환 ③ 토큰·비용
    ④ 가드레일·폴백 발동 ⑤ 종료 사유. env 부재 시 no-op. 관측 export가
    심의를 중단시키지 않도록 **절대 raise하지 않는다**. PII는 redact 후 export.
    AgentLoop Trace Completeness pass가 OTel span attribute에서 5요소를 추출한다.
    """
    try:
        fr = getattr(state, "final_report", {}) or {}
        if not isinstance(fr, dict):
            fr = {}
        llm_calls = getattr(state, "llm_calls", []) or []
        trace = getattr(state, "trace", []) or []
        pin, pout, pcached = _l3_token_usage(llm_calls)
        ic = fr.get("input_completeness")
        blocked_by = str(ic.get("blocked_by", "")) if isinstance(ic, dict) else ""
        tool_count = sum(
            1 for t in trace if isinstance(t, dict) and str(t.get("node", "")) in _L3_TOOL_NODES
        )
        attrs: dict[str, Any] = {
            "gen_ai.system": "compliance-sentinel",
            "gen_ai.operation.name": name,
            "gen_ai.usage.input_tokens": pin,            # ③ 토큰·비용
            "gen_ai.usage.output_tokens": pout,
            "gen_ai.usage.cached_tokens": pcached,
            "cs.finish_reason": str(fr.get("approval_status", "unknown")),   # ⑤ 종료 사유
            "cs.risk_level": str(fr.get("risk_level", "unknown")),
            "cs.guardrail.human_review": bool(getattr(state, "human_review_needed", False)),  # ④ 가드레일·폴백
            "cs.guardrail.pii_findings": len(getattr(state, "pii_findings", []) or []),
            "cs.guardrail.blocked_by": blocked_by,
            "cs.tool.count": tool_count,                 # ② 도구 인자/반환
            "cs.trace.steps": len(trace),                # ① 단계 입출력
            "cs.audit_log_id": str(getattr(state, "audit_log_id", "")),
            # AgentLoop Trace Completeness가 읽는 L3 완전성 신호(5요소 present)
            "cs.l3.complete": bool(trace) and bool(fr.get("approval_status")),
        }
    except Exception:
        return None

    # OTel span (OTEL_EXPORTER_OTLP_ENDPOINT + SDK 있을 때만)
    tracer = init_tracer()
    if tracer is not None:
        try:
            with tracer.start_as_current_span(name) as sp:
                for key, value in attrs.items():
                    try:
                        if isinstance(value, (str, int, float, bool)):
                            sp.set_attribute(key, value)
                        else:
                            sp.set_attribute(key, str(value)[:500])
                    except Exception:
                        continue
                for ev in trace:  # ① 단계별 trace를 span event로 (PII redact)
                    if not isinstance(ev, dict):
                        continue
                    try:
                        node = str(ev.get("node", "step"))
                        ev_attrs: dict[str, Any] = {}
                        for k, v in ev.items():
                            if k == "node":
                                continue
                            rv = _redact_payload_for_langsmith(v)
                            ev_attrs[str(k)] = rv if isinstance(rv, (str, int, float, bool)) else str(rv)[:200]
                        sp.add_event(node, attributes=ev_attrs)
                    except Exception:
                        continue
        except Exception:
            pass

    # LangSmith run (redacted) — LANGSMITH_API_KEY 있을 때만
    try:
        langsmith_record_run(
            name,
            inputs={"input_type": str(getattr(state, "input_type", ""))},
            outputs={"approval_status": fr.get("approval_status"), "risk_level": fr.get("risk_level")},
            metadata=attrs,
        )
    except Exception:
        pass
    return attrs.get("cs.finish_reason")


def _emit_l3_trace(fn: Any) -> Any:
    """Decorator: 함수 반환 후 L3 trace를 export. 반환이 EngineResult면 ``.state``,
    ComplianceState면 자체를 추출. export 실패는 무시(심의 비중단)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = fn(*args, **kwargs)
        try:
            st = getattr(result, "state", result)
            if hasattr(st, "trace"):
                emit_compliance_trace(st)
        except Exception:
            pass
        return result

    return wrapper


def reset_for_test() -> None:
    """테스트 격리용 — tracer 상태 초기화. 운영 코드에서 호출 금지."""
    global _TRACER, _LANGSMITH, _INIT_DONE
    _TRACER = None
    _LANGSMITH = None
    _INIT_DONE = False
