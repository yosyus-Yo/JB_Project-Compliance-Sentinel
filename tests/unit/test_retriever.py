"""retriever.py — keyword expansions + retrieve_context."""
from __future__ import annotations

import pytest

from compliance_sentinel.retriever import KEYWORD_EXPANSIONS, retrieve_context


class TestKeywordExpansions:
    def test_dict_structure(self):
        assert isinstance(KEYWORD_EXPANSIONS, dict)
        assert len(KEYWORD_EXPANSIONS) > 0

    def test_values_are_lists(self):
        for key, value in KEYWORD_EXPANSIONS.items():
            assert isinstance(value, (list, set, tuple)), f"{key} expansion not iterable"


class TestRetrieveContext:
    def test_returns_list(self):
        try:
            from compliance_sentinel.knowledge_base import LawKnowledgeBase
            kb = LawKnowledgeBase.from_json()
            result = retrieve_context("개인정보 처리", kb, limit=5)
            assert isinstance(result, list)
            assert len(result) <= 5
        except FileNotFoundError:
            pytest.skip("laws.json not available")

    def test_empty_text(self):
        try:
            from compliance_sentinel.knowledge_base import LawKnowledgeBase
            kb = LawKnowledgeBase.from_json()
            result = retrieve_context("", kb, limit=5)
            assert isinstance(result, list)
        except FileNotFoundError:
            pytest.skip("laws.json not available")
