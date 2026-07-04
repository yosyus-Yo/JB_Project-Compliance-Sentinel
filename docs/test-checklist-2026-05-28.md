# JB Compliance Sentinel — 통합 테스트 체크리스트

> **작성일**: 2026-05-28
> **목적**: 데모영상 (6/5 마감) 녹화 전 모든 구현 기능 정상 작동 검증
> **브랜치**: `benchmark-aieev-2026-05-21` (main merged at `ea830b5`)
> **사용법**: 각 항목 PASS/FAIL 체크. FAIL 발견 시 즉시 fix 또는 데모 시연 회피 결정.

---

## §0. 사전 환경 검증 (5분)

| # | 항목 | 명령 | 기대 결과 | PASS |
|---|---|---|---|:--:|
| 0.1 | Node 서버 실행 중 | `curl -s http://127.0.0.1:3000/api/health \| jq .status` | `"ok"` | ☐ |
| 0.2 | Python worker ready | `curl -s http://127.0.0.1:3000/api/health \| jq .python_worker.status` | `"ready"` | ☐ |
| 0.3 | `CS_ENABLE_LLM_RUNTIME=1` 적용 | worker env 확인 | `=***SET***` | ☐ |
| 0.4 | `OPENAI_API_KEY` 새 키 적용 | Admin UI Secure Settings → `OpenAI: present` | ✓ | ☐ |
| 0.5 | `LAW_OPEN_API_KEY=lawosopenapi` | worker env 확인 | `=***SET***` | ☐ |
| 0.6 | OpenAI Console project limit 설정 | https://platform.openai.com/usage | 한도 표시 | ☐ |
| 0.7 | UI 접속 가능 | http://localhost:3000 | 6개 탭 표시 | ☐ |

---

## §1. LLM Runtime + Cost Safety (8분)

| # | 항목 | 검증 방법 | 기대 결과 | PASS |
|---|---|---|---|:--:|
| 1.1 | `service_tier="default"` 호출 시 명시 | `audit_logs/llm_cost_ledger.jsonl` 최근 entry | `service_tier: default` 또는 priority 미사용 | ☐ |
| 1.2 | `gpt-5.5-pro` 자동 alias 차단 | model 필드 확인 | `gpt-5_5-2026-04-23` 또는 `gpt-5_4-mini-...` (pro 아님) | ☐ |
| 1.3 | `gpt-5` reasoning 토큰 32000 상향 | "Could not finish" 400 에러 없음 | 정상 응답 | ☐ |
| 1.4 | `_reasoning_effort_for_model` 동작 | gpt-5 호출에 `reasoning_effort` 파라미터 전송 | ledger에 effort 기록 | ☐ |
| 1.5 | `response_format` JSON 모드 | 구조화 응답 정상 파싱 | ✓ | ☐ |
| 1.6 | Deterministic fallback 작동 | `CS_ENABLE_LLM_RUNTIME=0` 환경에서 분석 시 | LLM 호출 0건 + 규칙 기반 결과 | ☐ |
| 1.7 | 단일 분석 비용 ≤ $0.05 | ledger 확인 | ✓ (이전 $128 spike 재발 없음) | ☐ |

---

## §2. 9-Step 워크플로우 (15분)

> Case A (한국어 정상) / Case B (영문 위반) / Case C (다국어 혼합) 3건으로 검증

| # | Step | 검증 항목 | PASS A | PASS B | PASS C |
|---|---|---|:--:|:--:|:--:|
| 2.1 | **PII 마스킹** | 주민번호/카드/이메일 마스킹, 마스킹 카운트 표시 | ☐ | ☐ | ☐ |
| 2.2 | **분류** | language/channel/product_type/target_audience 추론 | ☐ | ☐ | ☐ |
| 2.3 | **법령 RAG** | retrieved_law_provenance 1+ 항목, source_url 채워짐 | ☐ | ☐ | ☐ |
| 2.4 | **6인 보드** | 6 페르소나 모두 의견 출력 (legal_counsel/pipa/consumer/operational/business/contrarian) | ☐ | ☐ | ☐ |
| 2.5 | **CEO synthesizer** | 최종 approval_status + 근거 통합 | ☐ | ☐ | ☐ |
| 2.6 | **Verifier** | atomic claims 검증 (PASS/FAIL/PARTIAL) | ☐ | ☐ | ☐ |
| 2.7 | **라우팅** | HITL 필요 여부 자동 판정 | ☐ | ☐ | ☐ |
| 2.8 | **공유 plan** | workflow_publish_plan + targets | ☐ | ☐ | ☐ |
| 2.9 | **감사 로그** | audit_log_id 발급 + jsonl entry 생성 | ☐ | ☐ | ☐ |

