# Compliance Sentinel React UI

React/Vite UI for the parent `JB_Project-Compliance-Sentinel` Python system.

## 디자인 통합 (AI Studio UI → 실제 백엔드)

프론트엔드는 `../compliance-sentinel UI/`(AI Studio Gemini mock 기반)의 디자인을 채택하고,
실제 OpenAI+Python 백엔드(`server.ts`)에 연결한 결과입니다. mock 서버는 사용하지 않습니다.

- **네비게이션 9탭**: 디자인 4탭(실시간 AI 심의기 / 대화형 분석 대시보드 / 감사 보관함 / 시스템 아키텍처)
  + 운영 5탭(Admin / 감사 로그(Audit) / Knowledge / Workflow / Batch). 기존 운영 기능 100% 보존.
- **어댑터** (`src/adapter.ts`): 백엔드 `ComplianceReport`(types.ts) ↔ 디자인 presentation 타입
  `ProjectAuditListItem`(`src/ui-types.ts`) 매핑. `/api/review` 응답을 7단계 심의 시각화 + 6인 보드 카드 +
  위험표현 하이라이트 HTML(이스케이프 적용)로 변환. 날조 데이터 없음 — 모두 실제 리포트에서 파생.
- **심의/대시보드/보관함** → 실제 `/api/review`·`/api/history` (어댑터 경유).
- **운영 5탭** → 기존 `OperationsPanel`(`/api/admin/status`·`/api/settings/*`·`/api/audit/logs`·`/api/ingest`·
  `/api/workflow/*`·`/api/batch/review`) 컴포넌트를 재사용(로직 무손상) + 새 디자인 팔레트(slate)로 정합화.

### 디자인 통합용 신규 엔드포인트 (`server.ts`)

| 엔드포인트 | 용도 |
|---|---|
| `GET /api/auth/session` · `POST /api/auth/login` · `POST /api/auth/logout` | 역할 시뮬레이터(ADMIN/COMPLIANCE_OFFICER/CONTENT_MANAGER). in-memory 세션, **실제 인증 아님** — 기능 검토용 역할 전환 |
| `GET /api/analytics/realtime` | 실시간 대시보드 지표. **in-memory history에서만 파생**(총건수/고위험비율/위반단어빈도/타임라인). 날조 없음 |
| `DELETE /api/history/:id` | in-memory 심의 이력 1건 제거. **영구 audit_logs/compliance_audit.jsonl은 절대 삭제하지 않음**(tamper-evidence) |

> 검증: `tsc --noEmit` + `vite build` 통과, 백엔드 런타임 스모크(health/realtime/login/review/history/delete) + 어댑터 엣지케이스(49 assertion) 통과.

## Run

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

For live OpenAI advisory calls, create `.env.local` from `.env.example`:

```bash
OPENAI_API_KEY="..."
CS_ENABLE_LLM_RUNTIME=1
CS_USE_LLM_BOARD_VERDICTS=1
CS_LIVE_REVIEW_PROFILE=turbo
CS_LLM_PARALLELISM=8
CS_REVIEW_CACHE_TTL_MS=300000
CS_REVIEW_CACHE_MAX=64
CS_MODEL_SHALLOW="gpt-5.4-nano"
CS_MODEL_STANDARD="gpt-5.4-mini"
CS_MODEL_DEEP="gpt-5.5"
CS_MODEL_CRITIC="gpt-5.5"
CS_PYTHON_TIMEOUT_MS=60000
CS_PYTHON_WORKER_PORT=8765
CS_PYTHON_WORKER_STARTUP_MS=20000
CS_PYTHON_WORKER_TIMEOUT_MS=60000
```

You can also configure these values in the React `Admin` tab. The secure settings console stores API keys and routing settings in the parent project file `.local/secure_settings.json.enc` using the same encrypted settings format as the Streamlit UI. Secret values are accepted through password inputs, but the API only returns `present/source` status and never returns plaintext keys for display.

## Integration

The Node server starts a local FastAPI Python worker (`compliance_sentinel.api:app`) and reuses that process for `/api/review`. This keeps the Python agent, KB, and model clients warm between UI requests. If the worker is unavailable, the server falls back to the older per-request Python subprocess bridge; if that also fails, `/api/review` uses the deterministic local rule engine and routes the result to human review instead of auto-approving.

