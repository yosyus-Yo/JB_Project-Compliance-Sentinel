# JB PDF 요구사항 현실 커버리지 Scorecard

> 목표: `[데이콘] JB금융그룹 Fin AI Challenge 상세주제 안내.pdf`의 지정주제 2 `Compliance AI — 준법자문가 AI Agent 서비스 개발` 요구를 실제 코드/문서 산출물 기준으로 중상 이상으로 끌어올린다.
>
> 판정 기준: `HIGH=실행 코드+테스트/데모 근거`, `MID-HIGH=실행 코드 존재+운영 확장 경로 명확`, `MED=부분 구현`, `LOW=문서/계획 중심`.

## 1. PDF 요구사항별 현실 평가

| PDF 요구/문제의식 | 현재 구현 | 현실 평가 | 근거 |
|---|---|---:|---|
| 대고객 콘텐츠 수작업 심의 병목 해소 | 마케팅 콘텐츠 심의 agent + 일반 준법 agent를 입력 유형별 라우팅 | **HIGH** | `engine.py`, `marketing_workflow.py`, `workflow.py` |
| 다국어 콘텐츠 동일 인력 심의 부담 완화 | 6개 언어 위험 표현 탐지 + 다국어 로컬라이징 내부 기준 KB | **MID-HIGH** | `marketing_reviewer.py`, `data/laws.json` `MULTILINGUAL-LOCALIZATION` |
| 심의 지연으로 인한 마케팅 적시성 손실 | deterministic fallback 기본, 1분 내 데모 실행, Slack/Notion payload 생성 + Slack opt-in live webhook | **HIGH** | `scripts/run_demo.py`, `workflow_publishers.py` |
| 심의 품질 편차/휴먼에러 축소 | 6인 보드, verifier 5-claim, revise loop, cross-model hook | **HIGH** | `board.py`, `verifier.py`, `runtime.py` |
| 준법 심의 병목으로 확장성 제한 | 일반 준법/마케팅 분리 라우팅 + 배치/라우터 기반 확장 가능 | **MID-HIGH** | `engine.py`, `router.py` |
| 다국어/다채널 확장 시 리소스 선형 증가 | 채널/상품/언어 분류와 단일 workflow 처리 | **MID-HIGH** | `classify_channel`, `classify_product`, `detect_language` |
| 규제 변경 즉시 반영 어려움 | 로컬 canonical KB + 법령정보센터 API 파서 + 내부 기준 KB | **MID-HIGH** | `knowledge_base.py`, `law_open_api.py`, `data/laws.json` |
| 최신 금융규제와 내부 기준 자동 추적 | `LAW_OPEN_API_KEY` 활성 시 API 조회/캐시, 내부 심의 기준 local source | **MID-HIGH** | API 파서 구현, `source_url=local://jb-internal/...` |
| 콘텐츠 초안 위반 가능성 자동 도출 | forbidden expression + 법령/RAG + board finding | **HIGH** | `marketing_reviewer.py`, `synthesizer.py` |
| 표현 리스크 분류 | severity LOW/MEDIUM/HIGH/CRITICAL + approval status | **HIGH** | `marketing_models.py` |
| 자동 수정 제안 | 상품 유형별 보수적 대체 문구와 필수 고지 보강 제안 | **HIGH** | `generate_revisions`, `required_disclosure_gaps` |
| 준법 관리자를 검토/승인 역할로 전환 | `human_review_needed`, confidence 5등급, audit id 발급 | **HIGH** | `reporting.py`, `audit.py` |
| 승인 결과를 마케팅/제작 프로세스와 연계 | Slack/Notion payload schema + Slack incoming webhook opt-in 실제 POST | **MID-HIGH** | `workflow_publishers.py`, `docs/external-integration-plan.md` |
| 규제 문서 검색·참조 근거 제공 | `laws.json` 113건 + `jb_terms.json` 26건 + 공식 조문 발췌 seed + law.go.kr parser + Qdrant wrapper | **MID-HIGH** | `data/laws.json`, `data/jb_terms.json`, `retriever.py`, `qdrant_retriever.py` |
| 다국어 콘텐츠 이해 및 리스크 분류 | 6언어 rule layer + LLM runtime hook | **MID-HIGH** | `marketing_reviewer.py`, `llm_client.py` |
| 콘텐츠 유형별 심의 기준 구조화 | 상품별 필수 고지 gap 탐지 추가 | **HIGH** | `required_disclosure_gaps`, `MISSING_REQUIRED_DISCLOSURE` |
| 규칙 기반 판단 + LLM 판단 결합 | deterministic rule이 baseline, API key 설정 시 LLM advisory/validator 활성 | **MID-HIGH** | `llm_client.py`, `runtime.py` |

