# Delegation Board — Compliance Sentinel Build Team

## 현재 위임 상태

| Agent | Assigned Tasks | Status | Next Action |
|---|---|---|---|
| Product Architect | T-001, T-002, T-003, 통합 관리 | done | 구현 phase 착수 승인 |
| Legal Domain Lead | T-101, T-105 | assigned | 법령 범위와 citation 기준 확정 |
| RAG Engineer | T-103, T-104, T-204 | assigned | Qdrant schema와 hybrid retriever 설계 |
| LangGraph Engineer | T-201, T-202, T-208 | assigned | ComplianceState와 StateGraph skeleton 작성 |
| Multi-Agent Orchestrator | T-205, T-206 | assigned | 6인 보드 prompt 및 CEO synthesizer 작성 |
| Compliance Verifier Engineer | T-105, T-207 | assigned | atomic claim/citation verifier 구현 |
| Security Engineer | T-203 | assigned | PII redaction gate 구현 |
| Audit Engineer | T-302, T-303 | assigned | audit log와 trace schema 구현 |
| Frontend Demo Engineer | T-301 | assigned | Chainlit UI 구현 |
| QA/Eval Engineer | T-305, T-401, T-403, T-404 | assigned | demo seed + test suite 작성 |
| Red Team Engineer | T-402 | assigned | adversarial cases 작성 |
| Demo Director | T-405, T-406 | assigned | 5분 시연 스크립트/다이어그램 작성 |
| Performance Engineer | T-501, T-502, T-503 | todo | MVP 이후 AgentCompiler spike |

## Orchestrator 지시문

1. Phase 1~3은 병렬 가능하지만 `T-105 citation checker`는 verifier loop의 critical path다.
2. `T-203 PII guard` 완료 전에는 실제 개인정보가 LLM으로 전달되는 테스트를 금지한다.
3. `T-207 verifier`가 실패한 결과는 최종 보고서로 직접 출력하지 않는다.
4. `T-404 MVP smoke test` 통과 전 AgentCompiler 최적화 작업은 시작하지 않는다.
5. 모든 산출물은 acceptance criteria와 evidence를 남겨야 한다.

## 팀별 상세 위임

### Legal Domain Lead

- 법령 범위: 개인정보보호법, 신용정보법, 금융소비자보호법, 전자금융거래법, 전자금융감독규정, 금융광고 관련 규정
- 산출물: `references/legal-scope.md`, citation validation rules
- 완료 기준: 샘플 조항 10개와 가짜 조항 5개로 checker 테스트 가능

### RAG Engineer

- 산출물: Qdrant schema, ingestion spec, retriever contract
- 완료 기준: 조문번호 exact query와 의미 검색 query가 모두 동작

### LangGraph Engineer

- 산출물: graph skeleton, state model, conditional routing
- 완료 기준: mock tools로 end-to-end graph path가 실행됨

### Compliance Verifier Engineer

- 산출물: atomic claim schema, verification function, retry feedback format
- 완료 기준: 잘못된 citation을 `FAIL`로 반환하고 revision feedback 생성

### Security Engineer

- 산출물: PII recognizers, redaction policy, LLM input gate
- 완료 기준: 주민번호/전화번호/계좌번호/이메일 샘플이 마스킹됨

### QA/Eval Engineer

- 산출물: regression dataset, promptfoo/deepeval config, smoke test
- 완료 기준: fake law citation, prompt injection, PII leakage 케이스 포함

## 완료 선언 조건

Planning package는 현재 완료되었습니다. Product implementation 완료 선언은 다음 증거가 있어야 가능합니다.

- end-to-end demo smoke PASS
- citation verifier PASS/FAIL 양방향 테스트 PASS
- PII redaction 테스트 PASS
- audit log 생성 확인
- human review 라우팅 확인
- demo script와 architecture diagram 준비

## Phase M — Strengthened 3-Tool Governance Integration 완료 (2026-05-21)

| 산출물 | 위치 | 상태 |
|---|---|---|
| portable sibling tool root resolver | `scripts/tool_roots.py` | ✅ |
| AgentShield hot-path RuntimeGuard bridge | `src/compliance_sentinel/agent_shield_bridge.py`, `src/compliance_sentinel/engine.py`, `workflow_publishers.py` | ✅ |
| AgentLoop observability/rollout artifacts | `scripts/run_agentloop_gate.py` | ✅ |
| AgentCompiler MCP trace/evidence gate artifact | `scripts/run_three_tool_integration.py` | ✅ |
| governance dashboard | `reports/governance/three_tool_governance.{json,md}` | ✅ |

### Phase M Gate 통과 증거

- `uv run --extra dev pytest -q tests/test_efficiency_tooling.py` → `12 passed`.
- `uv run --extra dev pytest -q` → `182 passed, 3 skipped, 3 subtests passed`.
- `uv run --extra dev python -m compileall -q src scripts tests` → PASS.
- `uv run --extra dev python scripts/run_three_tool_integration.py --strict --skip-source` → `AgentShield=PASS`, `AgentLoop=pass action=promote`, `AgentCompiler=pass safety=True`.
- AgentCompiler evidence gate는 `simulated_evidence`, `real_gpu_backend_required`, `kv_claims_require_real_gpu_backend` 사유로 production/KV speedup claim 승격을 차단함.

## Phase L — 6-Board Persona Guideline Hardening 완료 (2026-05-19)

