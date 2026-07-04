from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Language = Literal["ko", "en", "zh", "vi", "ja", "id", "unknown"]
Channel = Literal["banner", "app_push", "sns", "email", "landing_page", "notice", "unknown"]
ProductType = Literal["deposit", "loan", "card", "investment", "insurance", "unknown"]
ApprovalStatus = Literal["APPROVED", "APPROVE_WITH_CHANGES", "REJECTED", "HUMAN_REVIEW_REQUIRED"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


@dataclass
class MarketingFinding:
    id: str
    rule_id: str
    severity: Severity
    evidence: str
    issue: str
    rationale: str
    suggested_revision: str
    language: Language
    channel: Channel
    product_type: ProductType
    verifier_status: str = "PARTIAL"
    law_name: str = "금융광고 심의 기준"
    article_no: str = "CONTENT-RULE"
    citation_text: str = "콘텐츠는 소비자가 오인하지 않도록 중요 조건과 제한사항을 명확히 표시해야 합니다."
    source_text: str = ""
    applicability_reason: str = "대고객 금융 마케팅 콘텐츠의 표현 리스크에 적용됩니다."

    def to_report_dict(self) -> dict:
        data = asdict(self)
        data["content_issue_type"] = data.pop("rule_id")
        return data


@dataclass
class RevisionSuggestion:
    finding_id: str
    original: str
    revised: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MarketingReview:
    raw_content: str
    redacted_content: str
    language: Language
    channel: Channel
    content_type: str
    product_type: ProductType
    findings: list[MarketingFinding] = field(default_factory=list)
    revision_suggestions: list[RevisionSuggestion] = field(default_factory=list)
    approval_status: ApprovalStatus = "APPROVED"
    workflow_exports: dict = field(default_factory=dict)
    evaluation_metadata: dict = field(default_factory=dict)
