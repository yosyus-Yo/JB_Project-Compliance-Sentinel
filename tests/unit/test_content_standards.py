"""content_standards.py — load_marketing_standards + fallback."""
from __future__ import annotations

import pytest

from compliance_sentinel.content_standards import (
    _fallback_standards,
    load_marketing_standards,
)


class TestFallbackStandards:
    def test_returns_dict(self):
        result = _fallback_standards()
        assert isinstance(result, dict)

    def test_contains_rules(self):
        result = _fallback_standards()
        # 최소 1개 카테고리 + 패턴 보유
        assert len(result) > 0

    def test_high_severity_keywords_present(self):
        """원금 보장/무위험/확정 수익 등 핵심 위험 키워드 포함."""
        result = _fallback_standards()
        flat = str(result)
        # 최소 1개 핵심 위반 표현 포함
        assert any(k in flat for k in ["원금", "무위험", "확정", "guaranteed", "100%"])


class TestLoadMarketingStandards:
    def test_returns_dict(self):
        result = load_marketing_standards()
        assert isinstance(result, dict)

    def test_fallback_when_file_missing(self, monkeypatch):
        """STANDARDS_DIR 존재하지 않을 때 fallback dict 반환."""
        from compliance_sentinel import content_standards
        monkeypatch.setattr(content_standards, "STANDARDS_DIR",
                            content_standards.Path("/nonexistent/path"))
        result = load_marketing_standards()
        assert isinstance(result, dict)
        assert len(result) > 0  # fallback 활용됨
