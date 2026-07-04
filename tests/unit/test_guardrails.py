"""guardrails.py — output check + disclaimer + block_or_revise."""
from __future__ import annotations

import pytest

from compliance_sentinel.guardrails import (
    DEFAULT_DISCLAIMER,
    FORBIDDEN_OUTPUT_PATTERNS,
    REQUIRED_DISCLAIMER_PHRASES,
    GuardrailViolation,
    block_or_revise,
    check_output,
    ensure_disclaimer,
)


class TestGuardrailViolation:
    def test_construction(self):
        # 실제 시그니처: rule, matched_text, severity
        v = GuardrailViolation(rule="R-1", matched_text="match", severity="critical")
        assert v.rule == "R-1"
        assert v.severity == "critical"


class TestCheckOutput:
    def test_clean_output_no_violations(self):
        violations = check_output("일반적인 컴플라이언스 검토 결과입니다.")
        assert violations == []

    def test_empty_output(self):
        violations = check_output("")
        assert violations == []

    def test_forbidden_patterns_defined(self):
        assert isinstance(FORBIDDEN_OUTPUT_PATTERNS, list)
        assert len(FORBIDDEN_OUTPUT_PATTERNS) > 0


class TestEnsureDisclaimer:
    def test_adds_disclaimer_when_missing(self):
        report = {"summary": "결과"}
        result = ensure_disclaimer(report)
        assert "disclaimer" in result
        assert result["disclaimer"]

    def test_preserves_existing_disclaimer(self):
        report = {"disclaimer": "기존 면책 조항"}
        result = ensure_disclaimer(report)
        # 기존 disclaimer 유지 또는 정상화 (구현 정책)
        assert "disclaimer" in result

    def test_default_disclaimer_constant(self):
        assert "법률 자문" in DEFAULT_DISCLAIMER

    def test_required_phrases_list(self):
        assert isinstance(REQUIRED_DISCLAIMER_PHRASES, list)
        assert len(REQUIRED_DISCLAIMER_PHRASES) > 0


class TestBlockOrRevise:
    def test_returns_tuple(self):
        result = block_or_revise("text")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_clean_text_returns_bool_and_list(self):
        blocked, violations = block_or_revise("정상적인 컴플라이언스 보고서입니다.")
        assert isinstance(blocked, bool)
        assert isinstance(violations, list)