---

## §3. 법령 RAG 검증 ⭐ (10분)

> 사용자 핵심 요청 — "RAG도 잘 작동하는지"

### 3-1. Backend 동작

| # | 항목 | 검증 | PASS |
|---|---|---|:--:|
| 3.1.1 | `rag_metadata.law_backend` 표시 | `hybrid_keyword_qdrant_rrf` 또는 `keyword_fallback` | ☐ |
| 3.1.2 | Qdrant 서버 활성 여부 표시 | `qdrant_status` 객체 | ☐ |
| 3.1.3 | `law_count > 0` (최소 1건 retrieval) | ✓ | ☐ |
| 3.1.4 | Cache hit/miss 추적 | `rag_cache_hit: true/false` | ☐ |
| 3.1.5 | `document_rag_count` (보조 문서 RAG) | 1+ chunks | ☐ |

### 3-2. RRF (Reciprocal Rank Fusion) — Qdrant 활성 시

| # | 항목 | 검증 | PASS |
|---|---|---|:--:|
| 3.2.1 | keyword + dense 두 source 모두 활성 | log 확인 | ☐ |
| 3.2.2 | 가중치 (keyword 0.45 / dense 0.55) 적용 | `_rrf_merge` | ☐ |
| 3.2.3 | 중복 article dedup | 동일 `(law_name, article_no, source_url)` 1회만 | ☐ |
| 3.2.4 | top-K (5) limit 적용 | ✓ | ☐ |

### 3-3. source_url 변환 ⭐⭐ (직전 turn fix)

| # | 항목 | 검증 | PASS |
|---|---|---|:--:|
| 3.3.1 | 외부 공식 법령 → `https://www.law.go.kr/...` | `_resolve_public_source_url` 결과 | ☐ |
| 3.3.2 | JB 내부 기준 → `local://` 유지 | ✓ | ☐ |
| 3.3.3 | UI "원문 ↗" 버튼 클릭 → law.go.kr 새 탭 열림 | 사용자 클릭 검증 | ☐ |
| 3.3.4 | UI "내부 기준 (검색) ↗" 라벨 표시 | ✓ | ☐ |
| 3.3.5 | 외부 URL 검색 fallback (`/lsSc.do?query=...`) 정상 동작 | ✓ | ☐ |

### 3-4. PII 격리 (RAG 보안)

| # | 항목 | 검증 | PASS |
|---|---|---|:--:|
| 3.4.1 | 프롬프트 인젝션 패턴 차단 | `PROMPT_INJECTION_MEMORY_RE` 매칭 시 redacted | ☐ |
| 3.4.2 | URL → `[url-redacted]` 변환 | 메모리 캡처 시 | ☐ |
| 3.4.3 | RAG 메모리에 raw user input 미적재 | `_safe_snippet` 적용 | ☐ |

---

## §4. 6-Agent Compliance Board (5분)

| # | 페르소나 | 역할 | 검증 항목 | PASS |
|---|---|---|---|:--:|
| 4.1 | `legal_counsel` | 법률 자문 | 자본시장법/금소법 인용 | ☐ |
| 4.2 | `pipa_expert` | 개인정보보호법 | PII 노출 위험 평가 | ☐ |
| 4.3 | `consumer_protection` | 금융소비자 보호 | 부당광고/오해 소지 식별 | ☐ |
| 4.4 | `operational_risk` | 운영 리스크 | 채널/사후 모니터링 | ☐ |
| 4.5 | `business_practicality` | 사업 실효성 | 마케팅 효과 vs 규제 비용 | ☐ |
| 4.6 | `contrarian` | 반론자 | 다수 의견 challenge | ☐ |
| 4.7 | risk_level 분포 | NONE/LOW/MEDIUM/HIGH/CRITICAL 매핑 | ☐ |  |
| 4.8 | opinion 분포 | APPROVE/AMEND/REJECT/HUMAN 매핑 | ☐ |  |

---

## §5. Marketing Copy 자동 재작성 ⭐ (5분)

> 직전 turn 통합 (marketing_reviewer.py + marketing_workflow.py)

