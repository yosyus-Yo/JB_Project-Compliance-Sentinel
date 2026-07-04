"""marketing_models.py — 3 dataclass."""
from __future__ import annotations

import pytest

from compliance_sentinel.marketing_models import (
    MarketingFinding,
    MarketingReview,
    RevisionSuggestion,
)


class TestMarketingFinding:
    def test_construction_with_defaults(self):
        f = MarketingFinding(
            id="F-1", rule_id="R-1", severity="HIGH",
            evidence="text", issue="issue", rationale="reason",
            suggested_revision="fix", language="ko",
            channel="banner", product_type="installment_savings",
        )
        assert f.verifier_status == "PARTIAL"
        assert f.law_name == "금융광고 심의 기준"
        assert f.article_no == "CONTENT-RULE"
        assert f.applicability_reason  # 기본 문구 존재

    def test_override_law_name(self):
        f = MarketingFinding(
            id="F-1", rule_id="R-1", severity="HIGH",
            evidence="e", issue="i", rationale="r", suggested_revision="s",
            language="ko", channel="banner", product_type="loan",
            law_name="신용정보법",
        )
        assert f.law_name == "신용정보법"


class TestRevisionSuggestion:
    def test_construction(self):
        r = RevisionSuggestion(
            finding_id="F-1", original="원본", revised="수정",
            reason="이유",
        )
        assert r.finding_id == "F-1"
        assert r.revised == "수정"


class TestMarketingReview:
    def test_default_fields(self):
        review = MarketingReview(
            raw_content="x",
            redacted_content="x",
            language="ko",
            channel="banner",
            content_type="advertisement",
            product_type="installment_savings",
        )
        assert review.findings == []
