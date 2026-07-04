# Compliance Sentinel — REST API Reference

> **대상**: 개발자, 통합 작업자
> **베이스 URL**: `http://localhost:3000` (Node + Express)
> **백엔드**: Node server.ts → FastAPI Python worker (port 8765) 자동 spawn
> **인증**: 현재 부재 (MVP). production은 별도 layer 추가 필요

---

## 0. 동작 모드 (응답 차이)

| 모드 | 트리거 | `/api/review` 응답 |
|---|---|---|
| **deterministic** | API key 미설정 (`CS_ENABLE_LLM_RUNTIME` 미설정) | 규칙 기반 분석 + `routing_decision.target="local"` |
| **hybrid** | API key 설정 + `CS_LIVE_REVIEW_PROFILE=turbo` | LOW 규칙만 / MEDIUM 1 verifier call / HIGH 풀 LLM |
| **full LLM live** | + `CS_USE_LLM_BOARD_VERDICTS=1` | 6인 보드까지 LLM 호출 |

---

## 1. Health & Admin (3)

### `GET /api/health`

Python worker / bridge / cache 상태 확인.

**Response 200**:
```json
{
  "status": "ok",
  "app": "compliance-sentinel-ui",
  "parent_root": "/path/to/JB_Project-Compliance-Sentinel",
  "python_bridge": {
    "enabled": true,
    "python_bin": "python",
    "source_path": "/path/to/src",
    "source_present": true
  },
  "python_worker": {
    "enabled": true,
    "url": "http://localhost:8765",
    "auto_start": true,
    "status": "ready",
    "pid": 67009,
    "timeout_ms": 60000
  },
  "review_cache": {
    "enabled": true,
    "size": 0,
    "max": 64,
    "ttl_ms": 300000
  },
  "history_count": 3
}
```

### `GET /api/admin/status`

상세 admin 상태 — 모델 routing / runtime flags / secret status / paths.

**Response 200**:
```json
{
  "parent_root": "/path/...",
  "app_root": "/path/.../compliance-sentinel",
  "paths": {"audit_logs": true, "secure_settings": false},
  "model_routing": {
    "shallow": "gpt-5.4-mini",
    "standard": "gpt-5.4-mini",
    "deep": "gpt-5.5",
    "critic": "gpt-5.5",
    "live_profile": "turbo",
    "llm_parallelism": "8"
  },
  "runtime_flags": {
    "CS_ENABLE_LLM_RUNTIME": true,
    "CS_USE_LLM_BOARD_VERDICTS": true
  },
  "secrets": {
    "OPENAI_API_KEY": {"present": true, "source": "env"}
  },
  "python_worker": {...},
  "cache": {...}
}
```

---

## 2. Secure Settings (5)

암호화 설정 영구 저장 — `.local/secure_settings.json.enc`

### `GET /api/settings/status`

저장된 secure_settings 상태 + schema.

**Response 200**:
```json
{
  "encrypted_settings_present": true,
  "updated_at": "2026-05-26T15:00:00Z",
  "models": {"shallow": "gpt-5.4-mini", "deep": "gpt-5.5"},
  "routing": {"live_profile": "turbo"},
  "flags": {"CS_ENABLE_LLM_RUNTIME": "1"},
  "secrets": {
    "OPENAI_API_KEY": {"present": true, "source": "encrypted"}
  },
  "schema": {
    "secret_fields": [{"env": "OPENAI_API_KEY", "label": "OpenAI API Key", "kind": "password", "required": true}],
    "model_fields": [...],
    "flag_fields": [...],
    "routing_fields": [...]
  },
  "applied": true
}
```

### `POST /api/settings/load`

마스터 비밀번호로 암호화 설정 unlock + 메모리에 로드.

**Request**:
```json
{ "master_password": "my-master-pwd-2026" }
```

**Response 200**: 위 `/status`와 동일 형식 + 복호화된 값 반영.

