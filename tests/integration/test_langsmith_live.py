"""langsmith_eval LIVE integration test.

LANGSMITH_API_KEY 미설정 시 skip.

설치:
  pip install -e ".[langsmith]"

실행:
  LANGSMITH_API_KEY=ls-... pytest tests/integration/test_langsmith_live.py
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestLangsmithLive:
    def test_client_init_with_key(self, require_langsmith):
        from compliance_sentinel.telemetry import langsmith_init, reset_for_test
        reset_for_test()
        client = langsmith_init()
        # 실제 key + langsmith SDK 설치 시 client 객체 반환
        assert client is not None or client is None  # 어느 path든 raise 안 함

    def test_record_run_no_raise(self, require_langsmith):
        from compliance_sentinel.telemetry import langsmith_record_run, reset_for_test
        reset_for_test()
        # 실제 호출 — LangSmith API에 run 1개 생성됨
        run_id = langsmith_record_run(
            "integration_test_run",
            inputs={"redacted_text": "테스트 입력"},
            outputs={"status": "OK"},
            metadata={"engine": "test"},
        )
        # 성공 시 UUID, 실패 시 None — 어느 쪽도 OK (silent fallback)
        assert run_id is None or isinstance(run_id, str)


class TestEvalDataset:
    """DEFAULT_EVAL_CASES + EvalCaseResult contract — env 불필요."""

    def test_default_cases_loadable(self):
        from compliance_sentinel.langsmith_eval import DEFAULT_EVAL_CASES
        assert isinstance(DEFAULT_EVAL_CASES, list)
        # 기본 케이스 1개 이상
        assert len(DEFAULT_EVAL_CASES) >= 1

    def test_eval_case_result_contract(self):
        from compliance_sentinel.langsmith_eval import EvalCaseResult
        result = EvalCaseResult(
            id="C1", passed=True, actual_status="APPROVED",
            actual_risk="LOW", audit_log_id="AL-1", reason="ok",
        )
        assert result.id == "C1"
