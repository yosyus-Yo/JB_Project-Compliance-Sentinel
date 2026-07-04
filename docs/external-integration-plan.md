# 외부 연계 상세 설계

> 원칙: 대회 제출 MVP는 외부 키 없이 deterministic fallback으로 재현 가능해야 한다. 운영/본선 고도화에서는 아래 환경변수와 adapter만 연결해 실제 외부 시스템으로 승격한다. AgentCompiler는 거의 완성된 별도 컴포넌트를 추후 결합하는 전제로, 본 문서는 연결 계약만 정의한다.

## 1. 연계 계층 개요

```text
CLI / API / Chainlit
  → engine.analyze_with_engine()
  → MarketingContentReviewAgent 또는 ComplianceSentinel
  → Retrieval Layer: local JSON → law.go.kr → Qdrant
  → Reasoning Layer: deterministic rules → LLM advisory → Cross-model verifier
  → Workflow Layer: local audit JSONL → Slack/Notion/Jira/Groupware
  → Observability/Eval: local trace → LangSmith/Phoenix/DeepEval/RAGAS
  → Optimization: baseline workflow → AgentCompiler compiled workflow
```

## 1-1. 규제 감시 운영 흐름 (Reg-watch → Materiality → Policy diff)

Claude for Legal의 `reg-feed-watcher`/`policy-diff` 패턴은 한국 금융권에 맞춰 다음 운영 흐름으로 축소 적용한다.

```text
금융위·금감원·법령정보센터·개인정보위 feed
  → source/provenance 태깅
  → materiality filter
     - material: 새 의무·시행일·제재·금융권 직접 영향
     - informational: 가이드·보도자료·예고·동향
     - skip: 적용 범위 밖 또는 중복
  → policy diff
     - 새/변경 요구사항을 discrete requirement로 분해
     - JB 내부 심의 기준·상품설명서·광고 가이드와 매핑
     - gap: none / partial / full / new-policy-needed
  → gap tracker
     - owner, due_date, status_verified, source_url, audit_log_id 기록
  → HITL 승인 후 Skill/RAG/Memory 후보로 stage
```

### 운영 원칙

- feed 항목은 **법률 결론이 아니라 lead**로 취급한다. 준법 담당자가 최종 materiality와 policy update 여부를 승인한다.
- 규제 원문/보도자료/지침은 source, retrieved_at, effective_date, status_verified를 필수 metadata로 저장한다.
- 검색 결과가 적거나 출처가 미확인인 경우 모델 지식으로 조용히 보충하지 않고 `SOURCE_GAP`을 audit trace에 남긴다.
- 시행일·개정 상태가 불명확하면 gap tracker에 `status_verified=false`로 기록하고 overdue 판단에는 사용하지 않는다.

## 2. 법령정보센터 Open API

### 목적
- PDF 요구사항의 “최신 금융규제 자동 추적”을 운영 단계에서 충족.
- 로컬 KB miss 시 공식 조문을 조회하고 canonical cache에 적재.

### 설정
```bash
export LAW_OPEN_API_KEY="..."
```

### 연결 지점
- `src/compliance_sentinel/law_open_api.py`
- `LawOpenApiClient.fetch_article(law_name, article_no)`
- `LawKnowledgeBase.get_article()`에서 로컬 miss 시 자동 호출.

### 운영 절차
1. 법령정보센터 계정에서 Open API key 발급.
2. 실제 응답 샘플 5~10개 저장: 개인정보보호법, 신용정보법, 금융소비자보호법, 전자금융거래법, 전자금융감독규정.
3. `_parse_article_response()` 계약 테스트 추가.
4. 조회 성공 조문은 `data/laws.json` 또는 별도 `cache/law_articles.jsonl`에 append-only 저장.
5. 매일/매주 스케줄러로 핵심 조항 변경 여부 diff.

### 실패 처리
- 네트워크/파싱 실패 시 None 반환.
- 시스템은 local KB fallback으로 계속 동작.
- fallback 발생은 trace와 audit metadata에 기록한다.

## 3. Qdrant / Vector DB Hybrid Retrieval

### 목적
- PDF의 “규제 문서 검색·참조 근거 제공”을 keyword-only에서 dense+sparse hybrid로 고도화.

### 설정
```bash
pip install qdrant-client sentence-transformers
export QDRANT_URL="https://..."
export QDRANT_API_KEY="..."   # 필요 시
```

### 연결 지점
- `src/compliance_sentinel/qdrant_retriever.py`
- collection: `compliance_laws`
- vector model: `BAAI/bge-m3`

### 인덱싱 payload schema
```json
{
  "law_name": "금융소비자보호법",
  "article_no": "19",
  "title": "설명의무",
  "effective_date": "2024-10-25",
  "source_url": "https://www.law.go.kr/...",
  "text": "...",
  "keywords": ["설명의무", "중요한 사항"]
}
```

### 운영 절차
1. `data/laws.json`, JB 내부 기준, 계열사 약관, 상품설명서 PDF를 chunking.
2. chunk마다 `law_name/article_no/source_url/effective_date` metadata 필수 부착.
3. exact law/article query는 metadata filter 우선.
4. 의미 검색은 dense vector + keyword overlap rerank.
5. verifier는 반드시 canonical 원문으로 재확인하여 RAG hallucination 차단.

## 4. Slack / Notion / 그룹웨어 승인 Workflow

### 목적
- PDF의 “승인 결과를 마케팅 및 제작 프로세스와 자동 연계” 충족.

