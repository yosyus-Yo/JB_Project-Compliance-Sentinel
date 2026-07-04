# Spec — MCP 서버화 (외부 에이전트/업무 시스템 연계 표준화)

> PDF 지정주제 2 우선순위 #3 — `pdf-optimization-plan.md` §5.

## 1. 목적

Compliance Sentinel을 **MCP (Model Context Protocol)** 서버로 노출하여, 외부 에이전트/Claude/Codex/IDE/슬랙봇 등이 표준 인터페이스로 준법 심의 기능을 호출할 수 있도록 한다. PDF "마케팅 및 제작 프로세스 자동 연계" (line 84) 직접 대응.

## 2. 현황

- `analyze_marketing_content()` Python 함수 노출 (CLI: `cs-router`)
- `LawKnowledgeBase` 직접 호출 가능 (in-process only)
- `AuditStore` 감사 로그 (JSONL append-only)
- **MCP 서버 미구현** — 외부 시스템은 CLI 호출 or HTTP API(`api.py` FastAPI) 우회 필요

## 3. 범위

### In Scope (MVP)

- 3개 MCP tool 노출:
  - `compliance_review(content: str, language?: str)` — 마케팅 콘텐츠 심의 (→ `analyze_marketing_content`)
  - `kb_search(query: str, top_k?: int = 5)` — 법령/내부 기준 검색
  - `audit_log(audit_log_id: str)` — 감사 로그 조회
- stdio transport (Claude Desktop / Claude Code 호환)
- deterministic 모드 default (CS_DETERMINISTIC_MODE=1)
- 모든 tool 응답에 `audit_log_id` + `disclaimer` 포함

### Out of Scope (P2 deferral)

- HTTP/SSE transport (Phase 2)
- 다중 사용자 격리 (single-tenant 가정)
- 실시간 streaming (analyze_marketing_content이 동기 API)
- 신규 검증 알고리즘
- MCP resource (file-like) 노출 — tool only

## 4. Acceptance Criteria

| AC | 내용 | 검증 |
|---|---|---|
| AC-MCP-001 | `mcp_server.py` 신규 파일 + `cs-mcp-serve` CLI entry | `python -m compliance_sentinel.mcp_server --help` |
| AC-MCP-002 | 3개 tool 정확히 노출 (compliance_review / kb_search / audit_log) | MCP `tools/list` 응답 |
| AC-MCP-003 | tool 스키마에 input/output JSON schema 명시 | jsonschema validation |
| AC-MCP-004 | `compliance_review` 응답이 `analyze_marketing_content` 결과와 동일 (id + audit_log_id) | unit test |
| AC-MCP-005 | `kb_search` 응답에 source_url + provenance + source_type 포함 | unit test |
| AC-MCP-006 | `audit_log` 응답에 disclaimer + redacted_content + final_report | unit test |
| AC-MCP-007 | 외부 client (예: `mcp_client` mock)가 stdio로 3 tool 모두 호출 성공 | integration test |
| AC-MCP-008 | 기존 123 tests 회귀 없이 통과 | pytest |
| AC-MCP-009 | deterministic 모드 default — API key 부재 시에도 mock 응답 | env clearance test |

## 5. 아키텍처

```text
External Client (Claude / Codex / Slack bot / IDE)
   │
   │ MCP stdio JSON-RPC
   ▼
mcp_server.py (cs-mcp-serve)
   ├─ tool: compliance_review → analyze_marketing_content()
   ├─ tool: kb_search        → LawKnowledgeBase.search()
   └─ tool: audit_log        → AuditStore.read(audit_log_id)
```

## 6. 의존성

- `mcp` Python SDK (pip install mcp 또는 `model-context-protocol`)
- 기존: `compliance_sentinel.marketing_workflow`, `knowledge_base`, `audit`

## 7. 위험 / 완화

| 위험 | 완화 |
|---|---|
| MCP SDK 버전 변동 | requirements에 명시 버전 pin |
| stdio transport 디버깅 어려움 | `--debug` 플래그로 stderr에 trace |
| LLM 호출 비용 폭증 | CS_DETERMINISTIC_MODE=1 default, env override 명시 안내 |
| MCP tool 결과 schema가 schema validation 거부 | jsonschema lib 활용 + 응답 dataclass 직렬화 strict |
| 동시 호출 race condition | single-tenant 가정, MVP에서 mutex 불필요 |

## 8. PDF 직접 대응 표

| PDF 요구 (line) | 본 spec 대응 |
|---|---|
| line 84 "마케팅 및 제작 프로세스 자동 연계" | 외부 마케팅 도구가 MCP로 compliance_review 호출 |
| line 86 "근거 제공" | kb_search 응답에 source_url + provenance + claim_taxonomy |
| line 88 "준법 담당자가 검토 및 승인 역할에 집중" | audit_log tool로 담당자가 binge 검토 가능 |

## 9. Phase 분해

- **Phase A** (3 task): MCP SDK 의존성 추가 + `mcp_server.py` skeleton + 3 tool stub
- **Phase B** (3 task): 3 tool 본문 구현 + 응답 schema 정의
- **Phase C** (2 task): `cs-mcp-serve` CLI entry + pyproject.toml [project.scripts] 추가
- **Phase D** (3 task): unit + integration test + deterministic 모드 검증

## 10. 예상 작업 시간

- Phase A: 1시간 (SDK 학습 + skeleton)
- Phase B: 2시간 (3 tool 구현 + schema)
- Phase C: 30분 (CLI entry)
- Phase D: 2시간 (테스트 + 디버그)

**합계: 5-6시간**

## 11. Definition of Done

1. AC 9건 모두 충족
2. `pytest -q` 회귀 통과 (123+ passed)
3. `cs-mcp-serve` 실행 + 외부 mock client로 3 tool 호출 e2e 통과
4. `docs/jb-pdf-compliance-scorecard.md` MCP 항목 추가
5. `handoff/delegation-board.md` 결과 요약

## 12. 검증 수준

| 주장 | 수준 | 근거 |
|---|---|---|
| MCP SDK 존재 | [검증됨] | Anthropic 공식 `model-context-protocol` Python SDK 배포됨 |
| `analyze_marketing_content` 직접 호출 가능 | [검증됨] | marketing_workflow.py L317 (직전 turn 검증) |
| `AuditStore` JSONL append-only | [검증됨] | audit.py 구조 |
| MCP tool 3개 충분성 | [추정] | MVP 단순화 — 추가 tool (revise_content 등)은 Phase 2 |
| stdio transport 적정성 | [추정] | Claude Desktop/Code 표준, HTTP는 별도 |
| 5-6시간 작업 시간 | [추정] | SDK 학습 비용 가변 |