| # | 항목 | 검증 | PASS |
|---|---|---|:--:|
| 5.1 | `marketing_rewrite.rewritten` 채워짐 | non-null 텍스트 | ☐ |
| 5.2 | `removed_terms` 배열 (위반 용어 목록) | ✓ | ☐ |
| 5.3 | `added_notices` 배열 (필수 고지 추가) | ✓ | ☐ |
| 5.4 | `model` 필드 (사용된 LLM 모델 명시) | ✓ | ☐ |
| 5.5 | `deterministic_fallback` 플래그 | true/false | ☐ |
| 5.6 | LLM 실패 시 fallback 정상 동작 | `error` 필드 있음 | ☐ |
| 5.7 | 재작성 결과 UI 표시 | "수정 적용" 버튼 동작 | ☐ |

---

## §6. UI / React (7분)

| # | 항목 | 검증 | PASS |
|---|---|---|:--:|
| 6.1 | **Report 탭** | 6 섹션 (Hero/Runtime/PII/Workflow/RAG/Marketing) 모두 표시 | ☐ |
| 6.2 | **Admin 탭** | Secure Settings 패널 + API key 저장 | ☐ |
| 6.3 | **Audit Logs 탭** | 최근 분석 이력 list + clickable | ☐ |
| 6.4 | **Knowledge 탭** | RAG corpus / coverage report 표시 | ☐ |
| 6.5 | **Workflow 탭** | LangGraph adapter status + HITL | ☐ |
| 6.6 | **Batch 탭** | 일괄 분석 기능 | ☐ |
| 6.7 | 다국어 깃발 grouping (P1-5) | KR/EN/ZH/VI/JA/TH/ID/AR 매핑 | ☐ |
| 6.8 | 9-step workflow 시각화 (`WorkflowSteps`) | ✓ | ☐ |
| 6.9 | Copy to clipboard (Review/Audit ID) | ✓ | ☐ |
| 6.10 | Risk pill 색상 (tone-green/amber/red) | risk_level별 다름 | ☐ |
| 6.11 | RAG retrieved laws 패널 (Database 아이콘) | ✓ | ☐ |
| 6.12 | "원문 ↗" / "원문 검색 ↗" / "내부 기준 (검색) ↗" 분기 | ⭐ (직전 turn fix) | ☐ |

---

## §7. Demo Cases 사전 검증 (10분)

### Case A — 한국어 정상 (APPROVE)
```
원자력 ETF — 안전성 강조 + 위험 고지 포함된 정상 카피
```
| 검증 | 기대 | PASS |
|---|---|:--:|
| approval_status | `APPROVED` 또는 `APPROVE_WITH_CHANGES` | ☐ |
| risk_level | `NONE` / `LOW` | ☐ |
| confidence_score | ≥ 0.7 | ☐ |
| 6인 보드 다수 APPROVE | ≥ 4/6 | ☐ |

### Case B — 영문 위반 (HUMAN_REVIEW)
```
Crypto staking — 원금 보장 표현 + 위험 고지 누락
```
| 검증 | 기대 | PASS |
|---|---|:--:|
| approval_status | `HUMAN_REVIEW_REQUIRED` 또는 `REJECTED` | ☐ |
| risk_level | `HIGH` / `CRITICAL` | ☐ |
| findings | "원금 보장" 위반 명시 | ☐ |
| marketing_rewrite.rewritten | 수정안 제공 | ☐ |

### Case C — 다국어 (PII 마스킹)
```
KR + EN 혼합 + 주민번호/카드번호 포함
```
| 검증 | 기대 | PASS |
|---|---|:--:|
| pii_detected: true | ✓ | ☐ |
| pii_redacted_count | ≥ 2 | ☐ |
| language detection | KR + EN 분리 grouping | ☐ |
| 깃발 표시 | 🇰🇷 + 🇺🇸 | ☐ |

---

## §8. Audit Logs (3분)

| # | 항목 | 검증 | PASS |
|---|---|---|:--:|
| 8.1 | `audit_logs/compliance_audit.jsonl` 신규 entry append | 분석 후 +1 line | ☐ |
| 8.2 | `audit_logs/llm_cost_ledger.jsonl` LLM 호출 기록 | ✓ | ☐ |
| 8.3 | `audit_log_id` UUID 형식 | ✓ | ☐ |
| 8.4 | `trace_count` 9-step 모두 기록 | ≥ 9 | ☐ |
| 8.5 | `model_plan` 필드 | role별 model 명시 | ☐ |
| 8.6 | `cross_model_result` (Verifier) | ✓ | ☐ |

---

## §9. 회귀 검증 (Regression, 3분)