Useful endpoints:

- `GET /api/health`
- `GET /api/admin/status`
- `GET /api/settings/status`
- `POST /api/settings/load`
- `POST /api/settings/apply`
- `POST /api/settings/save`
- `DELETE /api/settings`
- `GET /api/history`
- `GET /api/audit/logs`
- `GET /api/audit/logs/:auditId`
- `POST /api/review`
- `POST /api/batch/review`
- `POST /api/ingest`
- `GET /api/workflow/status`
- `POST /api/workflow/publish`
- `POST /api/history/clear`

## Operation Tabs

The React workspace now mirrors the parent system beyond single-draft review:

- `Admin`: encrypted LLM/API key settings, model-routing controls, runtime flags, worker, cache, and path status. Secret values are never returned.
- `Audit Logs`: persistent `audit_logs/compliance_audit.jsonl` search and detail view.
- `Knowledge`: paste or upload TXT/MD/JSON/CSV expert documents, dry-run or apply the existing Python ingest pipeline, and review automatic Skill/RAG/Memory distribution counts per file.
- `Workflow`: Slack/Notion/Jira payload preview, optional Slack live publish, LangGraph/HITL timeline visibility, MCP/audit surface status.
- `Batch`: multi-draft queue backed by the long-running Python worker and reusable deterministic agents.

Optional environment variables:

- `PYTHON_BIN`: Python executable path. Defaults to `python`.
- `CS_DISABLE_PYTHON_WORKER=1`: skip the long-running FastAPI worker and use the subprocess bridge.
- `CS_PYTHON_WORKER_PORT`: local worker port. Defaults to `8765`.
- `CS_PYTHON_WORKER_URL`: use an externally managed worker instead of auto-starting one.
- `CS_PYTHON_WORKER_STARTUP_MS`: worker startup wait. Defaults to `20000`.
- `CS_PYTHON_WORKER_TIMEOUT_MS`: worker request timeout. Defaults to `CS_PYTHON_TIMEOUT_MS` or `60000`.
- `CS_DISABLE_PYTHON_BRIDGE=1`: force local fallback.
- `CS_PYTHON_TIMEOUT_MS`: bridge timeout. Defaults to `60000`.
- `CS_ENABLE_LLM_RUNTIME=1`: allow live provider calls inside the Python engine.
- `CS_USE_LLM_BOARD_VERDICTS=1`: let structured LLM risk signals affect board diagnostics.
- `CS_LIVE_REVIEW_PROFILE=turbo|fast|balanced|strict`: `turbo` uses deterministic review for LOW, one verifier call for MEDIUM, and full validation for high-risk drafts.
- `CS_LLM_PARALLELISM`: concurrent live advisory call limit. Defaults to `8`.
- `CS_REVIEW_CACHE_TTL_MS`: repeated identical review cache TTL. Defaults to `300000`.
- `CS_REVIEW_CACHE_MAX`: maximum cached review count. Defaults to `64`.

## Documentation

자세한 사용 가이드와 API 명세는 상위 프로젝트의 `docs/` 디렉토리를 참조하세요:

- **[../docs/ui-guide.md](../docs/ui-guide.md)** — React UI 사용자 가이드 (5 tab + 9-step + 6인 보드 + 다국어 + Admin 키 설정 + 시나리오 3종)
- **[../docs/api-reference.md](../docs/api-reference.md)** — REST API 명세 (17 endpoints + 응답 schema + cURL 예시 + Fallback chain)
- **[../docs/architecture.md](../docs/architecture.md)** — 6인 보드 / Verifier 시스템 아키텍처
- **[../docs/feature-spec.md](../docs/feature-spec.md)** — F-1~F-8 핵심 기능 명세
- **[../docs/demo-script.md](../docs/demo-script.md)** — 시연 영상 스크립트
- **[../docs/mvp-proposal.md](../docs/mvp-proposal.md)** — MVP 제안서
- **[../docs/security-layers.md](../docs/security-layers.md)** — 보안 계층 모델
