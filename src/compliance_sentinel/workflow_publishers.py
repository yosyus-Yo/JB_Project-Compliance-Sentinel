from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

from .agent_shield_bridge import authorize_tool_call
from .marketing_models import MarketingFinding, RevisionSuggestion


def _board_summary_lines(board_diagnostics: dict | None, *, limit: int = 3) -> list[str]:
    """EC Phase C (spec/error-cascade-defense.md EC-201/202): board 충돌 요약 1줄씩.

    Slack/Notion payload에 inline 노출 — 담당자가 충돌 지점 빠르게 인지.
    """
    if not board_diagnostics:
        return []
    lines: list[str] = []
    score = board_diagnostics.get("disagreement_score", 0.0)
    majority = board_diagnostics.get("majority_risk", "?")
    arb = board_diagnostics.get("requires_human_arbitration", False)
    arb_flag = "⚠️ HUMAN_REVIEW" if arb else "✓"
    lines.append(f"심의자 의견 분포: majority={majority}, disagreement={score:.2f}, arbitration={arb_flag}")
    for minority in (board_diagnostics.get("minority_opinions") or [])[:limit]:
        persona = minority.get("persona", "?")
        risk = minority.get("risk_level", "?")
        rationale = (minority.get("rationale") or "")[:80]
        lines.append(f"• 이견 [{persona}] {risk}: {rationale}")
    pair_count = len(board_diagnostics.get("contradiction_pairs") or [])
    if pair_count:
        lines.append(f"직접 모순 페르소나 쌍: {pair_count}건 (risk gap ≥ 2)")
    return lines


def build_publish_plan(*, approval_status: str, risk_level: str, audit_log_id: str = "") -> dict:
    """Describe optional real workflow delivery without making network calls by default."""
    slack_url = os.environ.get("SLACK_WEBHOOK_URL")
    notion_key = os.environ.get("NOTION_API_KEY")
    notion_db = os.environ.get("NOTION_DATABASE_ID")
    jira_url = os.environ.get("JIRA_BASE_URL")
    jira_project = os.environ.get("JIRA_PROJECT_KEY")
    status_route = {
        "APPROVED": "auto_record_and_notify",
        "APPROVE_WITH_CHANGES": "request_marketing_revision",
        "HUMAN_REVIEW_REQUIRED": "route_to_compliance_owner",
        "REJECTED": "block_publication_until_rewrite",
    }.get(approval_status, "route_to_compliance_owner")
    live_enabled = os.environ.get("CS_ENABLE_WORKFLOW_PUBLISH") == "1"
    return {
        "mode": "live_enabled" if live_enabled and (slack_url or (notion_key and notion_db) or (jira_url and jira_project)) else "live_optional" if slack_url or (notion_key and notion_db) or (jira_url and jira_project) else "mock_payload_only",
        "status_route": status_route,
        "audit_log_id": audit_log_id or "pending",
        "risk_level": risk_level,
        "slack_ready": bool(slack_url),
        "notion_ready": bool(notion_key and notion_db),
        "jira_ready": bool(jira_url and jira_project),
        "live_publish_enabled": live_enabled,
        "required_env": {
            "slack": "SLACK_WEBHOOK_URL",
            "notion": ["NOTION_API_KEY", "NOTION_DATABASE_ID"],
            "jira": ["JIRA_BASE_URL", "JIRA_PROJECT_KEY", "JIRA_API_TOKEN"],
        },
    }


def publish_slack_payload(payload: dict, *, timeout_seconds: float = 3.0) -> dict:
    """Send a Slack incoming-webhook payload when explicitly enabled.

    Network delivery is opt-in (`CS_ENABLE_WORKFLOW_PUBLISH=1`) and requires
    `SLACK_WEBHOOK_URL`. The webhook URL is never returned or logged.
    """
    if os.environ.get("CS_ENABLE_WORKFLOW_PUBLISH") != "1":
        return {"attempted": False, "ok": False, "reason": "live_publish_disabled"}
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return {"attempted": False, "ok": False, "reason": "missing_SLACK_WEBHOOK_URL"}
    guard = authorize_tool_call(
        "slack_webhook",
        "http_post",
        {"url": webhook_url, "approval_id": os.environ.get("CS_WORKFLOW_APPROVAL_ID")},
    )
    if not guard.get("allowed"):
        return {"attempted": False, "ok": False, "reason": "agentshield_runtime_guard_blocked", "guard": guard}
    body = json.dumps({"text": payload.get("text", ""), "blocks": payload.get("blocks", [])}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - explicit user-configured webhook
            status = int(getattr(response, "status", 0) or response.getcode())
            return {"attempted": True, "ok": 200 <= status < 300, "status_code": status}
    except urllib.error.HTTPError as exc:
        return {"attempted": True, "ok": False, "status_code": exc.code, "error": "HTTPError"}
    except Exception as exc:  # pragma: no cover - depends on network
        return {"attempted": True, "ok": False, "error": type(exc).__name__}


def build_slack_payload(
    *,
    approval_status: str,
    risk_level: str,
    findings: list[MarketingFinding],
    revisions: list[RevisionSuggestion],
    audit_log_id: str = "",
    board_diagnostics: dict | None = None,  # EC Phase C
) -> dict:
    publish_plan = build_publish_plan(approval_status=approval_status, risk_level=risk_level, audit_log_id=audit_log_id)
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*승인 상태*: {approval_status}\n*위험도*: {risk_level}\n*Audit*: {audit_log_id or '(pending)'}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(f"• {f.evidence}: {f.issue}" for f in findings[:5]) or "위험 표현 없음"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(f"• {r.revised}" for r in revisions[:3]) or "수정안 없음"}},
    ]
    # EC-201: board_diagnostics 요약 inline (mock_payload_only 모드에서도 노출 — EC-204)
    board_lines = _board_summary_lines(board_diagnostics)
    if board_lines:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(board_lines)}})
    return {
        "channel": "#compliance-review-mock",
        "text": f"[준법심의] {approval_status} / risk={risk_level} / findings={len(findings)}",
        "publish_plan": publish_plan,
        "board_diagnostics_summary": board_lines,  # 외부 도구에서 grep용 (EC-204)
        "blocks": blocks,
    }