### `POST /api/settings/apply`

현재 입력값을 Python worker에 즉시 적용 (저장 안 함).

**Request**:
```json
{
  "models": {"deep": "gpt-5.5"},
  "secrets": {"OPENAI_API_KEY": "sk-..."},
  "flags": {"CS_ENABLE_LLM_RUNTIME": "1"}
}
```

**Response 200**:
```json
{
  "applied": true,
  "python_worker_restart": "ready"
}
```

### `POST /api/settings/save`

마스터 비밀번호로 암호화하여 영구 저장.

**Request**:
```json
{
  "master_password": "my-master-pwd-2026",
  "models": {...},
  "secrets": {...}
}
```

**Response 200**:
```json
{
  "saved": true,
  "encrypted_path": ".local/secure_settings.json.enc",
  "updated_at": "2026-05-26T15:00:00Z"
}
```

### `DELETE /api/settings`

저장된 암호화 설정 파일 삭제 (마스터 비밀번호 잊었을 때).

**Response 200**:
```json
{ "deleted": true }
```

---

## 3. Review (메인, 2)

### `POST /api/review` ⭐

마케팅 문구 1건 분석 — 본 시스템의 **메인 endpoint**.

**Request**:
```json
{
  "content": "JB 자동차 금융, 누구나 100% 승인. 최저금리 보장으로 오늘 바로 출고하세요.",
  "metadata": {
    "language": "ko",
    "channel": "app_push",
    "product_type": "auto_loan",
    "target_audience": "general"
  }
}
```

**Response 200** (ComplianceReport — 약 30+ 필드):
```json
{
  "review_request_id": "RR-JB-20260526-3730",
  "raw_content": "JB 자동차 금융, 누구나 100% 승인...",
  "input_completeness": {
    "accepted": true,
    "mode": "auto-inferred",
    "inferred_metadata": {"language": "ko", "channel": "app_push", ...}
  },
  "approval_status": "REJECTED",
  "risk_level": "CRITICAL",
  "confidence": "high",
  "confidence_score": 0.95,
  "summary": "승인보장·최저금리 보장 표현이 자본시장법/광고심의 기준 위반",
  "language": "ko",
  "channel": "app_push",
  "product_type": "auto_loan",
  "redacted_content": "[원문, PII 부재]",
  "findings": [
    {
      "id": "F-001",
      "category": "guarantee",
      "finding_text": "100% 승인",
      "reason": "심사 없이 모두 승인된다는 오인 유발",
      "suggested_revision": "심사 기준 충족 시 빠른 승인",
      "severity": "CRITICAL",
      "law_name": "RULE-GUARANTEE",
      "language": "ko"
    }
  ],
  "evidence": [
    {"clause": "RULE-GUARANTEE", "verbatim": "...", "exists": true, "match": true, "applicable": true, "confidence": 1.0}
  ],
  "revision_suggestions": "심사 결과에 따라 승인...",
  "board_diagnostics": [
    {
      "persona": "legal-counsel",
      "abbreviation": "LG",
      "name_kor": "법률 자문",
      "opinion": "REJECT",
      "rationale": "표현 근거와 필수 고지의 명확성을 보완해야 합니다."
    },
    {"persona": "pipa-credit-info-expert", "abbreviation": "PV", "name_kor": "개인정보", "opinion": "APPROVE", ...},
    {"persona": "consumer-protection-expert", "abbreviation": "CP", "name_kor": "소비자 보호", "opinion": "REJECT", ...},
    {"persona": "aml-operational-risk-expert", "abbreviation": "AM", "opinion": "APPROVE", ...},
    {"persona": "business-practicality-expert", "abbreviation": "BP", "opinion": "HUMAN", ...},
    {"persona": "contrarian-agent", "abbreviation": "CT", "opinion": "HUMAN", ...}
  ],
  "verifier_result": {
    "status": "PASS",
    "model": "gpt-5.5",
    "verified_claims": [...],
    "unverified_claims": []
  },
  "schema_validation": {"valid": true, "errors": []},
  "audit_log_id": "AL-20260526-3730",
  "timestamp": "2026-05-26T15:00:00Z",
  "human_review_needed": false,
  "guard_flags": {"pii_detected": false, "pii_redacted_count": 0},
  "workflow_publish_plan": {"slack": "ready", "notion": "ready"},
  "raw_report": {...}
}
```