> Main merge 후 기존 기능 깨짐 없는지

| # | 항목 | 검증 | PASS |
|---|---|---|:--:|
| 9.1 | `model_router.py` 기존 라우팅 동작 | 변경 후 정상 | ☐ |
| 9.2 | `langgraph_adapter.py` workflow | 정상 | ☐ |
| 9.3 | `cross_model_verifier.py` | 정상 | ☐ |
| 9.4 | `budget_guard.py` | 비용 가드 정상 | ☐ |
| 9.5 | `runtime.py` orchestration | 정상 | ☐ |
| 9.6 | `agent_model_guard.py` | model 매핑 정상 | ☐ |
| 9.7 | Marketing langgraph adapter | 정상 | ☐ |
| 9.8 | Memory governance report | `scripts/memory_governance_report.py` 실행 | ☐ |

---

## §10. 데모영상 사전 녹화 (15분)

| # | 항목 | 검증 | PASS |
|---|---|---|:--:|
| 10.1 | Case A 영상 길이 ≤ 2분 | 측정 | ☐ |
| 10.2 | Case B 영상 길이 ≤ 2분 | 측정 | ☐ |
| 10.3 | Case C 영상 길이 ≤ 2분 | 측정 | ☐ |
| 10.4 | Differentiator 6 (RAG 원문 ↗ 버튼 클릭) 강조 | 클릭 → law.go.kr 새 탭 열림 시연 | ☐ |
| 10.5 | Differentiator (Marketing rewrite) 강조 | "수정 적용" 클릭 시연 | ☐ |
| 10.6 | 전체 8분 분량 fit | ✓ | ☐ |
| 10.7 | UI 깨짐 / 에러 메시지 없음 | 화면 캡쳐 검토 | ☐ |
| 10.8 | 화면 녹화 audio 정상 | 음성 클리어 | ☐ |

---

## 실행 순서 (권장)

```
[5min]  §0 환경 검증 → 모두 PASS인지 확인 (FAIL이면 즉시 fix)
[8min]  §1 LLM Runtime (cost spike fix 검증)
[15min] §2 9-step workflow (Case A/B/C 각 1회)
[10min] §3 RAG ⭐ (사용자 핵심 요청)
[5min]  §4 6-agent board
[5min]  §5 Marketing rewrite
[7min]  §6 UI/React 6 tabs
[10min] §7 Demo Cases 사전 검증
[3min]  §8 Audit logs
[3min]  §9 회귀 검증
[15min] §10 데모영상 사전 녹화 (실제 화면)
─────────────────
Total: ~86분 (약 1.5시간)
```

## FAIL 처리 정책

| FAIL 영역 | 대응 |
|---|---|
| §0 환경 | 즉시 fix (서버 재시작, env 추가) — 영상 녹화 불가 |
| §1 LLM | 즉시 fix (config 점검) 또는 deterministic mode로 시연 |
| §3 RAG ⭐ | 즉시 fix (Qdrant 재기동, LAW_OPEN_API_KEY 확인) — 핵심 차별점 |
| §5 Marketing | 영상에서 해당 차별점 skip 결정 |
| §6 UI | 해당 탭 시연 회피 |
| §7 Demo Case | 다른 case로 대체 |

## 핵심 메모 (직전 세션 컨텍스트)

- **service_tier="default"**: $128 spike 재발 차단 (이전 priority tier 자동 사용 문제)
- **`_reasoning_effort_for_model`**: gpt-5 reasoning 모델 효율화 (main merge)
- **`_resolve_public_source_url`**: LAW_OPEN_API_KEY 활성 시 local:// → https://www.law.go.kr/... 변환
- **"원문 ↗" 버튼**: ReportView.tsx에서 외부 URL / 내부 기준 분기 적용 완료
- **CS_ENABLE_LLM_RUNTIME=1**: deterministic mode 비활성 — 실제 LLM 호출 활성

## 관련 파일

- `src/compliance_sentinel/llm_client.py` — LLM 호출 (cost fix + reasoning + service_tier)
- `src/compliance_sentinel/memory_rag.py` — RAG + URL 변환
- `compliance-sentinel/src/components/ReportView.tsx` — UI report 표시
- `audit_logs/compliance_audit.jsonl` — 감사 로그
- `audit_logs/llm_cost_ledger.jsonl` — LLM 비용 ledger
- `.env` — 환경변수 (CS_ENABLE_LLM_RUNTIME, LAW_OPEN_API_KEY, OPENAI_API_KEY)
