# Tasks — 금융 마케팅 콘텐츠 AI 심의관 재구축

> 상태값: todo / in_progress / done / deferred

## Phase A — Spec & Standards

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-001 | PDF 기반 PRD/spec 재작성 | done | spec.md가 콘텐츠 심의 중심으로 변경 |
| MT-002 | 구현 plan 재작성 | done | plan.md에 workflow/agent/data/eval 설계 포함 |
| MT-003 | task breakdown 재작성 | done | tasks.md에 Phase A-D 정의 |
| MT-004 | review standards YAML 작성 | done | 금지 표현/필수 고지/다국어 risk pack 포함 |
| MT-005 | 다국어 평가 샘플 작성 | done | en/zh/vi/ja/id 각 1건 이상 |

## Phase B — Core Engine

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-101 | marketing schema/dataclass 작성 | done | language/channel/product/finding/revision/export 타입 존재 |
| MT-102 | language detector 구현 | done | ko/en/zh/vi/ja/id 분류 |
| MT-103 | content/channel/product classifier 구현 | done | 광고 채널/상품 유형 분류 |
| MT-104 | rule-based checker 구현 | done | 금지 표현과 필수 고지 누락 탐지 |
| MT-105 | revision generator 구현 | done | finding별 안전 수정안 생성 |
| MT-106 | approval decision 구현 | done | APPROVED/APPROVE_WITH_CHANGES/REJECTED/HITL 산출 |
| MT-107 | workflow publisher mock 구현 | done | Slack/Notion payload 생성 |
| MT-108 | ComplianceState 호환 report 생성 | done | 기존 CLI/API/reporting과 호환 |

## Phase C — LangGraph & Runtime

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-201 | marketing_workflow 구현 | done | deterministic engine에서 콘텐츠 심의 수행 |
| MT-202 | marketing_langgraph_adapter 구현 | done | USE_LANGGRAPH=1에서 primary path 동작 |
| MT-203 | engine.py 기본 경로 전환 | done | analyze_with_engine이 marketing workflow 사용 |
| MT-204 | demo script 전환 | done | 마케팅 콘텐츠/다국어 중심 데모 |
| MT-205 | API/CLI JSON 호환 확인 | done | execution_engine 및 final_report 출력 |

## Phase D — Verification

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-301 | 마케팅 콘텐츠 unit tests 추가 | done | rule/language/revision/approval 검증 |
| MT-302 | 다국어 5개 샘플 tests 추가 | done | 각 언어 위험 표현 1개 이상 탐지 |
| MT-303 | PII audit/report leakage test | done | 원문 PII 미노출 |
| MT-304 | LangGraph CLI smoke | done | `USE_LANGGRAPH=1` 실행 성공 |
| MT-305 | 기존 test suite 회귀 | done | unittest discover 통과 |

## Phase L — 6-Board Persona Guideline Hardening

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-1201 | 6개 보드 persona별 profile 렌더링 | done | `board_member.md` placeholder가 live prompt에 남지 않고 역할별 focus/question/rule로 치환 |
| MT-1202 | 6개 보드 전용 Skill 주입 | done | Legal/PIPA/Consumer/Operational/Business/Contrarian 전용 Skill 파일 로드 |
| MT-1203 | 마케팅 workflow LLM advisory coverage 확장 | done | optional LLM advisory가 6개 보드 persona를 모두 포함 |
| MT-1204 | 회귀 테스트 | done | persona prompt, skill injection, advisory coverage 테스트 통과 |

## Phase K — Training-only Pi-to-Pi Peer Lab

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-1101 | local-only peer lab scaffold | done | `create-peer-lab`이 teacher/student/verifier/curator 프롬프트와 outputs 템플릿 생성 |
| MT-1102 | production decision path 격리 | done | manifest에 `production_decision_path=false`, network peer default false 기록 |
| MT-1103 | peer lab output 통합 | done | `integrate-peer-lab`이 `outputs/candidates.jsonl` 및 `outputs/expert-summary.md`를 기존 통합 경로로 처리 |
| MT-1104 | 안전한 Brain 통합 | done | memory는 pending→`--merge-patterns` 명시 merge만 허용 |
| MT-1105 | 회귀 테스트 | done | peer lab scaffold/integration 테스트 및 전체 회귀 통과 |

## Phase J — Independent Training Result Integration

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-1001 | 교사-학생/샌드박스 훈련 후보 JSONL 스키마 지원 | done | `target/text` 및 `target_store/lesson` alias 후보 import 가능 |
| MT-1002 | 훈련 결과를 Skill/RAG/Memory로 안전 staging | done | `approved=true`, `score >= min_score` 후보만 Skill/RAG/pending memory로 upsert |
| MT-1003 | 기존 Brain 학습 패턴 통합 옵션 | done | `--merge-patterns` 명시 시 `cs_brain.merge()`로 pending→Brain 통합 |
| MT-1004 | 중복 주입 방지 | done | archive/id 기반 중복 import, Skill/RAG upsert, Memory candidate_id 중복 staging 방지 |
| MT-1005 | 전문가 문서형 훈련 요약 통합 | done | `.md/.txt` 훈련 요약을 `knowledge_ingest` 경로로 dry-run/apply 가능 |
| MT-1006 | 보안 게이트 | done | secret-like token/prompt-injection 후보 reject, PII redaction 유지 |

