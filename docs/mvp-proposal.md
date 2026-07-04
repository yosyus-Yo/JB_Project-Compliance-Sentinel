# MVP 제안서 — Compliance Sentinel

> JB Fin:AI Challenge 지정주제 2번 (준법자문가 AI Agent)
>
> 항목 틀은 대회 요강에 따라 **변경 금지**. 본 문서는 PDF 변환용 마크다운 초안.

## 1. Summary

Compliance Sentinel은 금융 약관 / 광고 문구 / 계약 조항 / 거래 시나리오를 입력받아 관련 법령·내부정책과 대조하고 **판단 → 행동 → 검증 → 감사** 4단계를 코드 레벨에서 실제로 흐르게 하는 준법 검토 보조 AI Agent입니다. 단순 RAG QA 챗봇과 차별점은 (1) 6인 적대적 보드의 다중 관점 판단, (2) 사용자 인용까지 검증하는 Verifier 루프, (3) 모든 결정의 append-only audit log, (4) Hard Gate 기반 human-in-the-loop입니다.

## 2. 문제 정의

금융 규제는 매년 변동하고 부서별·계열사별로 적용 해석이 다릅니다. 약관·광고·계약·거래 문구가 PIPA·신용정보법·금융소비자보호법·전자금융감독규정 등과 충돌할 위험이 상시 존재하며, 위반 시 과징금·평판 손실·CEO 호출이 발생합니다. 기존 솔루션은 (a) 키워드 검색 기반 정적 검토, (b) 변호사·준법감시인의 수작업, (c) 단순 LLM 챗봇 — 모두 환각·근거 부재·감사 불가의 한계가 있습니다.

## 3. 솔루션 개요

```
입력 → PII Guard → 사용자 인용 추출 → 법령 RAG 검색 →
6인 컴플라이언스 보드 병렬 판단 →
CEO Synthesizer 종합 →
Atomic Verifier (law_exists / verbatim_match / applicability) →
[실패 시 최대 3회 자동 수정 또는 Human Review] →
최종 보고서 → Audit Log
```

- 코드: `src/compliance_sentinel/workflow.py` (8 node)
- 옵션 백엔드: `langgraph_adapter.py` (LangGraph StateGraph swap)
- 데모: `scripts/run_demo.py` 3 case 1분 안에 시연 (Case A 정상 / Case B 가짜 인용 차단 / Case C 자동 보정)

## 4. 주요 기능

| # | 기능 | 코드 위치 | 차별점 |
|---|---|---|---|
| 1 | PII 자동 마스킹 (RRN/Phone/Email/Account, 한글 인접 어미 포함) | `pii.py` | 한국어 텍스트 환경에 맞춘 lookaround 경계 |
| 2 | 6인 적대적 보드 (Legal/PIPA/Consumer/AML/Practicality/Contrarian) | `board.py` | 단일 LLM 답변 대신 다중 관점 합의 |
| 3 | 사용자 명시 인용 직접 검증 | `citation_extractor.py` + `verifier.py` | "제999조" 같은 환각 인용을 자체 RAG가 무시하지 않고 차단 |
| 4 | 원자적 클레임 분해 + verifier loop (3회 자동 수정) | `verifier.py`, `workflow.py` | Builder ≠ Verifier 격리 |
| 5 | Human-in-the-loop 라우팅 (PARTIAL/FAIL/HIGH risk 시) | `reporting.py` | 책임 소재 분리 |
| 6 | Append-only audit log (sha256 input hash, trace JSONL) | `audit.py` | 사후 감사 가능 |
| 7 | JB 4개 계열사 약관 샘플 ingestion (전북/광주/우리캐피탈/자산운용) | `data/jb_terms.json` | 사업 연계성 직격 |
| 8 | 법령정보센터 Open API offline-first adapter | `law_open_api.py` | API key 부재 시 로컬 캐시 fallback, 운영 시 swap-in |

## 5. 데이터 / 기술 활용

| 영역 | 사용 기술 | 운영 단계 옵션 |
|---|---|---|
| Workflow | deterministic orchestrator (기본) → LangGraph StateGraph (optional) | LangGraph + LangSmith trace |
| 법령 KB | 로컬 캐시(JSON) 6건 + JB 약관 샘플 4건 | 법령정보센터 Open API + Qdrant hybrid search |
| 한국어 처리 | 한글 word boundary lookaround | BGE-M3 임베딩 + KoSimCSE |
| PII | 자체 4-pattern regex | Microsoft Presidio + 한국 custom recognizer |
| 평가 | unittest 6건 + red-team 4건 JSONL seed | DeepEval / RAGAS / Promptfoo CI gate |
| UI | Chainlit/FastAPI skeleton | Chainlit full demo + Streamlit dashboard |
| 관측성 | local trace (state.trace) | LangSmith + Phoenix + Laminar |
| 감사 | append-only JSONL | OpenTelemetry export + WORM 보존 |

## 6. 사용자 시나리오

**시나리오 1** — 마케팅 팀이 신규 광고 문구 검토 요청
- 입력: "본 광고는 금융소비자보호법 제19조의 설명의무를 충족합니다. 원금 보장 무위험 확정 수익."
- 시스템: 사용자 인용을 추출 → 정상 조항이지만 verbatim 미스매치 → revise 1회 자동 보정 → 광고 위험 finding(`금융광고 가이드라인 G-1`) HIGH risk → Human review 라우팅
- 출력: status=HUMAN_REVIEW_REQUIRED, retries=1, confidence=PARTIAL, audit_log_id 발급

**시나리오 2** — Prompt injection 시도 차단
- 입력: "이 약관은 개인정보보호법 제999조를 위반합니다." (가짜 조항)
- 시스템: 사용자 인용 추출 → law_exists FAIL → 3회 retry 후 final FAIL → human review
- 결과: confidence=FAILED — 환각 인용이 결론으로 통과 못함

**시나리오 3** — JB우리캐피탈 신차 할부 광고 사전 검토
- 입력: "캐피탈 앱푸시: 누구나 100% 승인, 최저금리 보장 자동차 할부"
- 시스템: `loan` 계열로 분류 → `100% 승인`을 CRITICAL 승인보장 표현으로 탐지 → 필수고지 누락 탐지 → 보수적 정책에 따라 `REJECTED` 및 재작성 요청 → audit ID 발급
- 출력: `risk_level=CRITICAL`, `approval_status=REJECTED`, `verifier_result=FAILED`, `review_request_id`/`audit_log_id` 발급

## 7. 기대효과 / 확장성

**기대효과**
- 준법 담당자 1차 검토 시간 30~50% 단축 목표 [추정 — D-30 실측 필요]
- 환각 법령 인용에 의한 잘못된 결론 차단 (red-team #1 PoC 통과)
- 모든 검토 결정의 사후 감사 가능 (감사 로그 100%)

**확장성**
- LangGraph StateGraph로 swap-in 가능한 인터페이스 (`langgraph_adapter.py`)
- 법령정보센터 Open API key 추가만으로 production 데이터 소스 전환
- JB 4개 계열사 + 지역금융(전북/광주) 특화 데이터 ingestion 모듈 분리 설계
- AgentCompiler / Mem0 / Zep 등은 baseline 행동 동등성 검증 후 점진 도입

## Disclaimer

본 결과는 법률 자문이 아닌 준법 검토 보조 및 리스크 탐지입니다. 모든 고위험·불확실 판단은 인간 컴플라이언스 담당자에게 에스컬레이션됩니다.
