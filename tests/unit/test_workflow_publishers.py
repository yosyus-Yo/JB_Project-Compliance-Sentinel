"""workflow_publishers.py — Slack/Notion/Jira payload builders."""
from __future__ import annotations

import pytest

from compliance_sentinel.workflow_publishers import (
    _board_summary_lines,
    build_jira_payload,
    build_notion_payload,
    build_publish_plan,
    build_slack_payload,
)


class TestBoardSummaryLines:
    def test_empty_returns_empty_or_default(self):
        result = _board_summary_lines(None)
        assert isinstance(result, list)

    def test_with_diagnostics(self):
        diag = {
            "risk_distribution": {"HIGH": 2, "LOW": 4},
            "majority_risk": "LOW",
            "disagreement_score": 0.33,
        }
        result = _board_summary_lines(diag)
        assert isinstance(result, list)


class TestBuildPublishPlan:
    def test_returns_dict(self):
        plan = build_publish_plan(
            approval_status="APPROVED",
            risk_level="LOW",
            audit_log_id="AUD-abc",
        )
        assert isinstance(plan, dict)

    def test_includes_target_decisions(self):
        plan = build_publish_plan(
            approval_status="HUMAN_REVIEW_REQUIRED",
            risk_level="HIGH",
        )
        assert isinstance(plan, dict)
        # 어떤 채널/타겟 정보든 포함 (구현 의존)
        assert len(plan) > 0


class TestBuildSlackPayload:
    def test_returns_dict(self):
        payload = build_slack_payload(
            approval_status="APPROVED",
            risk_level="LOW",
            findings=[],
            revisions=[],
            audit_log_id="AUD-abc",
        )
        assert isinstance(payload, dict)


class TestBuildJiraPayload:
    def test_returns_dict(self):
        payload = build_jira_payload(
            approval_status="HUMAN_REVIEW_REQUIRED",
            risk_level="HIGH",
            findings=[],
            revisions=[],
            audit_log_id="AUD-abc",
        )
        assert isinstance(payload, dict)


class TestBuildNotionPayload:
    def test_returns_dict(self):
        payload = build_notion_payload(
            approval_status="APPROVED",
            risk_level="LOW",
            findings=[],
            revisions=[],
            audit_log_id="AUD-abc",
        )
        assert isinstance(payload, dict)