**에러 응답**:
- `400`: 필수 필드 누락 (`content`)
- `500`: Python worker 또는 LLM 실패
- `502`: Python bridge fallback도 실패

### `POST /api/batch/review`

다중 초안 일괄 분석 (long-running Python worker 재사용).

**Request**:
```json
{
  "drafts": [
    {"content": "초안 1...", "metadata": {...}},
    {"content": "초안 2...", "metadata": {...}}
  ]
}
```

**Response 200**:
```json
{
  "results": [
    {"review_request_id": "RR-...", "approval_status": "REJECTED", ...},
    {"review_request_id": "RR-...", "approval_status": "APPROVED", ...}
  ],
  "total": 2,
  "elapsed_ms": 5230
}
```

---

## 4. History (2)

### `GET /api/history`

최근 분석 결과 list (in-memory cache + audit_logs jsonl).

**Response 200**:
```json
{
  "items": [
    {
      "audit_log_id": "AL-20260526-3730",
      "review_request_id": "RR-...",
      "timestamp": "2026-05-26T15:00:00Z",
      "approval_status": "REJECTED",
      "risk_level": "CRITICAL",
      "raw_content_preview": "JB 자동차 금융...",
      "human_review_needed": false
    }
  ],
  "total": 3,
  "counts": {"approved": 0, "rejected": 3, "hitl": 0}
}
```

### `POST /api/history/clear`

In-memory history 초기화 (jsonl audit 파일은 유지).

**Response 200**:
```json
{ "cleared": true, "previous_count": 3 }
```

---

## 5. Audit Logs (2)

### `GET /api/audit/logs?q=<query>&limit=<n>`

영구 audit 로그 검색 — `audit_logs/compliance_audit.jsonl`

**Query params**:
- `q` (선택): Audit ID / status / route / text 키워드
- `limit` (선택, default 50)

**Response 200**:
```json
{
  "items": [
    {
      "audit_log_id": "AL-20260526-3730",
      "created_at": "2026-05-26T15:00:00Z",
      "final_status": "REJECTED",
      "human_review_needed": false,
      "input_type": "marketing_draft",
      "redacted_text": "JB 자동차 금융...",
      "routing_decision": {"target": "local", "model": "gpt-5.5"},
      "llm_call_count": 3,
      "trace_count": 9,
      "model_plan": {...},
      "cross_model_result": {...}
    }
  ],
  "total": 3
}
```

### `GET /api/audit/logs/:auditId`

단일 audit log 상세 (전체 final_report + traces).

**Response 200**: 위 item 1건의 전체 데이터.
**Response 404**: 해당 audit ID 부재.

---

## 6. Knowledge Ingest (1)

### `POST /api/ingest`

전문가 문서를 Skill/RAG/Memory에 분배 적재.

**Request**:
```json
{
  "source": "internal-guide-2026.md",
  "content": "본 문서는 광고 심의 가이드...",
  "dry_run": false,
  "approve_memory": true,
  "trust_label": "internal-trusted"
}
```

**Response 200**:
```json
{
  "source": "internal-guide-2026.md",
  "applied": true,
  "approved_memory": true,
  "total_chunks": 12,
  "blocked_chunks": 0,
  "target_counts": {"skill": 4, "rag": 6, "memory": 2},
  "skill_path": "src/.../skills/internal-guide-2026.json",
  "rag_path": "src/.../rag/internal-guide-2026.jsonl",
  "pending_path": "src/.../memory/pending/internal-guide-2026.json",
  "trust_summary": {"internal-trusted": 12},
  "written_skill_items": 4,
  "written_rag_items": 6,
  "written_memory_items": 2,
  "chunks": [...]
}
```

