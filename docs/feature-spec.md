# 기능명세서 — Compliance Sentinel

> 3페이지 이내 권장. 항목 6개 모두 포함. PDF 변환 시 페이지 분할 필요.

## 1. 서비스 개요

Compliance Sentinel은 금융 마케팅 콘텐츠(앱푸시, SNS, 배너, 이메일, 랜딩페이지)와 약관/고지 context를 입력받아 표현 리스크, 근거, 수정안, 검증 결과, 승인 라우팅, 감사로그를 반환하는 **준법 검토 보조 AI Agent**입니다. 외부 API key 없이 로컬에서 실행 가능한 deterministic MVP로 시연하며, 운영 시 LangGraph + 법령정보센터 Open API + Presidio + DeepEval로 swap-in됩니다. 최종 보고서는 `review_request_id`, `input_completeness`, `evidence`, `verifier_result`, `confidence_score`, `schema_validation`, `audit_log_id`를 포함합니다.

## 2. 시스템 구성도

```
              ┌──────────────────────┐
              │  User Input (텍스트)  │
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │  PII Guard           │  ← pii.py (한글 인접 lookaround)
              └──────────┬───────────┘
                         ▼
       ┌──────────────────────────────────┐
       │  Citation Extractor              │  ← citation_extractor.py
       │  (사용자 명시 인용 추출)         │
       └──────────────┬───────────────────┘
                      ▼
       ┌──────────────────────────────────┐
       │  RAG Retriever (hybrid-style)    │  ← retriever.py, knowledge_base.py
       │  로컬 KB + (옵션) law.go.kr API   │
       └──────────────┬───────────────────┘
                      ▼
     ┌────────────────────────────────────┐
     │  6인 Compliance Board (병렬)        │  ← board.py
     │  Legal · PIPA · Consumer · AML ·    │
     │  Practicality · Contrarian          │
     └────────────────┬───────────────────┘
                      ▼
            ┌─────────────────────┐
            │  CEO Synthesizer    │  ← synthesizer.py
            └─────────┬───────────┘
                      ▼
            ┌─────────────────────┐
            │  Atomic Verifier    │  ← verifier.py
            │  - law_exists       │
            │  - verbatim_match   │
            │  - applicability    │
            └─┬────────────┬──────┘
              │FAIL/PARTIAL│PASS
              ▼            ▼
     ┌────────────┐  ┌─────────────┐
     │ Revise     │  │ Final Report│
     │ Loop (≤3)  │  └──────┬──────┘
     └────┬───────┘         ▼
          │          ┌─────────────┐
          └─────►    │ Audit Log   │  ← audit.py (append-only JSONL)
                     └─────────────┘
```

## 3. 핵심 기능 명세

| ID | 기능 | 입력 | 출력 | 핵심 로직 |
|---|---|---|---|---|
| F-1 | PII 마스킹 | raw 텍스트 | `[KIND_REDACTED_N]` 마스킹 텍스트 + findings | 한글 인접 lookaround 기반 4-pattern regex |
| F-2 | 사용자 인용 추출 | 마스킹된 텍스트 | `Citation[]` | 법령 화이트리스트 + "제N조" 패턴, 80자 윈도우 페어링 |
| F-3 | 6인 보드 병렬 판단 | 텍스트 + 법령 컨텍스트 | `{agent_id: BoardOpinion}` | 도메인 키워드 매칭, risk_level 추출 |
| F-4 | CEO 종합 | 보드 의견 + 사용자 인용 | `findings: Finding[]` | 사용자 인용 우선 등재 → 보드 인용 dedupe append |
| F-5 | 원자적 검증 | findings | `VerifierResult[]` + 보정된 findings | finding당 3 claim (existence/verbatim/applicability) |
| F-6 | Revise 루프 | FAIL/PARTIAL findings | 보정된 citation_text | KB 원문으로 자동 교체, retry_count ≤ 3 |
| F-7 | Human Review 라우팅 | risk + confidence | `human_review_needed: bool` | FAIL 또는 HIGH/CRITICAL 또는 PARTIAL 시 활성 |
| F-8 | Audit Log | ComplianceState | append-only JSONL line | sha256 input hash + redacted + trace 전체 |

## 4. 흐름도 (시연 시나리오)

