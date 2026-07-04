"""Integration test 공통 fixture + skip 정책.

원칙:
  - 외부 의존성(OpenAI/Anthropic/Qdrant/LangSmith) **존재할 때만 실행**
  - 환경변수 없으면 자동 skip — CI default = skip
  - LIVE 호출 시 비용 발생 가능 → 명시적 환경변수 게이트

실행 방법:
  # unit만 (default)
  pytest -m unit

  # integration만 (OPENAI_API_KEY 등 설정 후)
  CS_ENABLE_LLM_RUNTIME=1 OPENAI_API_KEY=sk-... pytest -m integration

  # 전체 (env 설정된 path만 실제 실행, 나머지는 skip)
  pytest -m "unit or integration"
"""
from __future__ import annotations

import os

import pytest


def _has_openai_key() -> bool:
    """OPENAI_API_KEY 또는 호환 provider key 존재 여부."""
    return any(
        os.environ.get(name)
        for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENROUTER_API_KEY",
                     "GROQ_API_KEY", "TOGETHER_API_KEY", "DEEPSEEK_API_KEY")
    )


def _has_anthropic_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _has_google_key() -> bool:
    return bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))


def _has_qdrant() -> bool:
    return bool(os.environ.get("QDRANT_URL"))


def _has_langsmith() -> bool:
    return bool(os.environ.get("LANGSMITH_API_KEY"))


def _llm_runtime_enabled() -> bool:
    """CS_ENABLE_LLM_RUNTIME=1 명시 시에만 실제 호출 허용 (안전 게이트)."""
    return os.environ.get("CS_ENABLE_LLM_RUNTIME") == "1"


@pytest.fixture
def require_openai():
    """OPENAI_API_KEY 또는 호환 provider key 필수."""
    if not _has_openai_key():
        pytest.skip("OPENAI_API_KEY (또는 호환 provider key) 미설정 — integration skip")
    if not _llm_runtime_enabled():
        pytest.skip("CS_ENABLE_LLM_RUNTIME=1 미설정 — LIVE 호출 안전 게이트")
    yield


@pytest.fixture
def require_anthropic():
    if not _has_anthropic_key():
        pytest.skip("ANTHROPIC_API_KEY 미설정")
    if not _llm_runtime_enabled():
        pytest.skip("CS_ENABLE_LLM_RUNTIME=1 미설정")
    yield


@pytest.fixture
def require_qdrant():
    if not _has_qdrant():
        pytest.skip("QDRANT_URL 미설정")
    yield


@pytest.fixture
def require_langsmith():
    if not _has_langsmith():
        pytest.skip("LANGSMITH_API_KEY 미설정")
    yield


@pytest.fixture
def live_llm_env(monkeypatch):
    """integration test에서 LIVE 호출 활성화 토글.

    require_* fixture를 먼저 통과해야 의미 있음.
    deterministic mode 강제 OFF + LLM runtime 활성.
    """
    monkeypatch.setenv("CS_ENABLE_LLM_RUNTIME", "1")
    monkeypatch.delenv("CS_DETERMINISTIC_MODE", raising=False)
    yield