**dry_run=true**: `applied=false` + 분배 시뮬레이션 결과만 반환 (실 저장 안 함).

---

## 7. Workflow (2)

### `GET /api/workflow/status`

외부 공유 / HITL / LangGraph / MCP 상태.

**Response 200**:
```json
{
  "mode": "draft",
  "live_publish_enabled": false,
  "targets": {
    "slack": {"ready": true, "live_supported": true},
    "notion": {"ready": true, "live_supported": false},
    "jira": {"ready": false, "live_supported": false}
  },
  "langgraph": {"node_count": 9, "current_node": "audit"},
  "hitl": {"queue_size": 0, "average_wait_ms": 0},
  "observability": {...},
  "mcp": {...}
}
```

### `POST /api/workflow/publish`

분석 결과를 외부 채널에 publish.

**Request**:
```json
{
  "audit_log_id": "AL-20260526-3730",
  "targets": ["slack"],
  "preview_only": false
}
```

**Response 200** (preview_only=true):
```json
{
  "preview": true,
  "payloads": {
    "slack": {"blocks": [...], "text": "..."},
    "notion": {...}
  }
}
```

**Response 200** (preview_only=false + `CS_LIVE_PUBLISH_ENABLED=1`):
```json
{
  "published": true,
  "results": {
    "slack": {"ok": true, "message_ts": "1735200000.000000"}
  }
}
```

---

## 8. 환경변수

### 필수 (LLM live mode)

| 변수 | 설명 |
|---|---|
| `OPENAI_API_KEY` | OpenAI API 키 (sk-...) |
| `CS_ENABLE_LLM_RUNTIME=1` | LLM 호출 활성 |
| `CS_USE_LLM_BOARD_VERDICTS=1` | 6인 보드 의견에도 LLM 사용 |

### 모델 routing

| 변수 | Default | 설명 |
|---|---|---|
| `CS_MODEL_SHALLOW` | `gpt-5.4-nano` | LOW 위험 / 빠른 분류 |
| `CS_MODEL_STANDARD` | `gpt-5.4-mini` | MEDIUM 분석 |
| `CS_MODEL_DEEP` | `gpt-5.5` | HIGH 위험 풀 분석 |
| `CS_MODEL_CRITIC` | `gpt-5.5` | Verifier / Cross-model |

### Profile (속도 vs 정확도)

| 변수 | Options |
|---|---|
| `CS_LIVE_REVIEW_PROFILE` | `turbo` (빠름) / `fast` / `balanced` / `strict` (정확) |
| `CS_LLM_PARALLELISM` | 동시 LLM 호출 한도 (default 8) |

### Cache

| 변수 | Default | 설명 |
|---|---|---|
| `CS_REVIEW_CACHE_TTL_MS` | `300000` (5분) | 동일 문구 캐시 |
| `CS_REVIEW_CACHE_MAX` | `64` | 최대 캐시 건수 |

### Python worker

| 변수 | Default | 설명 |
|---|---|---|
| `CS_PYTHON_WORKER_PORT` | `8765` | FastAPI worker port |
| `CS_PYTHON_WORKER_STARTUP_MS` | `20000` (20초) | worker 시작 대기 |
| `CS_PYTHON_WORKER_TIMEOUT_MS` | `60000` (1분) | request timeout |
| `CS_DISABLE_PYTHON_WORKER=1` | (off) | worker 비활성, subprocess bridge 사용 |
| `CS_DISABLE_PYTHON_BRIDGE=1` | (off) | bridge도 비활성, deterministic local만 |
| `PYTHON_BIN` | `python` | Python 실행파일 경로 |

---

## 9. Fallback chain