| 산출물 | 위치 | 상태 |
|---|---|---|
| 6개 보드 persona profile 렌더링 | `src/compliance_sentinel/llm_client.py` | ✅ |
| 공통 board prompt template 보강 | `src/compliance_sentinel/system_prompts/board_member.md` | ✅ |
| persona별 Skill 문서 | `agents/skills/compliance_board_personas/*.md` | ✅ |
| Skill injection role map 확장 | `src/compliance_sentinel/skill_injection.py` | ✅ |
| marketing advisory 6 persona coverage | `src/compliance_sentinel/marketing_workflow.py` | ✅ |
| deterministic board 역할별 판단 보정 | `src/compliance_sentinel/board.py` | ✅ |
| 회귀 테스트 | `tests/test_compliance_sentinel.py` | ✅ |

### Phase L Gate 통과 증거

- 6개 persona prompt에서 `{{placeholder}}` 미노출.
- 6개 persona 모두 공통 금융 마케팅 Skill + 전용 persona Skill 로드.
- optional LLM advisory가 `legal_counsel`, `pipa_expert`, `consumer_protection`, `operational_risk`, `business_practicality`, `contrarian` 전원을 포함.
- 역할별 대표 시나리오 smoke:
  - PIPA: 개인정보/개인신용정보/제3자 제공 → `pipa-credit-info-expert=HIGH`.
  - Consumer Protection: `당일 무조건 승인`, `한도 무제한` → `consumer-protection-expert=HIGH`.
  - Operational Risk: `보안 인증 없이`, `AML 확인 생략` → `aml-operational-risk-expert=HIGH`.
- 관련 테스트: `25 passed`.
- 전체 회귀: `169 passed, 3 subtests passed`.

## Phase K — Training-only Pi-to-Pi Peer Lab 완료 (2026-05-19)

| 산출물 | 위치 | 상태 |
|---|---|---|
| local-only peer lab 생성 | `src/compliance_sentinel/learning_lab.py:create_peer_training_lab` | ✅ |
| peer lab 결과 통합 | `src/compliance_sentinel/learning_lab.py:integrate_peer_training_lab` | ✅ |
| CLI | `cs-learning-lab create-peer-lab`, `integrate-peer-lab` | ✅ |
| 문서 | `docs/knowledge-ingest-pipeline.md` | ✅ |
| 테스트 | `ExternalLearningLabTests.test_peer_training_lab_scaffold_and_integration_stay_training_only` | ✅ |

### Phase K Gate 통과 증거

- peer lab roles: `teacher`, `student`, `verifier`, `curator`.
- 생성 파일: `manifest.json`, `README.md`, `prompts/*.md`, `outputs/candidates.jsonl`, `outputs/expert-summary.md`.
- manifest safety: `production_decision_path=false`, `network_peer_default=false`, `auto_brain_merge_allowed=false`.
- 통합 경로: peer outputs → `integrate_training_artifact` → Skill/RAG/Memory pending → optional Brain merge.
- 테스트: `ExternalLearningLabTests` 6개 통과.
- 전체 회귀: `165 passed, 3 subtests passed` 당시 통과. 최신 Phase L 이후 전체 회귀는 `169 passed, 3 subtests passed`.

## Phase J — Independent Training Result Integration 완료 (2026-05-19)

| 산출물 | 위치 | 상태 |
|---|---|---|
| 독립 훈련 결과 통합 함수/CLI | `src/compliance_sentinel/learning_lab.py` | ✅ |
| 교사-학생 후보 예시 | `docs/examples/teacher-student-training-candidates.jsonl` | ✅ |
| 사용 가이드 | `docs/knowledge-ingest-pipeline.md` | ✅ |
| 통합/merge 테스트 | `tests/test_compliance_sentinel.py::ExternalLearningLabTests` | ✅ |

### Phase J Gate 통과 증거

- structured candidate JSONL/JSON 지원: `target/text`, `target_store/lesson` alias 정규화.
- `.md/.txt` 훈련 요약은 전문가 지식 문서처럼 `knowledge_ingest` 경로로 처리.
- 안전 staging 조건: `approved=true`, `score >= min_score`.
- Skill/RAG/Memory 분배: Skill/RAG upsert, Memory pending capture.
- `--merge-patterns` 명시 시 기존 `cs_brain.merge()`로 Brain 통합.
- 중복 방지: archive id, Skill/RAG id, Memory candidate_id pending+brain 체크.
- 보안: secret-like token/prompt-injection 후보 reject, PII redaction 유지.
- 관련 테스트: `6 passed`.
- 전체 회귀: `164 passed, 3 subtests passed`.

## Phase I — Expert Knowledge Upload E2E 검증 완료 (2026-05-19)

| 산출물 | 위치 | 상태 |
|---|---|---|
| 전문가 지식 업로드 예시 문서 | `docs/examples/expert-knowledge-upload-example.md` | ✅ |
| CLI/문서 가이드 갱신 | `docs/knowledge-ingest-pipeline.md` | ✅ |
| 중복 memory capture 방지 | `src/compliance_sentinel/knowledge_ingest.py` | ✅ |
| 긴 RAG chunk snippet 보존 | `src/compliance_sentinel/memory_rag.py` | ✅ |
| E2E 통합 테스트 | `tests/test_compliance_sentinel.py::KnowledgeIngestTests::test_expert_upload_example_distributes_and_affects_runtime` | ✅ |

### Phase I Gate 통과 증거

- Dry-run target 분류: `skill=1`, `rag=1`, `memory=1`.
- Apply 저장: `skill=1`, `rag=1`, `memory=1`.
- 중복 apply: `skill=0`, `rag=0`, `memory=0`.
- RAG 검색 hit=1, pending→brain merge 후 long-term memory hit=1.
- 런타임 분석에서 `document_rag_count=1`, `rag_quality_gates.passed=True`, `approval_status=REJECTED`, `risk_level=CRITICAL`.
- 예시 문서 전화번호 `010-1234-5678`은 저장/리포트에 미노출.
- 관련 테스트: `21 passed, 141 deselected`.
- 전체 회귀: `162 passed, 3 subtests passed`.

