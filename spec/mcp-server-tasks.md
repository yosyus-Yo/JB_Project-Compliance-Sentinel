# Tasks — MCP 서버화

> ID prefix: `MCP-`. Phase A=001-099, Phase B=101-199, Phase C=201-299, Phase D=301-399.

## Phase A — 의존성 + skeleton

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MCP-001 | `pyproject.toml` `[project.optional-dependencies] mcp = ["mcp>=1.0,<2.0"]` 추가 | todo | `pip install -e .[mcp]` 정상 |
| MCP-002 | `src/compliance_sentinel/mcp_server.py` skeleton 작성 | todo | main() + 3 tool stub 함수 + argparse `--debug` |
| MCP-003 | `pyproject.toml` `[project.scripts] cs-mcp-serve = "compliance_sentinel.mcp_server:main"` | todo | `cs-mcp-serve --help` 정상 |
| MCP-004 | MCP SDK 학습 + import 검증 | todo | `from mcp.server import Server` 정상, version 확인 |

## Phase B — Tool 본문

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MCP-101 | `compliance_review(content, language?)` tool 구현 | todo | analyze_marketing_content 호출 + final_report 직렬화 + audit_log_id 포함 |
| MCP-102 | `kb_search(query, top_k=5)` tool 구현 | todo | LawKnowledgeBase.search() + provenance/source_type/source_url 포함 |
| MCP-103 | `audit_log(audit_log_id)` tool 구현 | todo | AuditStore.read() + 존재 검증 + 부재 시 명확한 에러 |
| MCP-104 | input JSON schema 정의 (3 tool 각각) | todo | dataclass + jsonschema.validate() 통과 |
| MCP-105 | output JSON schema 정의 (3 tool 각각) | todo | 동일 |
| MCP-106 | tool 응답에 `disclaimer` 필드 inline | todo | 본 프로젝트 표준 disclaimer 포함 |

## Phase C — Transport + 통합

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MCP-201 | stdio transport server loop 구현 | todo | mcp SDK pattern으로 stdin/stdout JSON-RPC 처리 |
| MCP-202 | `--debug` 플래그 → stderr trace | todo | 모든 tool 호출이 stderr에 logging |
| MCP-203 | env override 명시 (CS_DETERMINISTIC_MODE / CS_PER_DEMO_USD) | todo | server startup 시 env 로드 + 로그 |

## Phase D — 검증

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MCP-301 | `test_mcp_compliance_review_returns_final_report` | todo | MarketingContentReviewAgent 결과와 동일 |
| MCP-302 | `test_mcp_kb_search_returns_provenance` | todo | source_url + source_type 포함 |
| MCP-303 | `test_mcp_audit_log_returns_audit_record` | todo | redacted_content + final_report inline |
| MCP-304 | `test_mcp_audit_log_missing_id_returns_error` | todo | 부재 시 명확한 error 응답 |
| MCP-305 | `test_mcp_tool_input_schema_validation` | todo | invalid input → schema error |
| MCP-306 | `test_mcp_tool_output_schema_validation` | todo | output schema 준수 |
| MCP-307 | `test_mcp_deterministic_default_no_api_key` | todo | env 없는 환경에서도 정상 응답 |
| MCP-308 | integration: mock stdio pipe → 3 tool 호출 e2e | todo | 모두 정상 응답 |
| MCP-309 | `pytest -q` 회귀 통과 | todo | 123+ passed (기존 + 8 신규) |
| MCP-310 | `docs/jb-pdf-compliance-scorecard.md` 업데이트 | todo | MCP 항목 + `pip install .[mcp]` 안내 |
| MCP-311 | `handoff/delegation-board.md` 결과 요약 | todo | AGENTS.md L24 준수 |

## Deferred

- HTTP/SSE transport (Phase 2)
- 다중 사용자 격리 (multi-tenant)
- streaming response
- 추가 tool: `revise_content` / `kb_index_stats` / `runtime_metrics`
- mcp registry 등록 (npmjs registry / pypi 분리 packaging)

## Definition of Done

1. AC 9건 충족 (`spec/mcp-server.md` §4)
2. `pytest -q` 회귀 통과 (123+ + 8 신규)
3. mock client e2e: `compliance_review` / `kb_search` / `audit_log` 3 호출 정상
4. `cs-mcp-serve` 실행 + Claude Code MCP 등록 시 tool 인식 (수동 검증)
5. scorecard + delegation-board 갱신