## Phase I — Expert Knowledge Upload End-to-End Validation

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-901 | 전문가 지식 예시 문서 작성 | done | `docs/examples/expert-knowledge-upload-example.md`가 Skill/RAG/Memory 분배 후보를 모두 포함 |
| MT-902 | upload ingest dry-run/apply/idempotency 검증 | done | dry-run 분류, apply 저장, 중복 apply 0-write 확인 |
| MT-903 | Skill/RAG/Memory runtime effect 검증 | done | 생성 Skill 주입, RAG 검색, pending→brain merge, 런타임 memory/RAG finding 반영 확인 |
| MT-904 | PII/secret/trust gate 재검증 | done | 예시 문서 전화번호 redaction 및 raw PII 미노출 확인 |

## Phase H — Skill / Memory / RAG Quality Hardening

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-801 | Skill injection cache/status | done | role별 skill 로드 상태와 캐시를 진단 가능 |
| MT-802 | Qdrant readiness diagnostics | done | deps/env/deterministic/fallback 상태가 `qdrant_status`로 노출 |
| MT-803 | Offline RAG quality gates | done | grounded source coverage와 memory/RAG presence gate를 report에 포함 |
| MT-804 | RAG/skill/eval regression tests | done | 관련 테스트와 전체 회귀 통과 |

## Phase G — AgentCompiler-Independent Efficiency Improvements

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-701 | KB lookup/search precompute cache | done | LawKnowledgeBase가 article lookup/search tokens/coverage report를 재사용 |
| MT-702 | RAG/Qdrant retriever instance reuse + query cache | done | 동일 ComplianceMemoryRAG 인스턴스 반복 query에서 `rag_cache_hit=true` |
| MT-703 | single-request reusable deterministic agents | done | API/UI 단일 요청 경로도 process-local agent cache로 KB/RAG/model client 재사용 |
| MT-704 | lightweight profiling flag | done | `CS_PROFILE=1`에서 final_report.performance_profile 노출 |

## Phase F — Provider-Agnostic LLM Routing

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-601 | provider-agnostic model env 도입 | done | `CS_MODEL_SHALLOW/STANDARD/DEEP/CRITIC`로 OpenAI 외 provider 모델 설정 가능 |
| MT-602 | LLMClient multi-provider 호출 경로 | done | OpenAI, Anthropic, Google Gemini, OpenAI-compatible provider가 deterministic fallback과 함께 지원됨 |
| MT-603 | ModelGuard OpenAI-only pin 제거 | done | 역할별 tier/critic 격리는 유지하면서 provider별 모델 ID 허용 |
| MT-604 | Cross-model verifier provider 추상화 | done | `CS_MODEL_CRITIC` provider가 검증 경로에 사용됨 |

## Phase E — LangGraph / LangSmith Operational Hardening

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-501 | LangGraph checkpoint runtime helper | done | `CS_LANGGRAPH_CHECKPOINT=1`에서 thread_id 기반 checkpoint config 사용 |
| MT-502 | LangGraph human-review gate | done | 고위험/검증 불확실 케이스가 `human_review_gate.required=true`와 사유를 report에 노출 |
| MT-503 | LangSmith redacted trace export | done | `LANGSMITH_API_KEY` 설정 시 raw input 없이 redacted run summary만 best-effort export |
| MT-504 | LangSmith-ready regression eval | done | 외부 key 없이 로컬 eval 3건 통과, key 설정 시 redacted summary run 기록 |

## Phase M — Strengthened 3-Tool Governance Integration

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-1301 | portable sibling tool root resolver | done | AgentShield/AgentLoop/AgentCompiler root가 env 또는 Linux/WSL/macOS workspace sibling 경로로 자동 해석됨 |
| MT-1302 | AgentShield RuntimeGuard hot-path bridge | done | input/output/tool URL guard metadata가 final_report와 Slack live publish gate에 연결됨 |
| MT-1303 | AgentLoop observability/rollout artifacts | done | gate 실행 시 Langfuse/Phoenix-compatible observability export와 rollout decision artifact가 생성됨 |
| MT-1304 | AgentCompiler MCP trace/evidence gate artifact | done | MCP trace→ASG shadow artifact와 simulated evidence 차단 gate가 생성됨 |
| MT-1305 | governance dashboard | done | `reports/governance/three_tool_governance.{json,md}`가 security/lifecycle/shadow 상태를 집계함 |

## Phase N — Memory Governance Readiness Gate

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| MT-1401 | Koala 4-memory readiness report | done | `memory_governance_report.py`가 Working/Semantic/Procedural/Episodic 대응과 counts를 JSON으로 출력 |
| MT-1402 | unsafe memory blocker 탐지 | done | prompt-injection, raw PII, secret-like token, mutable active Brain pattern을 blocker로 보고 |
| MT-1403 | efficiency readiness 통합 | done | `efficiency_report.py`가 memory governance 결과와 penalty basis를 포함 |
| MT-1404 | 회귀 테스트/문서 | done | efficiency tooling 테스트와 README/architecture 문서 갱신 |

## Deferred

| ID | 작업 | 상태 | 조건 |
|---|---|---|---|
| MT-401 | OCR 이미지 배너 입력 | deferred | OCR dependency/샘플 이미지 확보 후 |
| MT-402 | 영상 STT 입력 | deferred | Whisper/Groq key 또는 로컬 STT 결정 후 |
| MT-403 | 실제 Slack/Notion API 쓰기 | deferred | 사용자 승인 및 secret 관리 확정 후 |
| MT-404 | JB 광고 100건 공개 데이터셋 | deferred | 공개 자료 수집/라벨링 완료 후 |
| MT-405 | 규제 변경 watcher | deferred | 1차 출처와 업데이트 주기 확정 후 |

## Definition of Done

- spec/plan/tasks가 콘텐츠 심의관 기준으로 정렬됨
- 기본 engine이 marketing content review report를 반환
- 한국어 + 5개 외국어 샘플 검증 통과
- provider-agnostic 모델 라우팅 유지
- PII 원문 미노출
- 전체 unittest 통과