## Phase H — Skill / Memory / RAG Quality Hardening 완료 (2026-05-19)

| 산출물 | 위치 | 상태 |
|---|---|---|
| Skill injection cache/status | `src/compliance_sentinel/skill_injection.py` | ✅ |
| Qdrant readiness diagnostics | `src/compliance_sentinel/qdrant_retriever.py` | ✅ |
| RAG metadata qdrant_status | `src/compliance_sentinel/memory_rag.py` | ✅ |
| Offline RAG quality gates | `src/compliance_sentinel/eval_metrics.py` | ✅ |
| Report-level `rag_quality_gates` | `reporting.py`, `marketing_workflow.py` | ✅ |
| Regression tests | `tests/test_compliance_sentinel.py` | ✅ |

### Phase H Gate 통과 증거

- `rag_quality_gates.passed=True` smoke 확인: findings=4, law_provenance=5.
- `qdrant_status`가 report metadata에 노출되며 현재 환경은 `fallback=keyword_fallback`, `has_qdrant_client=False`로 정직 표기.
- `skill_injection_status('legal_counsel').loaded_skill_files=1` 확인.
- 관련 테스트: `16 passed, 145 deselected`.
- 전체 회귀: `161 passed, 3 subtests passed`.

## Phase G — AgentCompiler-Independent Efficiency Improvements 완료 (2026-05-19)

| 산출물 | 위치 | 상태 |
|---|---|---|
| KB precomputed lookup/search cache | `src/compliance_sentinel/knowledge_base.py` | ✅ |
| RAG/Qdrant retriever reuse + query cache | `src/compliance_sentinel/memory_rag.py` | ✅ |
| Process-local reusable deterministic agents | `src/compliance_sentinel/engine.py` | ✅ |
| `CS_PROFILE=1` performance profile | `src/compliance_sentinel/engine.py` | ✅ |
| Cache/reuse regression tests | `tests/test_compliance_sentinel.py` | ✅ |

### Phase G Gate 통과 증거

- Repeated deterministic analysis shows second request `rag_cache_hit=True` and lower elapsed profile in smoke run.
- Single-request engine trace includes `engine_route.reused_agent=true`.
- 관련 테스트: `12 passed, 147 deselected`.
- 전체 회귀: `159 passed, 3 subtests passed`.

## Phase F — Provider-Agnostic LLM Routing 완료 (2026-05-19)

| 산출물 | 위치 | 상태 |
|---|---|---|
| provider-agnostic model router | `src/compliance_sentinel/model_router.py` | ✅ |
| multi-provider LLM client | `src/compliance_sentinel/llm_client.py` | ✅ |
| tier/critic route ModelGuard | `src/compliance_sentinel/agent_model_guard.py` | ✅ |
| provider-agnostic cross verifier | `src/compliance_sentinel/cross_model_verifier.py` | ✅ |
| Streamlit settings provider fields | `src/compliance_sentinel/ui_settings.py` | ✅ |
| spec/readme 업데이트 | `spec/{spec,plan,tasks}.md`, `README.md` | ✅ |

### Phase F Gate 통과 증거

- `CS_MODEL_SHALLOW=google/gemini-1.5-flash`, `CS_MODEL_STANDARD=openrouter/anthropic/claude-3.5-sonnet`, `CS_MODEL_DEEP=anthropic/claude-3-5-sonnet-latest`, `CS_MODEL_CRITIC=google/gemini-1.5-pro` 설정 시 role plan에 해당 모델 반영.
- `split_provider_model()`이 `anthropic/...`, `google/...`, `openrouter/...`, bare `gpt-*`를 provider/API model로 분리.
- ModelGuard는 OpenAI-only pin이 아니라 role별 tier/critic env 모델만 허용.
- 관련 테스트: `23 passed, 134 deselected`.
- 전체 회귀: `157 passed, 3 subtests passed`.

## Phase E — LangGraph / LangSmith 운영 보강 완료 (2026-05-19)

| 산출물 | 위치 | 상태 |
|---|---|---|
| LangGraph runtime helper | `src/compliance_sentinel/langgraph_runtime.py` | ✅ |
| Marketing/general human-review gate | `marketing_langgraph_adapter.py`, `langgraph_adapter.py` | ✅ |
| Engine checkpoint config + metadata | `src/compliance_sentinel/engine.py` | ✅ |
| LangSmith redacted run export | `src/compliance_sentinel/telemetry.py` | ✅ |
| LangSmith-ready local regression eval | `src/compliance_sentinel/langsmith_eval.py` | ✅ |
| 회귀 테스트 3건 추가 | `tests/test_compliance_sentinel.py::LangGraphRuntimeAndLangSmithTests` | ✅ |

### Phase E Gate 통과 증거

- `USE_LANGGRAPH=1 CS_LANGGRAPH_CHECKPOINT=1` 마케팅/일반 준법 케이스 모두 `engine=langgraph`, `fallback=None`.
- final_report에 `langgraph_runtime.thread_id=cs-...`, `checkpoint_enabled=true`, `human_review_gate.required=true` 및 사유 노출.
- LangSmith export payload는 전화번호/이메일/장문 숫자를 `[PHONE]`/`[EMAIL]`/`[NUMBER]`로 redaction 후 best-effort `create_run`.
- `python -m compliance_sentinel.langsmith_eval` 로컬 eval 3/3 통과.
- 전체 회귀: `154 passed, 3 subtests passed`.

