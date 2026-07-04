"""VCR cassette 공통 설정 — API key/secret 마스킹 필수.

사용:
  from tests.integration.vcr_config import vcr_default_config

  @pytest.mark.vcr(**vcr_default_config())
  def test_real_openai_call_recorded():
      # 최초 실행: 실제 OpenAI 호출 + cassette 녹음
      # 이후 실행: cassette 재생, 0원

설치 (사용자 게이트):
  pip install -e ".[test-integration]"

보안:
  - Authorization header 자동 마스킹 ([REDACTED])
  - 응답 body의 user data 검토 후 commit
  - cassettes/ 디렉토리는 tests/integration/cassettes/에 저장
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

CASSETTE_DIR = Path(__file__).parent / "cassettes"


def vcr_default_config() -> dict[str, Any]:
    """모든 VCR test의 default 설정.

    핵심 보안 정책:
      1. Authorization / api-key / x-api-key 헤더 마스킹
      2. once recording mode (실수 재녹음 방지)
      3. URL의 query string 보존 (cassette 매칭에 필요)
    """
    return {
        "cassette_library_dir": str(CASSETTE_DIR),
        "record_mode": "once",
        "filter_headers": [
            ("authorization", "Bearer [REDACTED]"),
            ("api-key", "[REDACTED]"),
            ("x-api-key", "[REDACTED]"),
            ("openai-organization", "[REDACTED]"),
            ("openai-project", "[REDACTED]"),
        ],
        "filter_post_data_parameters": [
            ("api_key", "[REDACTED]"),
            ("key", "[REDACTED]"),
        ],
        "match_on": ["method", "scheme", "host", "port", "path", "query", "body"],
        # response의 set-cookie 등 민감 헤더도 필요시 마스킹
        "decode_compressed_response": True,
    }


def mask_response_body(response: dict[str, Any]) -> dict[str, Any]:
    """응답 body에 PII/secret이 들어있을 가능성 — 후처리 hook (선택적).

    예: organization ID, project ID, x-request-id 등 마스킹.
    필요 시 vcr_default_config()["before_record_response"]에 등록.
    """
    if "headers" in response:
        for key in list(response["headers"]):
            if key.lower() in {"openai-organization", "openai-project", "x-request-id"}:
                response["headers"][key] = ["[REDACTED]"]
    return response
