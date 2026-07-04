# 모듈화 단위 테스트 체크리스트 — 2026-05-29

> **대상**: `src/compliance_sentinel/` 47개 모듈 × `tests/unit/` 47개 테스트 파일
> **규모**: 1,149개 test 함수 (pytest 실행 시 parametrize 포함 약 1,160) · 커버리지 **86%**
> **실행 환경**: `deterministic_env` fixture (CS_ENABLE_LLM_RUNTIME=0, CS_DISABLE_QDRANT=1) — 외부 API/벡터DB 없이 동작
> **소스 브랜치**: `benchmark-aieev-2026-05-21` (커밋 f74bbb7)

---

## 사용법

- `[x]` = 단위 테스트 작성 완료 + 통과
- `[ ]` = 미작성 또는 보강 필요
- **test 수** = 해당 모듈 `def test_*` 함수 개수
- 새 기능 추가/수정 시 해당 모듈 행에 검증 항목 추가

---

## 1. 핵심 심의 엔진

| 모듈 | test 수 | 상태 | 핵심 검증 항목 |
|---|:---:|:---:|---|
| `workflow.py` | 19 | [x] | 9단계 파이프라인 순차 실행, 보드→synthesize→verify→validation 흐름 |
| `engine.py` | 36 | [x] | analyze_with_engine, 배치 처리, _AGENT_CACHE 재사용 |
| `runtime.py` | 30 | [x] | turbo/balanced/strict 프로파일, LLM 게이팅, quality-first 라우팅 |
| `board.py` | 26 | [x] | 6인 보드 deterministic 판정, diagnose_board, 모순/중재 트리거 |
| `synthesizer.py` | 18 | [x] | CEO draft 합성, finding 생성, user citation 통합 |
| `verifier.py` | 43 | [x] | atomic claim 추출, KB 검증, FAIL/PARTIAL 차등, revise 루프 |
| `classification.py` | 10 | [x] | 입력 타입/언어/채널/상품 분류 |

## 2. LLM / 모델 라우팅

| 모듈 | test 수 | 상태 | 핵심 검증 항목 |
|---|:---:|:---:|---|
| `llm_client.py` | 43 | [x] | deterministic fallback, provider 분기(OpenAI/Anthropic/Google), budget 차단 |
| `model_router.py` | 24 | [x] | 역할별 모델 선택, tier 라우팅, deterministic 모드 |
| `budget_guard.py` | 22 | [x] | per_demo/monthly 한도, 4-tier(green/yellow/red/blocked), 비용 추정 |
| `cross_model_verifier.py` | 10 | [x] | cross-model 독립 검증, STRONG/NONE 레벨 |
| `agent_model_guard.py` | 14 | [x] | 역할별 tier/critic route pin, 위반 시 RuntimeError |

## 3. LangGraph 통합

| 모듈 | test 수 | 상태 | 핵심 검증 항목 |
|---|:---:|:---:|---|
| `langgraph_adapter.py` | 14 | [x] | build_graph().invoke(), 노드별 동작, USE_LANGGRAPH toggle |
| `langgraph_runtime.py` | 29 | [x] | env flag 파싱, deterministic ID, checkpoint 옵션 |
| `marketing_langgraph_adapter.py` | 11 | [x] | 마케팅 그래프 invoke, intake/understand 노드, runtime metadata |

> ✅ 2026-05-29 실측: 54/54 통과 (0.91s), skip 0건. 외부 mock 데이터 불필요 — `langgraph_env` fixture(환경변수 toggle)로 동작.

## 4. 학습 / Brain

| 모듈 | test 수 | 상태 | 핵심 검증 항목 |
|---|:---:|:---:|---|
| `learning_lab.py` | 85 | [x] | 패턴 학습 루프, ablation, CLI 서브커맨드 |
| `cs_brain.py` | 56 | [x] | 패턴 저장/검색, ablation report |
| `memory_rag.py` | 25 | [x] | recall, retrieve_context, capture_outcome |

## 5. 마케팅 심의

| 모듈 | test 수 | 상태 | 핵심 검증 항목 |
|---|:---:|:---:|---|
| `marketing_reviewer.py` | 52 | [x] | 마케팅 콘텐츠 심의 코어, rewriter |
| `marketing_workflow.py` | 17 | [x] | 마케팅 워크플로우 단계 |
| `marketing_models.py` | 4 | [x] | 마케팅 데이터 모델 |

## 6. 지식 / RAG

| 모듈 | test 수 | 상태 | 핵심 검증 항목 |
|---|:---:|:---:|---|
| `knowledge_ingest.py` | 48 | [x] | 법령 수집/파싱/인덱싱 |
| `knowledge_base.py` | 8 | [x] | LawKnowledgeBase, get_article |
| `retriever.py` | 4 | [x] | 법령 검색 |
| `qdrant_retriever.py` | 11 | [x] | 벡터 검색 (CS_DISABLE_QDRANT mock) |
| `citation_extractor.py` | 5 | [x] | 명시적 법령 인용 추출 |