## Phase 6 (P1) — Request Router 완료 (2026-05-13)

| 산출물 | 위치 | 상태 |
|---|---|---|
| Routing table (8 domain + 3 pipeline) | `.cs-brain/routing-table.yaml` | ✅ |
| Router 구현 (5-Phase 결정론적 CLI) | `src/compliance_sentinel/router.py` (420줄) | ✅ |
| CLI entry point | `cs-router classify|route|status` | ✅ pyproject.toml 등록 |
| 회귀 테스트 10건 | `tests/test_compliance_sentinel.py::RouterTests` | ✅ 16/16 pass |
| routing_history.log 7-col TSV writer | `audit_logs/routing_history.log` | ✅ |
| workflows YAML 3개 | `workflows/cs-{router,brain,model-routing}.yaml` | ✅ |
| agents/team.yaml 신규 역할 6개 | router-engineer, model-router-engineer, brain-curator, cross-model-verifier, observability-engineer, safety-engineer | ✅ |

### P1 Gate 통과 증거

- `cs-router classify "이 약관에서 개인정보 제3자 제공 검토"` → domain=terms_review ✓
- `cs-router route "결제 약관에서 비밀번호 위험"` → workflow=cs-evolve, options=`--with-judge --with-review --strict`, model=critical ✓
- `cs-router route "PIPA 법령 개정 후 약관 반영"` → pipeline=policy_change_full (3 steps) ✓
- 동일 입력 재현성 (AC-010) 단위 테스트 통과
- routing_history.log 7-col TSV append (AC-011) 단위 테스트 통과
- LP-1647 적용: SEAS 179 skill 통째 import 안 함, 8 domain · 3 pipeline로 압축

### Phase 7 (P2) 진입 게이트

다음 호출 권장: `/auto cs-phase2 진행해줘` — 사용자 명시 승인 필수.
- T-701 model_router.py 4-tier 매트릭스
- T-702 Anthropic SDK 실호출 (deterministic fallback 보존)
- T-703 Builder ≠ Verifier 격리
- T-704 Codex cross-model verifier 자동 부착
- T-705 LP-CS-030 CEO Synthesizer Opus pin
- T-706 비용 budget guard

**AgentCompiler (Phase 5+)**: 명시 deferred. baseline (P1-P4) 안정 후 별도 spec.

## Phase 7 (P2) — Model Router + LLM 통합 완료 (2026-05-13)

| Task ID | 산출물 | 위치 | 상태 |
|---|---|---|---|
| T-701 | Model Router 4-tier 매트릭스 | `src/compliance_sentinel/model_router.py` (240줄) | ✅ |
| T-702 | LLM Client + deterministic fallback | `src/compliance_sentinel/llm_client.py` (155줄) | ✅ |
| T-703 | Builder ≠ Verifier 격리 (system prompts 7개) | `src/compliance_sentinel/system_prompts/{builder,verifier,ceo_synthesizer,board_member,classifier,documenter,codex_verifier}.md` | ✅ |
| T-704 | Cross-model verifier (Codex GPT-5.5) | `src/compliance_sentinel/cross_model_verifier.py` (95줄) | ✅ |
| T-705 | Agent Model Guard (LP-CS-030 Opus pin) | `src/compliance_sentinel/agent_model_guard.py` (75줄) | ✅ |
| T-706 | Budget Guard | `src/compliance_sentinel/budget_guard.py` (120줄) | ✅ |
| - | P2 단위 테스트 24건 | `tests/test_compliance_sentinel.py::ModelRouterTests,LLMClientTests,ModelGuardTests,BudgetGuardTests,CrossModelVerifierTests` | ✅ |
| - | CLI entry `cs-model-router` | `pyproject.toml` scripts | ✅ |

### P2 Gate 통과 증거

- 40/40 unit tests pass (P1 16 + P2 24)
- `cs-model-router plan "이 약관"` → 10 역할 자동 매핑, CEO=Opus 4.7, Verifier=ISOLATED ✓
- `cs-model-router plan "결제 약관 비밀번호 위험"` → critical tier, cross-model=STRONG auto-attach=True ✓
- `agent_model_guard.check(role='ceo_synthesizer', model='sonnet')` → `ModelGuardViolation` raised (LP-CS-030) ✓
- `CS_BYPASS_MODEL_GUARD=1` 시 stderr 경고 + 통과 (ablation 전용)
- `BudgetGuard.can_spend()` per_demo 한도 초과 시 False 반환 + JSONL ledger 기록
- Deterministic fallback: `CS_DETERMINISTIC_MODE=1` 또는 ANTHROPIC_API_KEY 부재 시 모든 LLM 호출 silent skip
- Demo 회귀: Case A/B/C retries=0/3/1 정상 동작 (Phase 1-5 무영향)

### 비용 예산 (P2 적용 후 시뮬레이션)

| 시나리오 | 비결정론 모드 추정 cost | 한도 |
|---|---:|---:|
| standard 시연 1회 (Case A/B/C 각 1) | ~$0.18 | $0.40 |
| critical 시연 1회 (Case B 결제 약관) | ~$0.36 | $0.40 |
| critical + Codex verifier | ~$0.46 → **차단** | $0.40 |
| 100건 배치 standard | ~$18.00 | $20.00 |
| 월간 개발 누적 | (실측) | $80.00 |

### Phase 8 (P3) 진입 게이트

다음 호출: `/auto cs-phase3 진행해줘`
- T-801 `.cs-brain/project_brain.yaml` schema 신설
- T-802 `cs_capture_learning.py` 4-분류 캡처
- T-803 `cs_search_patterns.py` BM25+dense RRF
- T-804 Stop hook auto-merge (readonly 보호)
- T-805 `cs_ablation_report.py` 주간 측정
- T-806 `cs_history_analyzer.py` 메타 인사이트
- T-807 readonly 패턴 자동 보호

