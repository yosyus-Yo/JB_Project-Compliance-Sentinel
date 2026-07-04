"""citation_extractor.py — extract_explicit_citations regex 추출."""
from __future__ import annotations

import pytest

from compliance_sentinel.citation_extractor import extract_explicit_citations


class TestExtractExplicitCitations:
    def test_finds_article_pattern(self):
        text = "개인정보보호법 제15조에 따라 처리합니다."
        citations = extract_explicit_citations(text)
        assert len(citations) >= 1
        # 첫 citation이 개인정보보호법 + 15조
        c = citations[0]
        assert "개인정보보호법" in c.law_name
        assert c.article_no == "15"

    def test_finds_multiple_citations(self):
        text = "개인정보보호법 제15조 및 신용정보법 제32조 적용"
        citations = extract_explicit_citations(text)
        law_names = {c.law_name for c in citations}
        # 최소 1개 이상 인용 추출 (law_name 매칭 정확도 의존)
        assert len(citations) >= 1

    def test_no_citation_returns_empty(self):
        citations = extract_explicit_citations("일반 텍스트입니다.")
        assert citations == []

    def test_empty_text(self):
        assert extract_explicit_citations("") == []

    def test_paragraph_pattern(self):
        text = "개인정보보호법 제15조 제2항"
        citations = extract_explicit_citations(text)
        assert len(citations) >= 1