def build_jira_payload(
    *,
    approval_status: str,
    risk_level: str,
    findings: list[MarketingFinding],
    revisions: list[RevisionSuggestion],
    audit_log_id: str = "",
    board_diagnostics: dict | None = None,
) -> dict:
    """Build a Jira issue contract without making network calls.

    P2 업무 연계 점수 보강용: live Jira 쓰기는 별도 인증/권한 검토 후
    붙이고, MVP에서는 schema-stable payload만 생성한다.
    """

    publish_plan = build_publish_plan(approval_status=approval_status, risk_level=risk_level, audit_log_id=audit_log_id)
    board_lines = _board_summary_lines(board_diagnostics)
    issue_type = "Bug" if approval_status == "REJECTED" else "Task"
    priority = "Highest" if risk_level == "CRITICAL" else "High" if risk_level == "HIGH" else "Medium"
    description_lines = [
        f"Approval Status: {approval_status}",
        f"Risk Level: {risk_level}",
        f"Audit ID: {audit_log_id or 'pending'}",
        "",
        "Findings:",
        *[f"- {f.evidence}: {f.issue}" for f in findings[:10]],
        "",
        "Revision Suggestions:",
        *[f"- {r.revised}" for r in revisions[:5]],
    ]
    if board_lines:
        description_lines.extend(["", "Board Diagnostics:", *[f"- {line}" for line in board_lines]])
    return {
        "project_key": os.environ.get("JIRA_PROJECT_KEY", "COMPLIANCE"),
        "issue_type": issue_type,
        "summary": f"[준법심의] {approval_status} / {risk_level} / {audit_log_id or 'pending'}",
        "priority": priority,
        "labels": ["compliance-sentinel", risk_level.lower(), approval_status.lower()],
        "publish_plan": publish_plan,
        "board_diagnostics_summary": board_lines,
        "fields": {
            "audit_log_id": audit_log_id or "pending",
            "approval_status": approval_status,
            "risk_level": risk_level,
            "finding_count": len(findings),
            "revision_count": len(revisions),
            "description": "\n".join(description_lines),
        },
    }


def build_notion_payload(
    *,
    approval_status: str,
    risk_level: str,
    findings: list[MarketingFinding],
    revisions: list[RevisionSuggestion],
    audit_log_id: str = "",
    board_diagnostics: dict | None = None,  # EC Phase C
) -> dict:
    publish_plan = build_publish_plan(approval_status=approval_status, risk_level=risk_level, audit_log_id=audit_log_id)
    children = [
        {"heading_2": "위험 표현"},
        {"bullets": [f"{f.evidence} — {f.rationale}" for f in findings]},
        {"heading_2": "수정 제안"},
        {"bullets": [r.revised for r in revisions]},
    ]
    # EC-202: board_diagnostics 요약 inline (EC-204: mock 모드에서도)
    board_lines = _board_summary_lines(board_diagnostics)
    if board_lines:
        children.append({"heading_2": "심의자 의견 분포 (Board Diagnostics)"})
        children.append({"bullets": board_lines})
    properties = {
        "Approval Status": approval_status,
        "Risk Level": risk_level,
        "Finding Count": len(findings),
        "Audit ID": audit_log_id or "pending",
    }
    if board_diagnostics:
        properties["Disagreement Score"] = board_diagnostics.get("disagreement_score", 0.0)
        properties["Arbitration Required"] = board_diagnostics.get("requires_human_arbitration", False)
    return {
        "database": "Compliance Review Mock",
        "publish_plan": publish_plan,
        "board_diagnostics_summary": board_lines,
        "properties": properties,
        "children": children,
    }