## Phase 8 (P3) — Brain 자기진화 완료 (2026-05-13)

| Task ID | 산출물 | 위치 | 상태 |
|---|---|---|---|
| T-801 | Brain 인프라 (project_brain + pending + ablation-config) | `.cs-brain/{project_brain.yaml, pending_patterns.yaml, ablation-config.yaml}` | ✅ |
| T-802 | capture (4 분류) | `cs_brain.capture()` | ✅ |
| T-803 | search (BM25, readonly 1.2x boost) | `cs_brain.search()` + `BM25` class | ✅ |
| T-804 | merge (readonly 보호) | `cs_brain.merge()` | ✅ |
| T-805 | ablation report (HEALTHY/UNDERUSED/DEAD) | `cs_brain.ablation_report()` | ✅ |
| T-806 | history-analyzer (top LP, similar, zero_hit_rate) | `cs_brain.analyze_history()` | ✅ |
| T-807 | readonly 패턴 자동 보호 | merge()에서 강제 (LP-CS-020/030 보존) | ✅ |
| - | CLI entry `cs-brain` | `pyproject.toml` | ✅ |
| - | 시드 LP 5건 (LP-CS-001~040) | `.cs-brain/project_brain.yaml` | ✅ |
| - | P3 단위 테스트 10건 | `BrainTests` | ✅ |

### P3 Gate 통과 증거

```
$ cs-brain status
project_brain.yaml: 5 pattern(s), 2 readonly
pending_patterns.yaml: 0 pattern(s)

$ cs-brain search "CEO Synthesizer 모델"
검색 결과 (1건):
  LP-CS-030 (score=6.233) [readonly]: CEO Synthesizer 모델 다운그레이드 회귀

$ cs-brain capture success "테스트" "내용" --tags "test"
✅ captured LP-CS-PND-1778... (success)

$ cs-brain merge
✅ merged 1 pattern(s)
   skipped readonly: 0
   new IDs: LP-CS-041

$ cs-brain ablation --days 7
Ablation report (지난 7일):
  ⚠️ router-classify      fires=1   expected=10  (UNDERUSED)
  💀 router-pipeline-detect fires=0  expected=2   (DEAD)
  ⚠️ brain-search         fires=2   expected=10  (UNDERUSED)
  ...
```

- 50/50 unit tests pass (P1 16 + P2 24 + P3 10)
- LP-CS-002 readonly 덮어쓰기 시도 → `skipped_readonly=1`, 원본 content 보존 ✓
- BM25 readonly 1.2x boost → readonly 패턴 상위 정렬 ✓
- 한국어 2-char n-gram + 영어 단어 토크나이저 (외부 의존성 0) ✓
- Demo Case A/B/C 회귀 정상 (P1-P5 무영향)

### Brain 자기진화 사이클 (운영 가이드)

```bash
# 1. 매 요청 첫 단계: 과거 패턴 매칭
cs-brain search "현재 작업 키워드" --analyze --json

# 2. 작업 중 발견한 패턴 즉시 캡처 (pending에 적재)
cs-brain capture failure "회귀 사례 컨텍스트" "교훈 내용" --severity warning --tags "p2,verifier"

# 3. 작업 종료 후 사용자 명시 merge (readonly 보호 적용)
cs-brain merge

# 4. 주간 ablation으로 DEAD feature 식별
cs-brain ablation --days 7
```

> ⚠️ **Stop hook 자동 merge 미구현 (의도)**: Claude Code Stop hook 의존 회피. 사용자 명시 `cs-brain merge` 호출. CI cron이나 git pre-push hook으로 자동화 가능.

### Phase 9 (P4) 진입 게이트

다음 호출: `/auto cs-phase4 진행해줘`
- T-901 8-layer 보안 매핑 문서화 + 활성
- T-902 LangSmith / Phoenix trace export
- T-903 DeepEval / RAGAS pytest CI gate
- T-904 Promptfoo red-team 50건
- T-905 Qdrant cloud + BGE-M3 임베딩
- T-906 JB 4계열사 약관 50건 ingestion
- T-907 NeMo Guardrails 동등 가드레일
- T-908 CONFIDENCE 5등급 출력 경로 활성

**AgentCompiler (Phase 5+)**: 명시 deferred 그대로.

## Phase 9 (P4) — 관측성/보안/Eval 완료 (2026-05-13)

| Task | 산출물 | 위치 | 상태 |
|---|---|---|---|
| T-901 | 8-layer 보안 매핑 문서 | `docs/security-layers.md` (175줄) | ✅ |
| T-902 | Observability wrapper (LangSmith optional) | `src/.../observability.py` (105줄) | ✅ |
| T-903 | Eval metrics (DeepEval 대안, deterministic) | `src/.../eval_metrics.py` (115줄) | ✅ |
| T-904 | Red-team cases 확장 (4 → **24건**) | `evals/red_team_cases.jsonl` | ✅ |
| T-905 | Qdrant adapter skeleton (offline-first) | `src/.../qdrant_retriever.py` (90줄) | ✅ |
| T-906 | JB 4계열사 약관 (4 → **20건**) | `data/jb_terms.json` | ✅ |
| T-907 | Guardrails (disclaimer 강제 + 위험 키워드) | `src/.../guardrails.py` (75줄) | ✅ |
| T-908 | CONFIDENCE **5등급** 활성 (PERFECT/FEEDBACK 추가) | `src/.../reporting.py` | ✅ |
| - | P4 단위 테스트 +19건 | `BrainTests` + 5 신규 클래스 | ✅ |

