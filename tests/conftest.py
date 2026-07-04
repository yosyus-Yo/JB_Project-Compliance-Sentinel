"""공통 pytest fixture — 13 모듈 unit test 전역 공유.

원칙:
  - 외부 의존성 0건 (Qdrant/OpenAI 미사용)
  - LLM 호출 없음 (CS_ENABLE_LLM_RUNTIME 미설정 → deterministic mode)
  - 빠른 실행 (전체 unit suite < 5초 목표)
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# LLM/외부 호출 비활성화 — 모든 unit test 진입 직전 강제
os.environ.setdefault("CS_ENABLE_LLM_RUNTIME", "0")
os.environ.setdefault("CS_DISABLE_QDRANT", "1")

from compliance_sentinel.models import (
    AtomicClaim,
    BoardOpinion,
    Citation,
    ComplianceState,
    Finding,
    LawArticle,
    PIIFinding,
)


@pytest.fixture
def sample_law_article() -> LawArticle:
    """KB 검증용 가짜 법령 조항 (verifier/board fixture 공통)."""
    return LawArticle(
        law_name="개인정보보호법",
        article_no="15",
        title="개인정보의 수집·이용",
        text="개인정보처리자는 다음 각 호의 어느 하나에 해당하는 경우에는 개인정보를 수집할 수 있다.",
        effective_date="2020-08-05",
        source_url="https://www.law.go.kr/lsInfoP.do?lsiSeq=000001",
        keywords=["개인정보", "수집", "이용", "동의"],
    )


@pytest.fixture
def sample_citation(sample_law_article) -> Citation:
    return Citation(
        law_name=sample_law_article.law_name,
        article_no=sample_law_article.article_no,
        citation_text=sample_law_article.text,
        source_url=sample_law_article.source_url,
    )


@pytest.fixture
def sample_finding(sample_citation) -> Finding:
    return Finding(
        id="F-001",
        source_text="개인정보를 수집하여 마케팅에 활용합니다.",
        issue="개인정보 수집·이용 동의 누락 가능성",
        law_name=sample_citation.law_name,
        article_no=sample_citation.article_no,
        citation_text=sample_citation.citation_text,
        applicability_reason="고객 개인정보 직접 언급 → 적용",
        suggested_revision="수집 항목, 보유 기간, 동의 방법을 명확히 고지하세요.",
    )


@pytest.fixture
def sample_pii_finding() -> PIIFinding:
    return PIIFinding(
        kind="rrn",
        value="900101-1234567",
        start=10,
        end=24,
        replacement="[RRN_REDACTED_1]",
    )


@pytest.fixture
def sample_board_opinion(sample_citation) -> BoardOpinion:
    return BoardOpinion(
        agent_id="legal-counsel",
        stance="법령·약관 구조 검토",
        risk_level="MEDIUM",
        rationale="약관 명시성 검토 필요.",
        citations=[sample_citation],
    )


@pytest.fixture
def sample_state() -> ComplianceState:
    return ComplianceState(
        input_text="테스트 입력",
        redacted_text="테스트 입력",
        input_type="advertisement",
    )


@pytest.fixture
def tmp_audit_dir(tmp_path: Path) -> Path:
    """임시 audit log 디렉토리 (테스트 격리)."""
    audit_dir = tmp_path / "audit_logs"
    audit_dir.mkdir(parents=True, exist_ok=True)
    return audit_dir


@pytest.fixture
def tmp_audit_path(tmp_audit_dir: Path) -> Path:
    return tmp_audit_dir / "compliance_audit.jsonl"


@pytest.fixture
def deterministic_env(monkeypatch):
    """LLM/외부 의존성 차단 환경 강제 (개별 test에서 명시 사용 가능)."""
    monkeypatch.setenv("CS_ENABLE_LLM_RUNTIME", "0")
    monkeypatch.setenv("CS_DISABLE_QDRANT", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    yield


@pytest.fixture
def llm_runtime_enabled(monkeypatch):
    """LLM runtime 활성화 fixture (mock 호출 테스트용 — 실제 OpenAI 호출 X)."""
    monkeypatch.setenv("CS_ENABLE_LLM_RUNTIME", "1")
    monkeypatch.setenv("CS_MODEL_CRITIC", "gpt-5.5")
    yield