def publish_notion_payload(payload: dict, *, timeout_seconds: float = 8.0) -> dict:
    """Create a Notion database page when live publish is explicitly enabled.

    Opt-in (`CS_ENABLE_WORKFLOW_PUBLISH=1`) and requires `NOTION_API_KEY` +
    `NOTION_DATABASE_ID`. The Notion API only allows the title property at
    creation; other properties must match the DB schema, so the rest of the
    review summary is written as page body blocks. The title property name
    defaults to "Name" and can be overridden via `NOTION_TITLE_PROPERTY`.
    """
    if os.environ.get("CS_ENABLE_WORKFLOW_PUBLISH") != "1":
        return {"attempted": False, "ok": False, "reason": "live_publish_disabled"}
    api_key = os.environ.get("NOTION_API_KEY")
    database_id = os.environ.get("NOTION_DATABASE_ID")
    if not api_key or not database_id:
        return {"attempted": False, "ok": False, "reason": "missing_NOTION_API_KEY_or_DATABASE_ID"}
    guard = authorize_tool_call(
        "notion_api",
        "http_post",
        {"url": "https://api.notion.com/v1/pages", "approval_id": os.environ.get("CS_WORKFLOW_APPROVAL_ID")},
    )
    if not guard.get("allowed"):
        return {"attempted": False, "ok": False, "reason": "agentshield_runtime_guard_blocked", "guard": guard}
    props = payload.get("properties") or {}
    title = f"[준법심의] {props.get('Approval Status', '')} / {props.get('Risk Level', '')}".strip()
    title_prop = os.environ.get("NOTION_TITLE_PROPERTY", "Name")
    summary_lines = [f"{key}: {value}" for key, value in props.items()]
    body = json.dumps(
        {
            "parent": {"database_id": database_id, "type": "database_id"},
            "properties": {
                title_prop: {"title": [{"text": {"content": title[:200] or "준법심의"}}]},
            },
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": line[:1900]}}]},
                }
                for line in summary_lines
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": os.environ.get("NOTION_API_VERSION", "2026-03-11"),
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - user-configured Notion API
            status = int(getattr(response, "status", 0) or response.getcode())
            return {"attempted": True, "ok": 200 <= status < 300, "status_code": status}
    except urllib.error.HTTPError as exc:
        return {"attempted": True, "ok": False, "status_code": exc.code, "error": "HTTPError"}
    except Exception as exc:  # pragma: no cover - depends on network
        return {"attempted": True, "ok": False, "error": type(exc).__name__}


def publish_jira_payload(payload: dict, *, timeout_seconds: float = 8.0) -> dict:
    """Create a Jira Cloud issue when live publish is explicitly enabled.

    Opt-in (`CS_ENABLE_WORKFLOW_PUBLISH=1`) and requires `JIRA_BASE_URL`,
    `JIRA_PROJECT_KEY`, `JIRA_API_TOKEN`, and `JIRA_EMAIL` (Basic auth).
    Uses the Jira Cloud REST v3 endpoint; description is sent as an
    Atlassian Document Format (ADF) object as required by v3.
    """
    if os.environ.get("CS_ENABLE_WORKFLOW_PUBLISH") != "1":
        return {"attempted": False, "ok": False, "reason": "live_publish_disabled"}
    base_url = os.environ.get("JIRA_BASE_URL")
    project_key = payload.get("project_key") or os.environ.get("JIRA_PROJECT_KEY")
    api_token = os.environ.get("JIRA_API_TOKEN")
    email = os.environ.get("JIRA_EMAIL") or os.environ.get("JIRA_USER_EMAIL")
    if not base_url or not project_key or not api_token or not email:
        return {"attempted": False, "ok": False, "reason": "missing_JIRA_BASE_URL_PROJECT_KEY_API_TOKEN_or_EMAIL"}
    guard = authorize_tool_call(
        "jira_api",
        "http_post",
        {"url": base_url, "approval_id": os.environ.get("CS_WORKFLOW_APPROVAL_ID")},
    )
    if not guard.get("allowed"):
        return {"attempted": False, "ok": False, "reason": "agentshield_runtime_guard_blocked", "guard": guard}
    fields = payload.get("fields") or {}
    description_text = str(fields.get("description") or "(no description)")
    issue_body = json.dumps(
        {
            "fields": {
                "project": {"key": str(project_key)},
                "summary": str(payload.get("summary") or "[준법심의]")[:250],
                "issuetype": {"name": str(payload.get("issue_type") or "Task")},
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": description_text[:30000]}]}
                    ],
                },
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")
    auth = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
    url = base_url.rstrip("/") + "/rest/api/3/issue"
    request = urllib.request.Request(
        url,
        data=issue_body,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - user-configured Jira API
            status = int(getattr(response, "status", 0) or response.getcode())
            return {"attempted": True, "ok": 200 <= status < 300, "status_code": status}
    except urllib.error.HTTPError as exc:
        return {"attempted": True, "ok": False, "status_code": exc.code, "error": "HTTPError"}
    except Exception as exc:  # pragma: no cover - depends on network
        return {"attempted": True, "ok": False, "error": type(exc).__name__}