## 7. 입출력 / 리포트

| 모듈 | test 수 | 상태 | 핵심 검증 항목 |
|---|:---:|:---:|---|
| `multimodal_input.py` | 40 | [x] | PDF/DOCX/XLSX/RTF/HTML/HWPX/OCR 7형식 추출, 인코딩 fallback |
| `pii.py` | 15 | [x] | RRN/카드/전화/이메일/계좌 마스킹, first-match 순서 |
| `reporting.py` | 17 | [x] | 최종 리포트 빌드, pii_findings 노출 |
| `report_schema.py` | 9 | [x] | v2 스키마 검증 |
| `audit.py` | 13 | [x] | 감사 로그 기록, audit_id 발급 |
| `guardrails.py` | 10 | [x] | disclaimer 보장 |
| `content_standards.py` | 5 | [x] | 콘텐츠 표준 검증 |

## 8. 인프라 / 연동

| 모듈 | test 수 | 상태 | 핵심 검증 항목 |
|---|:---:|:---:|---|
| `agent_shield_bridge.py` | 59 | [x] | 에이전트 권한 가드, exec approval |
| `law_open_api.py` | 51 | [x] | 법령 Open API 연동 (urllib mock) |
| `ui_settings.py` | 45 | [x] | UI 설정 로드/검증 |
| `telemetry.py` | 32 | [x] | 텔레메트리 수집 |
| `eval_metrics.py` | 33 | [x] | 평가 지표 산출 |
| `mcp_server.py` | 21 | [x] | MCP 서버 엔드포인트 |
| `api.py` | 24 | [x] | FastAPI worker (/analyze, /review, /batch) |
| `cli.py` | 13 | [x] | CLI 서브커맨드 |
| `models.py` | 16 | [x] | 데이터 모델(ComplianceState, BoardOpinion 등) |
| `langsmith_eval.py` | 6 | [x] | LangSmith 평가 연동 |
| `skill_injection.py` | 5 | [x] | 스킬 컨텍스트 주입 |
| `workflow_publishers.py` | 7 | [x] | 워크플로우 발행 |
| `smoke_imports.py` | 11 | [x] | 전체 모듈 import smoke test |

---

## 9. 통합 테스트 (별도 — tests/integration/)

| 항목 | 상태 | 비고 |
|---|:---:|---|
| VCR cassette 인프라 | [x] | API key 마스킹(Authorization/api-key/x-api-key) |
| `test_llm_client_live.py` | [x] | live OpenAI/Anthropic (CS_ENABLE_LLM_RUNTIME=1 게이트) |
| `test_llm_client_vcr.py` | [x] | cassette 재생 |
| `test_qdrant_live.py` | [x] | live Qdrant |
| `test_langsmith_live.py` | [x] | live LangSmith |

> 평소 skip, `CS_ENABLE_LLM_RUNTIME=1` 환경에서만 실행. prod 코드 0줄 변경.

---

## 10. 미보강 / 후속 후보 (체크리스트 갭)

E2E 테스트(2026-05-29)에서 발견된 결함과 연결되는 단위 테스트 갭:

- [ ] **D2 회귀**: `board.py` 다국어 위험표현 탐지(영문/중문/베트남어) 단위 테스트 — 현재 consumer_expert 한국어 키워드만
- [ ] **D2 회귀**: `board.py` business_practicality/contrarian 동적 risk 반영 테스트 — 현재 항상 MEDIUM 하드코딩
- [ ] **D1 회귀**: budget_guard 요청 간 격리(재사용 인스턴스 session 누적 방지) 테스트
- [ ] **D4 회귀**: PII `pii_detected` 플래그와 실제 마스킹 동기화 테스트 + 인명 마스킹
- [ ] `pii.py` 2.3~2.6: Amex 카드/전화/이메일/계좌 패턴 실입력 테스트 (현재 일부 ⚠️ 미테스트)

---

## 검증 수준

| 주장 | 수준 | 근거 |
|---|:---:|---|
| 47 모듈 / 1,149 test 함수 | [검증됨] | benchmark 브랜치 `git show` + `grep -c "def test_"` 실측 |
| LangGraph 54/54 통과 | [검증됨] | 2026-05-29 `pytest` 직접 실행 |
| 86% 커버리지 | [추정] | 이전 세션(2026-05-29) 측정, 본 문서 작성 시 재측정 안 함 |
| §10 갭 항목 | [검증됨] | E2E 리포트 D1·D2·D4 + test-results-2026-05-28 §2 ⚠️ 항목 cross-check |