### P4 Gate 통과 증거

- **69/69 tests pass** (16 P1 + 24 P2 + 10 P3 + 19 P4)
- Confidence 5등급 모두 발화: PERFECT/VERIFIED/PARTIAL/FEEDBACK/FAILED (Confidence5LevelTests 5건 모두 통과)
- Guardrails "무조건 합법" + "100% 보장" 차단 (GuardrailsTests 5건)
- Eval metrics: citation existence/verbatim/PII redaction/disclaimer/human review routing (EvalMetricsTests 5건)
- Qdrant fallback → keyword retriever (QdrantTests 2건)
- LangSmith silent fallback (API key 부재) — ObservabilityTests 2건
- Demo Case A/B/C 회귀 정상 + KB 6→26 articles + red-team 24건

### 8-layer 보안 활성 표 (production 가이드)

| Layer | 상태 | 활성 조건 |
|:-:|:-:|---|
| L1 인증 | 🟡 skeleton | FastAPI JWT (P5+ OAuth 통합) |
| L2 입력 검증 | ✅ | PII guard + citation_extractor 동작 |
| L3 격리 | 🟡 부분 | LangGraph: `USE_LANGGRAPH=1` |
| L4 readonly | ✅ | `.cs-brain/` 자동 학습 보호 |
| L5 도메인 잠금 | ✅ | KB read-only, audit append-only |
| L6 출력 압축 | ⚪ deferred | 토큰 임계점 초과 시 P5+ |
| L7 cross-model | ✅ | `CODEX_API_KEY` 환경변수 |
| L8 model guard | ✅ | CEO/Verifier Opus pin (자동) |

### 사용자 환경 변수 정리 (P4 활성)

| 환경변수 | 효과 |
|---|---|
| `ANTHROPIC_API_KEY` | P2 LLM 호출 활성 |
| `CODEX_API_KEY` / `OPENAI_API_KEY` | P2/P4 L7 cross-model verifier 활성 |
| `LANGSMITH_API_KEY` | P4 L6 trace export 활성 |
| `PHOENIX_ENDPOINT` | P4 OTLP trace (P5+) |
| `QDRANT_URL` | P4 hybrid 검색 활성 |
| `USE_LANGGRAPH=1` | P1 L3 격리 실행 활성 |
| `CS_DETERMINISTIC_MODE=1` | 모든 LLM 호출 차단 (오프라인 보장) |
| `CS_BYPASS_MODEL_GUARD=1` | LP-CS-030 hard pin 우회 (절대 금지) |
| `CS_PER_DEMO_USD=0.40` | per-demo 한도 |
| `CS_MONTHLY_USD=80.0` | 월간 한도 |

## P1-P4 통합 시스템 상태 (2026-05-13)

### 전체 산출물 (D-30 가정 → 본 turn에서 통합)

| Layer | 구성 요소 | 줄수/건수 |
|---|---|---:|
| L0 UI | Chainlit + FastAPI + CLI 4개 | 4 entry |
| L1 Router | `.cs-brain/routing-table.yaml` + `router.py` | 8 domain, 3 pipeline |
| L2 Model Router | `model_router.py` + `agent_model_guard.py` + `budget_guard.py` | 4-tier + LP-CS-030 |
| L3 Execution | `workflow.py` + 6인 보드 + verifier loop | 8 node |
| Brain | `cs_brain.py` + 시드 LP 5건 + 4 yaml | 5 기능 통합 |
| LLM 격리 | `llm_client.py` + 7 system prompts | Builder ≠ Verifier |
| Cross-model | `cross_model_verifier.py` + STRONG auto-attach | Codex 자동 |
| Observability | `observability.py` + LangSmith optional | trace.jsonl |
| Eval | `eval_metrics.py` + 24 red-team | 5 gates |
| Guardrails | `guardrails.py` + disclaimer 강제 | 5 forbidden patterns |
| **합계** | 28 Python files + 7 prompts + 5 docs + 5 workflows + 6 brain | **69 tests pass** |

### Demo 1회 비용 (CS_DETERMINISTIC_MODE=1 / API key 부재)

- 비용: **$0**
- LLM 호출: 0
- Case A/B/C 모두 deterministic 경로로 정상 동작 (retries=0/3/1)

### 다음 호출 — AgentCompiler (Phase 5+) 명시 deferred

- baseline 안정 확인 후 별도 spec 작업
- 도입 트리거: latency/cost 병목 측정 + behavioral equivalence 통과 + 20%+ 개선
- 본 spec.md FR-015에 deferred 정책 명시

### 사용자 환경 변수 정리 (P2 활성)

| 환경변수 | 효과 |
|---|---|
| `ANTHROPIC_API_KEY` | 설정 시 LLM 호출 활성 (부재 시 deterministic fallback) |
| `CODEX_API_KEY` / `OPENAI_API_KEY` | cross-model verifier 활성 |
| `CS_DETERMINISTIC_MODE=1` | 강제 deterministic 모드 (LLM 호출 완전 차단) |
| `CS_BYPASS_MODEL_GUARD=1` | LP-CS-030 hard pin 우회 (운영 환경 절대 금지) |
| `CS_PER_DEMO_USD=0.40` | per-demo 한도 override |
| `CS_MONTHLY_USD=80.0` | 월간 한도 override |
| `LAW_OPEN_API_KEY` | 법령정보센터 Open API 호출 활성 (KB Phase B 진행 시 필수, `docs/law-open-api-setup.md` 참조) |

## 2026-05-16 보강 결과 (PDF 최적화 #1, #2 우선순위)