### 현재 상태
- `workflow_publishers.py`가 Slack/Notion payload를 생성한다.
- 기본은 mock payload이며 외부 호출은 하지 않는다.

### 설정 예시
```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
export NOTION_API_KEY="secret_..."
export NOTION_DATABASE_ID="..."
```

### 연결 절차
1. `build_slack_payload()` 결과를 webhook POST.
2. `audit_log_id`, `approval_status`, `risk_level`, `finding_count`, `revision_suggestions` 포함.
3. Notion database에는 다음 필드 생성:
   - Title: campaign/content id
   - Status: APPROVED / APPROVE_WITH_CHANGES / HUMAN_REVIEW_REQUIRED / REJECTED
   - Risk Level: LOW/MEDIUM/HIGH/CRITICAL
   - Audit Log ID
   - Reviewer
   - Due Date
   - Evidence URL
4. 준법 담당자가 Notion/그룹웨어에서 승인하면 callback이 `audit_log_id` 기준으로 audit record에 후속 상태를 append.

### 보안
- 외부 payload에는 raw PII를 포함하지 않는다.
- `redacted_content`와 hash만 전달.
- webhook 실패 시 retry queue에 저장하고 심의 결과 자체는 로컬 audit에 남긴다.

## 5. LLM Runtime / Cross-Model Verifier

### 목적
- deterministic rule baseline 위에 LLM 판단을 advisory layer로 추가.
- Builder ≠ Verifier 격리로 법령 인용 환각 차단.

### 설정
```bash
export CS_ENABLE_LLM_RUNTIME=1
export OPENAI_API_KEY="..."   # 또는 CODEX_API_KEY
```

### 연결 지점
- `llm_client.py`
- `runtime.py`
- `model_router.py`
- `cross_model_verifier.py`

### 운영 규칙
- raw input이 아니라 `redacted_text`만 LLM에 전달.
- CEO/builder와 verifier는 다른 system prompt, 다른 role assignment.
- high/critical quality는 independent validator 자동 부착.
- LLM 응답은 final decision이 아니라 finding/revision/verifier evidence의 보강으로만 사용.

## 6. LangGraph / LangSmith / Observability

### 설정
```bash
pip install langgraph langsmith
export USE_LANGGRAPH=1
export LANGSMITH_API_KEY="..."
export LANGSMITH_PROJECT="jb-compliance-sentinel"
```

### 연결 지점
- `marketing_langgraph_adapter.py`: 마케팅 그래프
- `langgraph_adapter.py`: 일반 준법 그래프 확장 지점
- `observability.py`: local trace + LangSmith export

### 운영 절차
1. deterministic workflow의 node 이름과 LangGraph node 이름을 동일하게 유지.
2. 각 node input/output에는 PII redaction 상태와 audit id를 포함.
3. LangSmith trace에는 raw PII 금지.
4. 실패 케이스를 trace URL과 함께 scorecard에 첨부.

## 7. DeepEval / RAGAS / Promptfoo 평가 게이트

### 설정
```bash
pip install deepeval ragas promptfoo
```

### 평가 항목
- citation existence
- citation verbatim match
- context precision/recall
- PII leakage
- human review routing consistency
- forbidden output pattern
- multilingual risky expression recall

### CI 정책
1. `evals/red_team_cases.jsonl`을 기준 세트로 유지.
2. PR마다 deterministic tests + eval metrics 실행.
3. critical case fail 시 merge 차단.
4. metric 결과는 `eval_reports/YYYY-MM-DD.json`로 보존.

## 8. AgentCompiler 추후 결합 계약

### 전제
- AgentCompiler는 별도 컴포넌트가 거의 완성되어 추후 결합한다.
- 본 저장소에서는 baseline workflow의 behavioral equivalence를 보존하는 adapter만 둔다.

### 결합 위치
```text
engine.analyze_with_engine()
  → baseline graph/workflow 선택
  → AgentCompiler.compile(workflow_spec)
  → compiled_workflow.invoke(redacted_state)
  → output equivalence check
```

### 입력 계약
```json
{
  "workflow_id": "marketing_content_review" 또는 "general_compliance_review",
  "nodes": ["pii_guard", "retrieve_context", "board", "synthesizer", "verifier", "audit"],
  "state_schema": "ComplianceState",
  "privacy_mode": "redacted_only",
  "max_retry": 3,
  "equivalence_tests": ["tests/test_compliance_sentinel.py", "evals/red_team_cases.jsonl"]
}
```

### 출력 계약
```json
{
  "compiled": true,
  "latency_ms": 0,
  "cost_estimate_usd": 0,
  "behavioral_equivalence": "PASS|FAIL",
  "unsupported_nodes": []
}
```

### 결합 승인 게이트
- baseline 85+ tests PASS.
- red-team critical 0 fail.
- compiled output의 `status/risk_level/findings/verifier_status/human_review_needed`가 baseline과 동등.
- latency 또는 cost 20% 이상 개선.
- PII raw leak 0건.

## 9. 운영 체크리스트

- [ ] 외부 API key는 `.env`가 아니라 secret manager/CI secret 사용.
- [ ] raw PII는 외부 tool payload에 포함 금지.
- [ ] 법령/내부 기준 source_url, effective_date 필수.
- [ ] high/critical은 항상 human review.
- [ ] audit log는 append-only, 삭제/수정 금지.
- [ ] 외부 장애 시 local fallback으로 심의 지속.
- [ ] AgentCompiler 적용 전후 behavioral equivalence 리포트 보존.
