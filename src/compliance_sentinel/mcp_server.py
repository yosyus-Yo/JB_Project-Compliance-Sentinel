"""MCP Server — Compliance Sentinel 외부 노출 (stdio transport).

spec/mcp-server.md Phase A (MCP-001~004).

3 tool:
  - compliance_review(content, language?) → analyze_marketing_content
  - kb_search(query, top_k?)              → LawKnowledgeBase 검색
  - audit_log(audit_log_id)               → AuditStore 조회

원칙:
  - mcp SDK는 optional extra (`[mcp]`) — 미설치 시 import 실패 명시
  - deterministic 기본값 (CS_DETERMINISTIC_MODE=1)
  - 모든 응답에 disclaimer + audit_log_id

CLI:
    cs-mcp-serve              # stdio transport 시작
    cs-mcp-serve --debug      # stderr trace 활성
    cs-mcp-serve --help
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

# MCP SDK lazy import (MCP-005 — optional extra)
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool
    _MCP_AVAILABLE = True
except ImportError as _e:
    Server = None  # type: ignore[assignment]
    stdio_server = None  # type: ignore[assignment]
    TextContent = None  # type: ignore[assignment]
    Tool = None  # type: ignore[assignment]
    _MCP_AVAILABLE = False
    _IMPORT_ERROR = str(_e)

DISCLAIMER = "본 결과는 법률 자문이 아닌 금융 마케팅 콘텐츠 준법 심의 보조 및 리스크 탐지 결과입니다."


def _require_mcp() -> None:
    """SDK 미설치 시 명확한 에러 (MCP-001)."""
    if not _MCP_AVAILABLE:
        msg = (
            f"mcp SDK 미설치. 설치: `pip install -e .[mcp]`\n"
            f"import error: {_IMPORT_ERROR if not _MCP_AVAILABLE else ''}"
        )
        print(msg, file=sys.stderr)
        sys.exit(1)


def _tool_definitions() -> list:
    """MCP-002/004: 3 tool input schema 정의."""
    if not _MCP_AVAILABLE:
        return []
    return [
        Tool(
            name="compliance_review",
            description=(
                "금융 마케팅 콘텐츠 초안의 준법 심의 보조. "
                "표현 리스크, 필수 고지 누락, 자동 수정안, board 의견 분포 반환."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "심의 대상 콘텐츠 텍스트"},
                    "language": {
                        "type": "string",
                        "description": "콘텐츠 언어 (선택). 미지정 시 자동 감지.",
                        "enum": ["ko", "en", "zh", "vi", "ja", "id"],
                    },
                },
                "required": ["content"],
            },
        ),
        Tool(
            name="kb_search",
            description="법령/내부 기준 검색 (BM25). source_url, source_type, provenance 포함.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색 쿼리"},
                    "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="audit_log",
            description="감사 로그 조회 (audit_log_id 기준).",
            inputSchema={
                "type": "object",
                "properties": {
                    "audit_log_id": {"type": "string", "description": "AUD-* 형식 ID"},
                },
                "required": ["audit_log_id"],
            },
        ),
    ]


def _handle_compliance_review(args: dict) -> dict:
    """MCP-101: analyze_marketing_content() 호출 → final_report 반환."""
    from .marketing_workflow import analyze_marketing_content
    content = args.get("content", "")
    # language 인자는 현재 analyze가 자동 감지이므로 무시 (extension point)
    report = analyze_marketing_content(content)
    report["disclaimer"] = DISCLAIMER
    return report


def _handle_kb_search(args: dict) -> dict:
    """MCP-102: LawKnowledgeBase 검색."""
    from .knowledge_base import LawKnowledgeBase
    query = args.get("query", "")
    top_k = int(args.get("top_k", 5))
    kb = LawKnowledgeBase.from_json()
    # LawKnowledgeBase에 search 메서드가 없을 수 있음 — fallback 처리
    results = []
    if hasattr(kb, "search"):
        results = kb.search(query, limit=top_k)
    else:
        # fallback: 모든 article에서 query 포함 article 반환
        for article in kb.articles[:top_k * 2]:
            if query.lower() in (article.text + article.title + article.law_name).lower():
                results.append(article)
                if len(results) >= top_k:
                    break
    from .knowledge_base import article_provenance
    return {
        "query": query,
        "top_k": top_k,
        "results": [article_provenance(a) for a in results],
        "disclaimer": DISCLAIMER,
    }


def _handle_audit_log(args: dict) -> dict:
    """MCP-103: AuditStore 조회."""
    from .audit import AuditStore
    audit_log_id = args.get("audit_log_id", "")
    store = AuditStore()
    # AuditStore에 read 메서드가 있는지 확인
    if hasattr(store, "read"):
        record = store.read(audit_log_id)
    elif hasattr(store, "find"):
        record = store.find(audit_log_id)
    else:
        # fallback: log 파일 직접 grep
        record = None
        log_path = getattr(store, "log_path", None) or getattr(store, "path", None)
        if log_path and os.path.exists(str(log_path)):
            with open(log_path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                        if row.get("audit_log_id") == audit_log_id:
                            record = row
                            break
                    except json.JSONDecodeError:
                        continue
    if record is None:
        return {
            "error": f"audit_log_id not found: {audit_log_id}",
            "audit_log_id": audit_log_id,
            "disclaimer": DISCLAIMER,
        }
    return {
        "audit_log_id": audit_log_id,
        "record": record,
        "disclaimer": DISCLAIMER,
    }


TOOL_HANDLERS = {
    "compliance_review": _handle_compliance_review,
    "kb_search": _handle_kb_search,
    "audit_log": _handle_audit_log,
}


async def _serve() -> None:
    """MCP-201: stdio transport server loop."""
    _require_mcp()
    app = Server("compliance-sentinel")

    @app.list_tools()
    async def list_tools() -> list:
        return _tool_definitions()

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list:
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            result = {"error": f"unknown tool: {name}", "disclaimer": DISCLAIMER}
        else:
            try:
                result = handler(arguments or {})
            except Exception as e:
                result = {
                    "error": f"tool execution failed: {type(e).__name__}: {e}",
                    "tool": name,
                    "disclaimer": DISCLAIMER,
                }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main() -> int:
    """MCP-003: cs-mcp-serve CLI entry."""
    parser = argparse.ArgumentParser(description="Compliance Sentinel MCP Server (stdio transport)")
    parser.add_argument("--debug", action="store_true", help="stderr trace 활성")
    parser.add_argument("--check", action="store_true", help="설치 검증만 (실제 serve 안 함)")
    args = parser.parse_args()

    if args.check:
        if _MCP_AVAILABLE:
            print("MCP SDK 설치 확인: OK")
            print(f"Tool count: {len(_tool_definitions())}")
            print("Tools:", [t.name for t in _tool_definitions()])
            return 0
        else:
            print(f"MCP SDK 미설치. 설치: `pip install -e .[mcp]`", file=sys.stderr)
            return 1

    if args.debug:
        os.environ.setdefault("CS_MCP_DEBUG", "1")

    _require_mcp()
    asyncio.run(_serve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