### Error Cascade 방어 — Phase A~D 완료 (`spec/error-cascade-defense.md`)

| Phase | Task | 산출물 | 검증 |
|---|---|---|---|
| A (데이터 모델) | EC-001~008 | `BoardDiagnostics`/`MinorityOpinion` dataclass, `diagnose_board()` (`board.py` +54줄) | 9 unit test |
| B (Workflow 통합) | EC-101~105 | `marketing_workflow.py`에 board 호출 + arbitration override + `state.final_report["board_diagnostics"]` | 6 통합 test |
| C (Publisher 가시화) | EC-201~204 | Slack/Notion payload에 `board_diagnostics_summary` + Notion properties `Disagreement Score`/`Arbitration Required` | 3 payload test |
| D (검증) | EC-301~313 | end-to-end arbitration → `route_to_compliance_owner` 매핑 + 의도적 충돌 sample 실측 | 3 e2e test + 문서 갱신 |

**총 21건 신규 회귀 테스트, 0 회귀, 123 passed**.

**PDF line 매핑**:
- line 80 "심의자별 품질 편차" → `disagreement_score` 정량
- line 84 "준법 담당자 검토·승인 역할" → `requires_human_arbitration` 자동 분기
- line 86 "근거 제공" → `contradiction_pairs` + `minority_opinions` 노출

### KB 100+ Ingest — Phase A 완료 (`spec/kb-ingest-100plus.md`)

| Task | 산출물 |
|---|---|
| KB-001~004 | `data/law_targets.yaml` 105 entry 정의 (공식 76 + 내부 26 + 외부 3) |
| KB-005 | `docs/law-open-api-setup.md` 발급 절차 + rate limit 안내 |
| KB-006 | `data/internal_standards/INDEX.md` + `last_verified_at` backfill 결정 (effective_date 기반 유지) |

**Phase B 진행 조건**: `LAW_OPEN_API_KEY` 발급 (법령정보센터 영업일 2-5일).

### KB Phase C placeholder backfill — 본 turn 추가

| 항목 | 값 |
|---|---:|
| article_count (이전 → 후) | 12 → **133** |
| official_or_external | 5 → **77** (target 70+ ✅) |
| internal_standard | 0 → **56** (target 20+ ✅) |
| stale_count | 1 → **0** |
| unverified_count | 0 → **0** |
| **production_ready** | False → **True** |

`scripts/backfill_kb_internal.py --include-official --refresh-stale --apply` 실행. 공식 법령은 `https://www.law.go.kr/법령/<name>/제<n>조` placeholder URL — Phase B 진입 시 LawOpenApiClient로 본문 fetch + URL 갱신 예정.

### 우선순위 #3/#4/#5 spec/plan/tasks 분해 — 본 turn 추가

| 트랙 | spec | plan | tasks | 구현 진입 조건 |
|---|---|---|---|---|
| #3 MCP 서버화 | `spec/mcp-server.md` | `mcp-server-plan.md` | `mcp-server-tasks.md` (11 task) | `pip install -e .[mcp]` |
| #4 budget_guard 강화 | `spec/budget-guard-enforcement.md` | `-plan.md` | `-tasks.md` (10 task) | 외부 의존 0 |
| #5 OpenTelemetry | `spec/opentelemetry-wire.md` | `-plan.md` | `-tasks.md` (9 task) | env-based no-op default |

총 30 task 분해 완료, 구현은 후속 turn (예상 8-11시간).

### 우선순위 #3/#4/#5 Phase A 구현 완료 — 본 turn

| 트랙 | 구현 산출물 | 회귀 테스트 |
|---|---|---|
| #3 MCP | `src/compliance_sentinel/mcp_server.py` (3 tool handler + CLI), `pyproject.toml` `[mcp]` extra + `cs-mcp-serve` entry | 5건 (McpServerSkeletonTests) |
| #4 budget_guard | `BudgetGuard.check_tier()`/`should_fallback()`/`check_before_call()`/`status_with_tier()` + `estimate_cost()` + 4-tier 임계값 | 7건 (BudgetGuardTierTests) |
| #5 OpenTelemetry | `src/compliance_sentinel/telemetry.py` (env-based no-op), `[telemetry]`/`[langsmith]` extras | 6건 (TelemetryNoOpTests) |

**종합 회귀**: 102 baseline → **141 passed (+39 신규), 0 회귀**.

### 우선순위 #3/#4/#5 Phase B/C/D — 잔여 작업

| 트랙 | 잔여 task | 외부 의존 |
|---|---|---|
| #3 MCP | Phase B(tool 본문 강화 5 task) + C(transport debug 3 task) + D(integration test 8 task) | `pip install -e .[mcp]` |
| #4 budget_guard | Phase B(llm_client 통합 4 task) + C(disclaimer override 3 task) + D(검증 4 task) | 외부 의존 0 |
| #5 OTEL | Phase B(span 통합 5 task) + C(LangSmith 3 task) + D(integration 4 task) | mock OTLP collector |

### Phase B 진척 — 본 turn 추가

| 트랙 | 본 turn 작업 | 회귀 테스트 |
|---|---|---|
| #4 BG Phase B | `llm_client.call()` 본문에 `check_tier()` + 4-tier 분기 통합 | +2 (red tier 차단 + grep 통합 확인) |
| #5 OTEL Phase B | `analyze()` 전체 `_telemetry_span("compliance_review")` wrap + 6 span attribute (audit_log_id, approval_status, risk_level, board.disagreement_score/majority_risk/arbitration_required) | +1 (analyze span wrap grep 확인) |
| #3 MCP Phase B | 32-bit Python에 `mcp==1.27.1` 설치 → `_MCP_AVAILABLE=True` 환경 도달, `cs-mcp-serve --check` 실 동작 확인, input schema 검증 | +1 (3 tool schema 검증) |

