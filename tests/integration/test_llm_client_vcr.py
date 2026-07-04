"""llm_client VCR cassette test — 최초 1회 녹음 후 무료 재생.

⚠️ 사용자 게이트:
  - 본 파일의 cassette 녹음은 **실제 OpenAI 호출 1회** 발생
  - 비용: ~$0.001 (gpt-5.4-nano + 짧은 prompt)
  - 녹음 후엔 인터넷/key 없이도 재생 → 비용 0

설치:
  pip install -e ".[test-integration]"

최초 녹음:
  CS_ENABLE_LLM_RUNTIME=1 OPENAI_API_KEY=sk-... pytest tests/integration/test_llm_client_vcr.py --record-mode=once

재생 (default):
  pytest tests/integration/test_llm_client_vcr.py
  # → cassette 있으면 재생, 없으면 skip

녹음 갱신 (SDK 업데이트 등 시):
  rm tests/integration/cassettes/*.yaml
  pytest tests/integration/test_llm_client_vcr.py --record-mode=new_episodes
"""
from __future__ import annotations

import pytest

# pytest-recording이 없으면 모듈 전체 skip
pytest_recording = pytest.importorskip("pytest_recording")

pytestmark = pytest.mark.integration


try:
    from tests.integration.vcr_config import vcr_default_config
except ImportError:
    # 절대 경로 import fallback
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from tests.integration.vcr_config import vcr_default_config


class TestLLMClientVCR:
    """cassette 기반 재현 가능한 test — SDK contract 회귀 감지."""

    @pytest.mark.vcr(**vcr_default_config())
    def test_classifier_call_via_cassette(self, monkeypatch):
        """classifier role 호출 cassette 녹음 + 재생.

        최초 녹음 시:
          - 실제 OpenAI 호출 발생 (~$0.0005)
          - cassettes/test_classifier_call_via_cassette.yaml 생성
        이후 실행 시:
          - cassette 재생 — 0원
          - API key 없어도 통과
        """
        # cassette 매칭 위해 deterministic하지 않은 env 필요
        monkeypatch.setenv("CS_ENABLE_LLM_RUNTIME", "1")
        monkeypatch.delenv("CS_DETERMINISTIC_MODE", raising=False)
        # cassette 재생 모드에서도 SDK가 key를 요구하므로 fake 값 주입
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-cassette-replay")

        from compliance_sentinel.budget_guard import from_env as budget_guard_from_env
        from compliance_sentinel.agent_model_guard import ModelGuard
        from compliance_sentinel.llm_client import LLMClient

        client = LLMClient(
            budget_guard=budget_guard_from_env(),
            model_guard=ModelGuard.from_env(),
        )
        # deterministic은 has_any_provider_credentials()로 결정 — fake key로도 True
        # 실제 호출 시 cassette가 가로챔

        result = client.call(
            role="classifier",
            user_text="다음을 한 단어로 분류: 광고",
            model="gpt-5.4-nano",
            effort="low",
            max_tokens=20,
            estimated_cost_usd=0.001,
        )

        # contract: 응답 구조 검증
        assert result.model == "gpt-5.4-nano"
        assert result.role == "classifier"
        assert isinstance(result.text, str)
        # cassette 응답이라 text는 녹음 시점 응답 그대로
        # deterministic_fallback은 cassette 재생 시 False (실제 호출 흐름 재현)