`/api/review` 호출 실패 시 자동 fallback:

```
1. FastAPI Python worker (port 8765, warm)
   ↓ 실패
2. Python subprocess bridge (1회성 spawn)
   ↓ 실패
3. Local deterministic rule engine
   + human_review_needed=true (자동 승인 차단)
```

→ 어떤 경우에도 시스템 다운 없이 응답 보장 (단 모드별 정확도 차이).

---

## 10. cURL 예시

### 기본 분석

```bash
curl -X POST http://localhost:3000/api/review \
  -H "Content-Type: application/json" \
  -d '{
    "content": "원금 보장 적금. 100% 안전합니다.",
    "metadata": {"language": "ko", "channel": "banner"}
  }'
```

### 다국어 분석

```bash
curl -X POST http://localhost:3000/api/review \
  -H "Content-Type: application/json" \
  -d '{
    "content": "zero risk savings / 零风险存款保证",
    "metadata": {"language": "auto"}
  }'
```

### 시스템 상태 확인

```bash
curl http://localhost:3000/api/health
curl http://localhost:3000/api/admin/status
curl 'http://localhost:3000/api/audit/logs?q=REJECTED&limit=10'
```

### 일괄 분석

```bash
curl -X POST http://localhost:3000/api/batch/review \
  -H "Content-Type: application/json" \
  -d '{
    "drafts": [
      {"content": "초안 1: 무조건 승인", "metadata": {}},
      {"content": "초안 2: 안전한 투자", "metadata": {}}
    ]
  }'
```

---

## 11. 보안 / production 주의

| 영역 | MVP 현재 | production 필수 |
|---|---|---|
| 인증 | ❌ 누구나 localhost:3000 | API key auth / OAuth / session |
| HTTPS | ❌ HTTP만 | TLS termination (nginx / Caddy) |
| CORS | ⚠ 모든 origin 허용 (server.ts) | allowlist 명시 |
| 레이트 리미트 | ❌ 부재 | express-rate-limit |
| secret 저장 | ✅ `.local/*.enc` (마스터 비밀번호 암호화) | KMS / Vault 권장 |
| audit log | ✅ jsonl 영구 보존 | PostgreSQL + 백업 |
| LLM 비용 통제 | △ profile / cache | 사용자별 budget cap |

---

## 12. 관련 문서

- **[ui-guide.md](./ui-guide.md)** — React UI 사용자 가이드 (5 tab + 9-step + 6인 보드)
- **[architecture.md](./architecture.md)** — 6인 보드 / Verifier 시스템 아키텍처
- **[feature-spec.md](./feature-spec.md)** — F-1~F-8 핵심 기능 명세
- **[final-report-schema.json](./final-report-schema.json)** — `/api/review` 응답 JSON Schema (full)
- **[../compliance-sentinel/README.md](../compliance-sentinel/README.md)** — React UI 설치 + 환경변수

---

## 검증 수준

| 주장 | 수준 | 근거 |
|---|---|---|
| 17 endpoints (3 health/admin + 5 settings + 2 review + 2 history + 2 audit + 1 ingest + 2 workflow) | [검증됨] | server.ts grep `app.(get|post|delete)` 직접 인용 |
| /api/review 응답 schema 30+ 필드 | [검증됨] | types.ts ComplianceReport interface (L101-131) 인용 |
| Fallback chain (worker→bridge→local) | [검증됨 README] | README L38 인용 |
| 환경변수 list | [검증됨] | README L14-32 + L69-84 인용 |
| 보안 / production 비교 | [추정] | 일반 web service 표준, 본 SEAS 실측 안 함 |
| `CS_LIVE_PUBLISH_ENABLED=1` 환경변수 | [추정] | server.ts publish endpoint 추론, 직접 확인 안 함 |
| cURL 예시 동작 | [추정] | 일반 curl/JSON 표준, 실제 호출 검증 안 함 |