3 case가 1회 데모 실행으로 순차 출력:

| Case | 입력 요지 | 기대 결과 | 합격 기준 |
|---|---|---|---|
| A | 캐피탈 앱푸시: `누구나 100% 승인, 최저금리 보장 자동차 할부` | `CRITICAL`, `REJECTED`, `loan`, `verifier_result=FAILED` | 승인보장 표현 + 필수고지 누락 + AUD ID |
| B | 다국어 예금/SNS: `zero risk / không rủi ro / 零风险 / guaranteed benefits` | `HIGH`, `HUMAN_REVIEW_REQUIRED`, 다국어 위험 표현 동시 탐지 | 3개 이상 언어/표현 리스크 finding |
| C | 정상/중위험 예금 안내 | `APPROVE_WITH_CHANGES` 또는 `APPROVED`, 근거/수정안/AUD ID | 필수고지 gap 또는 안전 승인 경로 확인 |

모든 case는 `audit_log_id`, `review_request_id`, `schema_validation.passed=true`를 포함하고 `audit_logs/compliance_audit.jsonl`에 사후 감사 레코드로 보존됩니다.

## 5. 향후 발전 방향 (Roadmap)

| Phase | 작업 | 트리거 |
|---|---|---|
| P0 (현재) | deterministic MVP + JB 약관 ingestion | 완료 |
| P1 (D+5) | 법령정보센터 Open API key 활성 + KB 자동 확장 | env에 LAW_OPEN_API_KEY 설정 |
| P2 (D+10) | LangGraph StateGraph swap (행동 동등성 보장) | `pip install langgraph` + USE_LANGGRAPH=1 |
| P3 (D+20) | Presidio + Microsoft 한국 NER recognizer 통합 | 자체 regex → ML-based PII |
| P4 (D+25) | DeepEval/RAGAS pytest CI gate | PR merge 자동 차단 |
| P5 (D+30+) | AgentCompiler / SGLang / Mem0 / Zep 점진 도입 | baseline 대비 latency/cost 20%+ 개선 시만 |

본 로드맵의 모든 단계는 `langgraph_adapter.py` 인터페이스 덕분에 기존 코드 변경 0으로 swap 가능합니다.

## 6. 부록

### A. 코드 구조 (src/compliance_sentinel/)

```
__init__.py            api.py           audit.py
board.py               citation_extractor.py   classification.py
cli.py                 knowledge_base.py        law_open_api.py
langgraph_adapter.py   models.py                pii.py
reporting.py           retriever.py             synthesizer.py
verifier.py            workflow.py
```

### B. 실행 명령

```bash
PYTHONPATH=src python3 scripts/run_demo.py
PYTHONPATH=src python3 -m compliance_sentinel.cli --json "광고 문구: 원금 보장 무위험 확정 수익을 제공합니다."
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

### C. 참조 (1차 출처)

- 법령정보센터 Open API: https://open.law.go.kr/LSO/openApi/guideList.do
- LangGraph: https://langchain-ai.github.io/langgraph/
- Microsoft Presidio: https://microsoft.github.io/presidio/
- DeepEval: https://docs.confident-ai.com/
- 자세한 매핑: `references/references.md`

### D. 변경이력 (본선 진출 시 의무 제출)

| 버전 | 일자 | 변경 요약 |
|---|---|---|
| 0.1.0 | 초기 MVP | 6인 보드 + 검증자 루프 + audit log + Chainlit/FastAPI skeleton |
| 0.2.0 | 2026-05-13 | PII 한글 인접 어미 fix, 사용자 인용 verifier wiring (AC-002), JB 4개 계열사 약관 ingestion, LangGraph swap adapter, 법령정보센터 API skeleton |
| 0.3.0 | 2026-05-21 | 기능명세서 V2 정합성 보강: `evidence`/`verifier_result`/`confidence_score`/`review_request_id`/`schema_validation` 노출, 캐피탈 할부 loan 분류, 혼합 다국어 위험표현 동시 탐지, runtime guard 추가 |

### Disclaimer

본 시스템은 **법률 자문이 아닌** 준법 검토 보조 및 리스크 탐지 시스템입니다. 고위험·불확실 판단은 반드시 인간 컴플라이언스 담당자에게 에스컬레이션됩니다.
