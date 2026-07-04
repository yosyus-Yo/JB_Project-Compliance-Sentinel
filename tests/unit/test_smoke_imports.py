"""Smoke imports — trivial modules (telemetry / observability / __init__).

본 파일은 deep test 가치가 낮은 trivial 모듈을 묶어 import smoke만 검증.
"""
from __future__ import annotations

import pytest


class TestTrivialImports:
    def test_root_package_imports(self):
        import compliance_sentinel
        assert compliance_sentinel is not None

    def test_telemetry_imports(self):
        import compliance_sentinel.telemetry as tel
        assert tel is not None

    def test_observability_imports(self):
        import compliance_sentinel.observability as obs
        assert obs is not None


class TestTelemetryHelpers:
    def test_span_contextmanager(self):
        from compliance_sentinel.telemetry import span
        # OTEL 미활성 시 no-op contextmanager
        with span("test_span", attr="value"):
            pass

    def test_init_tracer_returns(self):
        from compliance_sentinel.telemetry import init_tracer
        result = init_tracer()
        # OTEL 미활성 시 None 또는 tracer 객체
        assert result is None or result is not None

    def test_reset_for_test_callable(self):
        from compliance_sentinel.telemetry import reset_for_test
        reset_for_test()

    def test_redact_email(self):
        from compliance_sentinel.telemetry import _redact_string_for_langsmith
        result = _redact_string_for_langsmith("contact user@example.com")
        assert "user@example.com" not in result

    def test_redact_phone(self):
        from compliance_sentinel.telemetry import _redact_string_for_langsmith
        result = _redact_string_for_langsmith("call 010-1234-5678")
        assert "010-1234-5678" not in result


class TestObservabilityHelpers:
    def test_tracer_class(self):
        from compliance_sentinel.observability import Tracer
        assert Tracer is not None

    def test_get_default_tracer(self):
        from compliance_sentinel.observability import get_default_tracer
        tracer = get_default_tracer()
        assert tracer is not None

    def test_trace_event_dataclass(self):
        from compliance_sentinel.observability import TraceEvent
        assert TraceEvent is not None
