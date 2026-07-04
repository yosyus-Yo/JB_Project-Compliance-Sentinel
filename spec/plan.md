# Plan — 금융 마케팅 콘텐츠 AI 심의관 재구축

## 1. 재구축 원칙

1. 기존 Compliance Sentinel의 검증·감사·LangGraph·모델 라우팅 자산은 재사용한다.
2. 제품 중심은 “법령/약관 검토”가 아니라 “대고객 마케팅 콘텐츠 심의”로 전환한다.
3. 기본 경로는 deterministic + rule engine으로 재현성을 확보하고, LLM은 advisory/critic으로 결합한다.
4. 실제 LLM 호출은 `CS_ENABLE_LLM_RUNTIME=1`일 때만 활성화한다.
5. 다국어·workflow action·평가 데이터셋을 우승 차별화 포인트로 삼는다.

## 2. 목표 아키텍처

```text
Content Intake
  → PII/Sensitive Guard
  → Language Detector
  → Channel/Product Classifier
  → Review Standards Retriever
  → Rule-Based Checker
  → LLM Advisory Board
  → Revision Generator
  → Verifier / Adversarial Critic
  → Approval Decision
  → Slack/Notion Mock Publisher
  → Audit + Evaluation Metadata
```

## 3. LangGraph Node 설계

| Node | 역할 | 재사용/신규 |
|---|---|---|
| content_intake | 텍스트/OCR/STT 입력 정규화 | 신규 |
| pii_guard | PII 마스킹 | 재사용 |
| detect_language | ko/en/zh/vi/ja/id 감지 | 신규 |
| classify_content | 채널/유형/상품 분류 | 신규 |
| load_review_standards | YAML 기준 로드 | 신규 |
| rule_based_review | 금지 표현/필수 고지 탐지 | 신규 |
| llm_advisory_board | provider-agnostic 역할별 advisory calls | 재사용+신규 |
| generate_revisions | 수정안 생성 | 신규 |
| independent_validation | `CS_MODEL_CRITIC` critic route | 재사용 |
| approval_decision | 승인/수정/반려/HITL 결정 | 신규 |
| publish_workflow_mock | Slack/Notion payload 생성 | 신규 |
| audit_log | append-only audit | 재사용 |

## 4. 에이전트 팀

| Agent | 모델 라우팅 | 역할 |
|---|---|---|
| Intake Classifier | `CS_MODEL_SHALLOW` | 언어/채널/상품 분류 보조 |
| Rule Reviewer | deterministic + `CS_MODEL_STANDARD` | 기준 기반 위험 탐지 |
| Multilingual Reviewer | `CS_MODEL_STANDARD` | 다국어 의미/문화권 리스크 검토 |
| Revision Writer | `CS_MODEL_DEEP` | 안전한 수정 문구 생성 |
| Adversarial Critic | `CS_MODEL_CRITIC` | 과소탐지/과장표현 검증 |
| Approval Orchestrator | deterministic | 승인 상태/워크플로우 발행 |
| Audit Officer | deterministic | audit/log/eval metadata 기록 |

## 5. 데이터 설계

```text
data/review_standards/
  financial_marketing.yaml
  multilingual_risk_pack.yaml
  channel_disclosure.yaml

evals/marketing_content_cases.jsonl
  - ko/en/zh/vi/ja/id 샘플
  - expected risk flags
  - expected approval_status
```

## 6. 핵심 구현 파일

| 파일 | 목적 |
|---|---|
| `marketing_models.py` | 콘텐츠 심의 dataclass/schema |
| `content_standards.py` | YAML 기준 로더 |
| `marketing_reviewer.py` | deterministic 심의 엔진 |
| `marketing_workflow.py` | ComplianceState 호환 workflow |
| `marketing_langgraph_adapter.py` | LangGraph primary path |
| `workflow_publishers.py` | Slack/Notion mock payload |
| `engine.py` | 기본 실행 경로를 marketing workflow로 전환 |

## 7. 평가 전략

- Unit: language detection, rule matching, revision generation, approval decision
- Integration: engine deterministic, LangGraph, CLI JSON
- Safety: PII 원문 미노출
- Multilingual: 5개 외국어 샘플 각각 위험 탐지
- Regression: 기존 verifier/audit/model routing 테스트 유지

## 8. 압축 로드맵

### Phase A — Spec & Standards
- spec/plan/tasks 재작성
- review standards YAML 작성
- 다국어 샘플 JSONL 작성

### Phase B — Core Engine
- marketing reviewer 구현
- revision/approval/workflow export 구현
- ComplianceState 호환 final_report 생성

### Phase C — LangGraph & Runtime
- marketing LangGraph adapter 구현
- engine.py 기본 경로 전환
- CLI/API/demo marketing 중심 전환

### Phase D — Verification
- unit/integration tests 추가
- 기존 tests 회귀 통과
- 다국어 5개 샘플 smoke 통과

## 9. 리스크와 완화

| 리스크 | 완화 |
|---|---|
| 실제 국가별 규제 과대 주장 | “한국 금융광고 기준 기반 cross-cultural screening”으로 표현 |
| LLM 비용 폭증 | 기본 deterministic, 명시 활성화 필요 |
| 다국어 번역 품질 | deterministic 위험어 사전 + LLM advisory 분리 |
| 기존 기능 회귀 | legacy ComplianceSentinel 보존, engine만 marketing 기본화 |
| PII 유출 | redacted content만 report/audit에 저장 |
