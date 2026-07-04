# Plan — MCP 서버화

> `spec/mcp-server.md` 의 중간 layer. 본 프로젝트 `spec/plan.md` 패턴 (Phase A/B/C/D).

## 1. 원칙

1. **기존 인프라 재사용** — `analyze_marketing_content()`, `LawKnowledgeBase`, `AuditStore` 그대로 호출.
2. **deterministic 기본값** — `CS_DETERMINISTIC_MODE=1` default, env override 명시.
3. **stdio transport MVP** — Claude Desktop/Code 호환. HTTP/SSE는 P2.
4. **3 tool만 노출** — `compliance_review` / `kb_search` / `audit_log`. 추가 tool은 별도 spec.
5. **schema strict** — input/output dataclass 직렬화, jsonschema validation.
6. **회귀 무영향** — 기존 코드 호출만, 변경 0.

## 2. 목표 구조

```text
src/compliance_sentinel/
├── mcp_server.py             # NEW: MCP stdio server
│   ├─ tool: compliance_review (content, language?)
│   ├─ tool: kb_search        (query, top_k?)
│   └─ tool: audit_log        (audit_log_id)
├── marketing_workflow.py     # 변경 없음 (호출만)
├── knowledge_base.py         # 변경 없음
└── audit.py                  # 변경 없음

pyproject.toml
└── [project.scripts]
    cs-mcp-serve = "compliance_sentinel.mcp_server:main"
└── [project.optional-dependencies]
    mcp = ["mcp>=1.0"]

tests/test_compliance_sentinel.py
└── TestMcpServerTools (8 test)
```

## 3. 핵심 데이터 흐름

```text
External Client → stdio JSON-RPC → mcp_server.py
   ├─ compliance_review → analyze_marketing_content() → final_report dict 반환
   ├─ kb_search        → LawKnowledgeBase.search(query, top_k) → [LawArticle...] 반환
   └─ audit_log        → AuditStore.read(audit_log_id) → audit record dict 반환
```

## 4. 압축 로드맵

### Phase A — 의존성 + skeleton (1시간)
- `pyproject.toml` `[project.optional-dependencies] mcp` 추가
- `mcp_server.py` skeleton (3 tool stub + main entry)
- `cs-mcp-serve` CLI entry 등록
- 의존성 설치 검증: `pip install -e .[mcp]`

### Phase B — Tool 본문 (2시간)
- `compliance_review`: marketing_workflow 호출 + final_report 직렬화
- `kb_search`: LawKnowledgeBase 검색 + provenance 메타 포함
- `audit_log`: AuditStore 조회 + 존재 검증
- 각 tool input/output JSON schema 정의

### Phase C — Transport + 통합 (30분)
- stdio transport 구성 (mcp SDK pattern)
- `--debug` 플래그 (stderr trace)
- env override 처리 (CS_DETERMINISTIC_MODE 등)

### Phase D — 검증 (2시간)
- 8 unit test (TestMcpServerTools)
- mock client integration test (stdio pipe 시뮬레이션)
- 회귀: 123+ passed
- docs/jb-pdf-compliance-scorecard.md 갱신

## 5. 리스크와 완화

| 리스크 | 완화 |
|---|---|
| `mcp` SDK 버전 불일치 | requirements에 `mcp>=1.0,<2.0` pin |
| stdio JSON-RPC 디버깅 어려움 | `--debug` stderr trace + mock client test |
| LLM 호출 비용 폭증 | CS_DETERMINISTIC_MODE=1 default |
| MCP tool 스키마 validation 실패 | dataclass strict 직렬화 + jsonschema lib |
| 동시 호출 race | single-tenant 가정, mutex 불필요 |
| pyproject.toml extra 설치 사용자가 누락 | README + scorecard에 `pip install .[mcp]` 명시 |

## 6. 산출물 검증 매핑

| 산출물 | AC | 검증 명령 |
|---|---|---|
| `mcp_server.py` + skeleton | AC-MCP-001 | `python -m compliance_sentinel.mcp_server --help` |
| 3 tool list | AC-MCP-002 | mock client `tools/list` |
| JSON schema | AC-MCP-003 | unit test (jsonschema) |
| compliance_review 동일성 | AC-MCP-004 | unit test |
| kb_search provenance | AC-MCP-005 | unit test |
| audit_log 응답 | AC-MCP-006 | unit test |
| e2e mock stdio | AC-MCP-007 | integration test |
| 회귀 | AC-MCP-008 | pytest -q (123+ passed) |
| deterministic default | AC-MCP-009 | env clearance test |

## 7. PDF 직접 대응 표

| PDF 요구 (line) | 본 plan 대응 |
|---|---|
| line 84 "마케팅 및 제작 프로세스 자동 연계" | 외부 도구 MCP 호출로 compliance_review 자동화 |
| line 86 "근거 제공" | kb_search 응답에 source_url + source_type + provenance |
| line 88 "준법 담당자 검토·승인 역할 집중" | audit_log tool로 담당자 빠른 검토 |
