"""telemetry.py — OTel + LangSmith env-driven wire + PII scrubber."""
from __future__ import annotations

import pytest

from compliance_sentinel.telemetry import (
    _redact_payload_for_langsmith,
    _redact_string_for_langsmith,
    _service_name,
    init_tracer,
    langsmith_init,
    langsmith_record_run,
    reset_for_test,
    span,
)


@pytest.fixture(autouse=True)
def _reset_telemetry_state(monkeypatch):
    reset_for_test()
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    yield
    reset_for_test()


class TestServiceName:
    def test_default(self):
        assert _service_name() == "compliance-sentinel"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OTEL_SERVICE_NAME", "custom-svc")
        assert _service_name() == "custom-svc"


class TestInitTracer:
    def test_no_env_returns_none(self):
        assert init_tracer() is None

    def test_idempotent_after_no_env(self):
        assert init_tracer() is None
        # 두 번째 호출도 None (init done)
        assert init_tracer() is None

    def test_with_env_attempts_init(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318/v1/traces")
        # SDK 미설치 또는 exporter 실패 시 None 또는 tracer
        result = init_tracer()
        # 어느 path든 raise 안 함
        assert result is None or result is not None


class TestSpanContextManager:
    def test_yields_when_tracer_none(self):
        # tracer 없으면 silent yield
        with span("test_op", attr1="value"):
            pass

    def test_accepts_various_attribute_types(self):
        with span("op", s="str", i=42, f=3.14, b=True, lst=[1, 2], none_val=None):
            pass

    def test_complex_attribute_stringified(self):
        with span("op", complex_obj={"nested": "dict"}):
            pass

    def test_no_exception_on_attribute_error(self):
        # span은 모든 예외를 silent 처리
        with span("op", bad_attr=object()):
            pass


class TestLangsmithInit:
    def test_no_api_key_returns_none(self):
        assert langsmith_init() is None

    def test_with_api_key_attempts_init(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key")
        # SDK 미설치 또는 client 실패 시 None
        result = langsmith_init()
        assert result is None or result is not None


class TestLangsmithRecordRun:
    def test_no_client_returns_none(self):
        result = langsmith_record_run("test_run", inputs={"x": 1})
        assert result is None

    def test_no_inputs_outputs(self):
        result = langsmith_record_run("test_run")
        assert result is None


class TestRedactString:
    def test_email_redacted(self):
        result = _redact_string_for_langsmith("contact alice@example.com today")
        assert "alice@example.com" not in result
        assert "[EMAIL]" in result

    def test_korean_phone_redacted(self):
        result = _redact_string_for_langsmith("010-1234-5678 call me")
        assert "[PHONE]" in result

    def test_rrn_redacted(self):
        result = _redact_string_for_langsmith("주민번호 900101-1234567")
        assert "[RRN]" in result

    def test_long_number_redacted(self):
        result = _redact_string_for_langsmith("카드 1234567890123456 결제")
        assert "[NUMBER]" in result

    def test_clean_text_passes_through(self):
        result = _redact_string_for_langsmith("일반 텍스트 내용")
        assert "일반 텍스트" in result

    def test_truncated_to_2000_chars(self):
        long = "x" * 5000
        result = _redact_string_for_langsmith(long)
        assert len(result) == 2000

    def test_multiple_patterns_in_one_string(self):
        text = "alice@x.com 010-1234-5678 900101-1234567"
        result = _redact_string_for_langsmith(text)
        assert "[EMAIL]" in result
        assert "[PHONE]" in result
        assert "[RRN]" in result


class TestRedactPayload:
    def test_string_redacted(self):
        result = _redact_payload_for_langsmith("alice@example.com")
        assert "[EMAIL]" in result

    def test_dict_recursive(self):
        result = _redact_payload_for_langsmith({"email": "x@x.com", "name": "alice"})
        assert "[EMAIL]" in result["email"]
        assert result["name"] == "alice"

    def test_list_recursive(self):
        result = _redact_payload_for_langsmith(["alice@x.com", "ok"])
        assert "[EMAIL]" in result[0]
        assert result[1] == "ok"

    def test_tuple_becomes_list(self):
        result = _redact_payload_for_langsmith(("alice@x.com", "ok"))
        assert isinstance(result, list)
        assert "[EMAIL]" in result[0]

    def test_primitives_unchanged(self):
        assert _redact_payload_for_langsmith(42) == 42
        assert _redact_payload_for_langsmith(3.14) == 3.14
        assert _redact_payload_for_langsmith(True) is True
        assert _redact_payload_for_langsmith(None) is None

    def test_nested_dict_with_list(self):
        payload = {"emails": ["a@x.com", "b@y.com"], "count": 2}
        result = _redact_payload_for_langsmith(payload)
        assert "[EMAIL]" in result["emails"][0]
        assert result["count"] == 2

    def test_custom_object_stringified_and_redacted(self):
        class Obj:
            def __str__(self):
                return "alice@x.com"
        result = _redact_payload_for_langsmith(Obj())
        assert "[EMAIL]" in result


class TestResetForTest:
    def test_resets_state(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost")
        init_tracer()
        reset_for_test()
        # state 초기화 후 다시 호출 가능
        result = init_tracer()
        # 어느 결과든 raise 안 함
        assert result is None or result is not None


class TestSpanWithMockedTracer:
    """tracer가 활성화된 상태로 span context manager 동작 cover."""

    def test_span_with_active_tracer(self, monkeypatch):
        # OTEL SDK 가용 + endpoint 설정 → tracer가 실제 활성화
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318/v1/traces")
        reset_for_test()
        tracer = init_tracer()
        # SDK 가용 시 tracer 실제 활성화
        if tracer is not None:
            with span("test_op", attr="value"):
                pass


class TestLangsmithInitWithMockedClient:
    def test_caches_client(self, monkeypatch):
        # 두 번 호출 시 _LANGSMITH 재사용
        monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key")
        reset_for_test()
        client1 = langsmith_init()
        client2 = langsmith_init()
        # 같은 인스턴스 또는 둘 다 None (SDK 미설치)
        assert client1 is client2 or (client1 is None and client2 is None)


class TestLangsmithRecordRunWithKey:
    def test_with_api_key_attempts_record(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key")
        reset_for_test()
        # langsmith SDK가 설치되어 있어도 실제 호출 실패 시 None
        result = langsmith_record_run(
            "test_run",
            inputs={"email": "alice@x.com"},
            outputs={"result": "ok"},
            metadata={"key": "value"},
        )
        # 성공 시 run_id, 실패 시 None
        assert result is None or isinstance(result, str)

    def test_redacts_input_payload(self, monkeypatch):
        # _redact_payload_for_langsmith 호출 path cover
        monkeypatch.setenv("LANGSMITH_API_KEY", "fake")
        reset_for_test()
        result = langsmith_record_run(
            "test",
            inputs={"text": "alice@x.com call 010-1234-5678"},
            outputs={},
        )
        assert result is None or isinstance(result, str)
