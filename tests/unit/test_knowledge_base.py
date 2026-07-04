"""knowledge_base.py — normalize/tokenize + LawKnowledgeBase."""
from __future__ import annotations

import pytest

from compliance_sentinel.knowledge_base import (
    LawKnowledgeBase,
    normalize,
    normalize_article_no,
    tokenize,
)


class TestNormalize:
    def test_removes_whitespace(self):
        assert normalize("개인 정보 보호 법") == "개인정보보호법"

    def test_empty(self):
        assert normalize("") == ""


class TestNormalizeArticleNo:
    def test_extracts_digits(self):
        assert normalize_article_no("제15조") == "15"

    def test_pure_digits(self):
        assert normalize_article_no("15") == "15"

    def test_empty(self):
        assert normalize_article_no("") == ""


class TestTokenize:
    def test_returns_set(self):
        result = tokenize("개인정보 보호")
        assert isinstance(result, set)

    def test_nonempty_input(self):
        result = tokenize("개인정보 처리")
        assert len(result) > 0


class TestLawKnowledgeBase:
    def test_from_json_loads(self):
        try:
            kb = LawKnowledgeBase.from_json()
            assert kb is not None
        except FileNotFoundError:
            pytest.skip("laws.json not available")