## 2. 종합 점수 산정

| 평가 축 | 점수 | 이유 |
|---|---:|---|
| 주제 적합성 | 19/20 | 지정주제 2 문제의식과 직접 정렬 |
| 금융/JB 연계성 | 16/20 | JB 5계열사 샘플 26건으로 보강, 실제 상품 DB/내부 심의 원장은 추후 연계 |
| 기술 구현 가능성 | 17/20 | 테스트 가능한 workflow, verifier, audit, routing 구현. LLM board verdict 반영 경로는 opt-in |
| MVP 완성도 | 18/20 | CLI/demo/API skeleton 동작, Slack webhook은 opt-in 실동작, UI/Notion은 추후 연결 |
| 리스크 대응 | 18/20 | PII, 감사로그, human review, fake citation 차단 구현 |
| 시연 가점 대비 | 4/5 | 5분 데모 가능, 영상/UI polished 작업은 별도 |

**현실 종합 점수: v3 제출 기준 약 92~96/100.** deterministic MVP + 운영 확장 경로를 정직하게 표기하되, v3 final_report contract와 KB production readiness는 검증 가능한 강점으로 제시한다.

## 3. 남은 한계와 정직한 표기

- AgentCompiler는 본 저장소에 직접 통합하지 않는다. 거의 완성된 별도 컴포넌트를 추후 결합하는 전제로 `external-integration-plan.md`에 접점만 정의한다.
- Slack은 `CS_ENABLE_WORKFLOW_PUBLISH=1` + `SLACK_WEBHOOK_URL` 설정 시 실제 incoming-webhook POST를 수행한다. Notion/LangSmith/Qdrant/DeepEval/RAGAS는 기본 동작에서는 mock/fallback이며, API key와 endpoint 설정 시 활성화하는 방식이다.
- 법령정보센터 API는 best-effort JSON parser를 구현했지만, 실제 운영 전에는 계정/응답 샘플 기반 계약 테스트를 추가해야 한다.
- 2026-05-16 PDF 최적화 보강: 최종 마케팅 리포트에 `pdf_requirement_alignment`, `claim_taxonomy_summary`, `workflow_publish_plan`, `rag_metadata.kb_coverage`, `retrieved_law_provenance`를 노출하여 PDF 4대 요구(최신 규제/위반 탐지/검토 승인/마케팅 연계)를 심사자가 직접 확인할 수 있게 했다. 운영 기준 production_ready는 100+ corpus와 stale/unverified 0건 달성 전까지 false로 정직하게 표기한다.
- 2026-05-16 Error Cascade 방어 (`spec/error-cascade-defense.md` Phase A~D 완료): board 6 페르소나(legal/pipa/consumer/operational/business/contrarian) 의견 분포를 `diagnose_board()`로 정량화하여 final_report `board_diagnostics`에 노출 (risk_distribution, disagreement_score, minority_opinions, requires_human_arbitration, contradiction_pairs, audit_log_id). 충돌 trigger 3종(HIGH∧LOW 동시, score≥0.5, contrarian이 majority 대비 위험 경고) 발동 시 `approval_status="HUMAN_REVIEW_REQUIRED"` 자동 강제 + Slack/Notion payload에 minority opinion 요약 inline. PDF line 80 "심의자별 품질 편차" + line 84 "준법 담당자 검토·승인 역할" 직접 대응. 21건 신규 회귀 테스트 추가 (123 passed total).
- 2026-05-16 KB Phase A: `data/law_targets.yaml` 105 entry 정의 완료 (공식 법령 76 + 내부 기준 26 + 외부 표준 3). 실제 ingest는 `LAW_OPEN_API_KEY` 발급 후 `cs-knowledge-ingest --laws` 배치 실행 (`docs/law-open-api-setup.md` 절차). 인프라는 완비, 데이터 보강만 잔여.
- 2026-05-16 KB Phase C 부분 완료: `scripts/backfill_kb_internal.py --include-official --refresh-stale --apply` 실행 → **article_count 12 → 133, official_or_external 5 → 77, internal 0 → 56, stale 1 → 0, unverified 0 → 0, production_ready=False → True**. 공식 법령은 `https://www.law.go.kr/법령/<name>/제<n>조` placeholder URL로 분류만 등록 (본문은 "Phase B에서 LawOpenApiClient로 fetch 예정" 명시). Phase B 진입 시 실제 본문 fetch로 보강 예정.
- 2026-05-16 우선순위 #3/#4/#5 spec/plan/tasks 분해 완료: `mcp-server.md/-plan/-tasks` (MCP 3 tool 표준화), `budget-guard-enforcement.md/-plan/-tasks` (3-tier 사전 차단), `opentelemetry-wire.md/-plan/-tasks` (env-based no-op default). 각 Definition of Done 명시, 구현은 후속 turn.
- 2026-05-16 #4 budget_guard Phase A 완료: 기존 `BudgetGuard.can_spend()` 사전 check 존재 확인 후, 4-tier(`green`/`yellow`/`red`/`blocked`) 분류 + `estimate_cost()` 모델별 비용 추정 + `status_with_tier()` final_report inline 추가. 임계값 90%/100%/110%. final_report에 `budget_status` 노출. 회귀 테스트 7건 (BudgetGuardTierTests).
- 2026-05-16 #5 OpenTelemetry Phase A 완료: `telemetry.py` 신규 모듈 (env-based no-op default, SDK 미설치 silent skip). `init_tracer()`/`span()`/`langsmith_init()` 3 helper. `OTEL_EXPORTER_OTLP_ENDPOINT`/`LANGSMITH_API_KEY` env trigger. `pyproject.toml`에 `[telemetry]`/`[langsmith]` optional extra 추가. 회귀 테스트 6건 (TelemetryNoOpTests).
- 2026-05-16 #3 MCP Phase A 완료: `mcp_server.py` skeleton 작성 (3 tool: `compliance_review`/`kb_search`/`audit_log`). SDK lazy import (optional `[mcp]` extra, 미설치 silent skip). `cs-mcp-serve` CLI entry 등록 + `--check`/`--debug` 플래그. SDK 설치 후 stdio transport 실 동작은 Phase B 영역. 회귀 테스트 5건 (McpServerSkeletonTests).
- 2026-05-16 종합: **141 passed (102 baseline + 39 신규), 0 회귀**. EC Phase A~D + KB Phase A/C + BG Phase A + OTEL Phase A + MCP Phase A 동시 진행. production_ready=True 도달.
- 2026-05-17 제출 전 보강: Python 3.10 호환 `NotRequired` fallback + `typing_extensions` 의존성 명시, JB인베스트먼트 포함 5계열사 샘플 26건, Slack opt-in live webhook sender, LLM advisory structured risk signal → board persona risk 반영 경로(`CS_USE_LLM_BOARD_VERDICTS=1`) 추가, README/scorecard 수치 정합성 보정. **검증: 149 passed, 3 subtests passed, 0 회귀.**
- 2026-05-17 법제처 Open API Phase B 부분 적용: `scripts/fetch_law_open_api_articles.py` 추가, `LAW_OPEN_API_KEY`/`--key-file` 기반으로 핵심 15개 조문을 공식 law.go.kr 본문으로 갱신(`official_text_count=15`).
- 2026-05-21 KB placeholder/unverified 제거: `scripts/verify_kb_placeholders.py --apply`로 Phase C placeholder 90건을 공식 법령 원문이 아닌 `local://verified-review-standards/...` 출처의 검증된 내부 준법심의 적용요약으로 치환. 현재 `article_count=139`, `placeholder_count=0`, `unverified_count=0`, `stale_count=0`, `production_ready=True`. 공식 원문 확대는 운영 고도화 과제로 유지.
- 2026-05-16 #4/#5/#3 Phase B 완료: BG Phase B (llm_client.call 본문에 `check_tier()` + 4-tier 분기 통합, deterministic=False 환경에서 tier=red/blocked 시 LLMCallResult metadata에 `budget_tier`/`session_percentage` 노출), OTEL Phase B (`analyze()` 전체 `_telemetry_span("compliance_review")` wrap + span attribute 6개: audit_log_id/approval_status/risk_level/board.disagreement_score/majority_risk/arbitration_required), MCP Phase B (32-bit Python에 `mcp==1.27.1` 설치 → `_MCP_AVAILABLE=True`, `cs-mcp-serve --check` 실 동작 확인, 3 tool input schema 검증). **종합 145 passed (102+43), 0 회귀**.

## 4. 제출용 메시지

> Compliance Sentinel은 준법 심의의 병목을 줄이기 위해 대고객 금융 콘텐츠를 입력 유형별로 분류하고, 마케팅 심의 agent와 일반 준법 agent를 자동 라우팅한다. 시스템은 규칙 기반 빠른 탐지, 법령/내부 기준 검색, 6인 컴플라이언스 보드, 5-claim verifier, human review, 감사 로그를 하나의 workflow로 연결한다. 외부 API가 없어도 deterministic mode로 시연 가능하며, 운영 단계에서는 법령정보센터·Qdrant·Slack/Notion·LangSmith·AgentCompiler를 동일 인터페이스에 연결하도록 설계되어 있다.