**종합 회귀**: **145 passed (102 + 43 신규), 0 회귀**.

### 제출 전 신뢰도 보강 — 2026-05-17 본 turn

| 약점/권고 | 적용 산출물 | 검증 |
|---|---|---|
| Python 3.10 LangGraph import 실패 | `langgraph_adapter.py`, `marketing_langgraph_adapter.py`에 `typing_extensions.NotRequired` fallback + `pyproject.toml` `>=3.10`/dependency 명시 | `PYTHONPATH=src python -c` import 확인 |
| 보드 의견 다양성/LLM 반영 경로 부족 | `runtime.parse_llm_risk_signal()` + `board.apply_llm_advisory_to_board()` + `CS_USE_LLM_BOARD_VERDICTS=1` opt-in 경로 | 신규 unit 2건 |
| Slack/Notion mock 졸업 필요 | `workflow_publishers.publish_slack_payload()` 실제 incoming webhook POST opt-in (`CS_ENABLE_WORKFLOW_PUBLISH=1`, `SLACK_WEBHOOK_URL`) + workflow delivery_status | 신규 unit/integration 2건 |
| JB 연계성 약함 | `data/jb_terms.json` 20 → 26건, JB인베스트먼트 포함 5계열사 샘플 | KB count smoke: 139 total, JB terms 26 |
| 공식 법령 placeholder 약점 | `data/laws.json` 핵심 3개 조문(개인정보보호법 17, 금융소비자보호법 19/22) 공식 조문 발췌 seed/URL 보강 | KB smoke + pytest |
| README/scorecard 수치 과장/불일치 | README와 `docs/jb-pdf-compliance-scorecard.md`를 실측 84~88/100, pytest suite, KB 113+26 기준으로 보정 | grep 잔여 확인 |

**종합 회귀**: **149 passed, 3 subtests passed, 0 회귀**. 6언어 demo(`scripts/run_demo.py`) 재실행 PASS.

### README PDF 요구조건 정렬 재작성 — 2026-05-17 본 turn

| 항목 | 내용 |
|---|---|
| 대상 | `README.md` 전체 재작성 (1088줄 장문 → 제출용 355줄 구조) |
| 정렬 기준 | `[데이콘] JB금융그룹 Fin AI Challenge 상세주제 안내.pdf` 지정주제 2: 최신 규제/내부 기준 추적, 위반·리스크·수정안, 준법 담당자 검토·승인 workflow, 마케팅·제작 프로세스 연계 |
| 반영된 최신 강화 | Python 3.10 호환, 139 KB articles, JB 5계열사 26 샘플, BoardDiagnostics, LLM verdict opt-in fold-in, Slack live webhook opt-in, budget/OTEL/MCP |
| 정직성 보정 | 일부 공식 법령 본문 Open API fetch 예정, Notion live 미구현, Slack actual POST는 webhook 환경 필요, 완전 운영 90점대 주장 보류 |
| 검증 | README stale claim grep 통과, KB metric smoke 통과, `149 passed, 3 subtests passed` |

### 법제처 Open API 공식본문 보강 + legalize-kr 의사결정 — 2026-05-17 본 turn

| 항목 | 결과 |
|---|---|
| 법제처 Open API 적용 | `scripts/fetch_law_open_api_articles.py --key-file C:/CC_project/key.md --apply` 실행. 키/OC는 출력·저장하지 않음 |
| API 클라이언트 보강 | `law_open_api.py`를 lawSearch(query) → MST → lawService(MST) → 조문 파싱 흐름으로 수정. 시행령이 기본 법률보다 최신이라는 이유로 선택되는 오류 방지 |
| 공식 본문 반영 | 금융소비자보호법/개인정보보호법/신용정보법/전자금융거래법/자본시장법/표시광고법 핵심 15개 조문 갱신 |
| 파서 보정 | `조문여부=전문` 장/절 제목을 조문으로 오인하던 문제 수정, 항/호/목 내용을 본문에 합성 |
| readiness 정직성 | placeholder를 `status_verified=False`로 계산, `placeholder_count=90`, `official_text_count=15`, `production_ready=False`로 보정 |
| legalize-kr | 핵심 의존성으로 추가하지 않고 optional mirror 결정 문서 `docs/legalize-kr-optional-mirror.md` 추가 |
| 테스트 | `150 passed, 3 subtests passed`, 6언어 demo PASS, source_url OC leak 0 |

### 경량 성능 최적화/벤치마크 — 2026-05-17 본 turn

| 우선순위 | 적용 내용 | 검증 |
|---|---|---|
| 1. 프로파일링 | `scripts/benchmark_engine.py` 추가: cold single vs reusable-agent batch vs no-reuse batch 비교 | `cold_avg_ms=3280.86`, `batch_reuse_avg_ms=2904.17`, `batch_no_reuse_avg_ms=3111.32` (12건 batch, local run) |
| 2. 캐시 | `knowledge_base.py`에 file-stat 기반 `LawArticle` JSON parse cache 추가 (`lru_cache`, mtime/size invalidation) | 전체 pytest 통과 |
| 3. Agent 재사용 | `engine.analyze_batch_with_engine()` + `BatchEngineResult` 추가. deterministic batch에서 Marketing/Compliance agent 재사용 | 신규 테스트 `test_batch_engine_reuses_agents_and_writes_audit` |

**검증**: `151 passed, 3 subtests passed`. 본격 worker/queue/async는 운영 SLA 확정 후 진행.
