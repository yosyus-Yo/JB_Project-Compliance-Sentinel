"""skill_injection.py — skill context loader (file 의존)."""
from __future__ import annotations

import pytest

from compliance_sentinel.skill_injection import (
    clear_skill_cache,
    load_injected_skill_context,
    skill_injection_status,
)


class TestSkillInjectionStatus:
    def test_returns_dict(self):
        status = skill_injection_status()
        assert isinstance(status, dict)

    def test_role_specific(self):
        status = skill_injection_status(role="legal_counsel")
        assert isinstance(status, dict)


class TestLoadInjectedSkillContext:
    def test_returns_string(self):
        result = load_injected_skill_context("legal_counsel")
        assert isinstance(result, str)

    def test_no_skill_returns_empty_or_default(self):
        # 존재하지 않는 role
        result = load_injected_skill_context("nonexistent_role_xyz")
        assert isinstance(result, str)


class TestClearSkillCache:
    def test_callable(self):
        # side-effect only
        clear_skill_cache()
