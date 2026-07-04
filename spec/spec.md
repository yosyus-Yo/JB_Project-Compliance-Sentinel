# Spec — 금융 마케팅 콘텐츠 AI 심의관

## 1. 목적

Compliance Sentinel은 기존 “약관/법령 검토 보조”에서 **금융 마케팅 콘텐츠 AI 심의관**으로 재구축된다. 마케팅팀이 만든 대고객 콘텐츠 초안(배너, 앱푸시, SNS, 이메일, 랜딩페이지, 다국어 문구)을 입력하면 AI Agent가 콘텐츠 유형·언어·상품을 분류하고, 금융광고/소비자보호/내부 심의 기준에 따른 표현 리스크와 수정안을 제시하며, 준법 담당자의 승인 workflow까지 지원한다.

## 2. 제품 포지셔닝

- **기존 인상**: AI 변호사 / 법령 검토 엔진
- **신규 목표**: AI 콘텐츠 심의관 / 금융 마케팅 제작-준법 병목 해소 Agent
- **핵심 사용자**: 마케팅 담당자, 준법 심의 담당자, 콘텐츠 제작자, 데모 심사위원

## 3. 차별화 전략

| 코드 | 차별화 | MVP 반영 |
|---|---|---:|
| A | 다국어·Cross-Cultural 콘텐츠 심의 | MUST |
| B | 이미지 OCR/영상 STT 멀티모달 확장 | SHOULD (OCR 우선) |
| C | 자동 수정안 + Slack/Notion mock 발행 | MUST |
| D | 최신 규제 변경 추적 | SHOULD |
| E | Human-in-the-loop + Audit | MUST |
| F | JB 5계열사 광고 데이터셋/평가표 | MUST |

MVP 권장 조합은 **A + C + F + OCR 일부**이다.

## 4. 범위

### In Scope

- 한국어 및 5개 외국어 콘텐츠 심의: 영어, 중국어, 베트남어, 일본어, 인도네시아어
- 콘텐츠 유형 분류: 배너, 앱푸시, SNS, 이메일, 랜딩페이지, 약관/고지
- 상품 유형 분류: 예금/적금, 대출, 카드, 투자, 보험, 기타
- 금지/주의 표현 탐지: 원금 보장, 무위험, 확정 수익, 누구나 승인, 무조건 혜택 등
- 필수 고지 누락 탐지: 우대금리 조건, 한도, 세전/세후, 심사 조건, 위험 고지
- 규칙 기반 판단 + LLM advisory/critic 결합
- 수정안 자동 생성
- 승인 상태: 승인 가능, 수정 후 승인, 반려, 준법 담당자 검토 필요
- Slack/Notion mock 발행 payload 생성
- audit log 및 평가 메타데이터 저장

### Out of Scope

- 최종 법률 자문 대체
- 실제 Slack/Notion 외부 쓰기 연동(초기에는 mock payload)
- 모든 국가별 금융규제 완전 커버리지
- 실거래/고객원장 조회
- 영상 STT 전체 자동화(초기에는 확장 포인트)

## 5. 기능 요구사항

### MFR-001 Content Intake

- 시스템은 텍스트 콘텐츠를 기본 입력으로 받아야 한다.
- IF 이미지/영상 입력이 제공될 경우 THEN OCR/STT 확장 포인트를 통해 텍스트화할 수 있어야 한다.

### MFR-002 Language Detection

- 시스템은 입력 언어를 `ko`, `en`, `zh`, `vi`, `ja`, `id`, `unknown` 중 하나로 분류해야 한다.
- 다국어 콘텐츠는 원문 의미와 한국 금융광고 기준 간 의미 충돌을 표시해야 한다.

### MFR-003 Content Classification

- 시스템은 콘텐츠 채널과 유형을 분류해야 한다.
- 분류 결과는 이후 심의 기준 선택에 사용되어야 한다.

### MFR-004 Product Classification

- 시스템은 금융상품 유형을 예금/대출/카드/투자/보험/기타로 분류해야 한다.

### MFR-005 Rule-Based Review

- 시스템은 `data/review_standards/*.yaml` 기준으로 금지 표현과 필수 고지 누락을 탐지해야 한다.
- 탐지 결과는 severity, evidence, rationale, suggested_revision을 포함해야 한다.

### MFR-006 LLM Advisory Review

- 시스템은 `CS_ENABLE_LLM_RUNTIME=1` 및 선택 provider API key가 있을 때 역할별 LLM advisory call을 수행해야 한다.
- 키가 없거나 비활성화된 경우 deterministic fallback으로 동작해야 한다.

### MFR-007 Revision Generation

- 시스템은 위험 표현별 수정 문구를 생성해야 한다.
- 수정안은 원문보다 보수적이고 조건/한도/위험 고지를 포함해야 한다.

### MFR-008 Verifier / Critic

- critical/high-risk 콘텐츠는 `CS_MODEL_CRITIC`에 설정된 별도 critic 모델이 분리 컨텍스트에서 검증해야 한다.
- 검증 실패/불확실성은 human review로 라우팅되어야 한다.

### MFR-009 Approval Workflow

- 시스템은 approval_status를 산출해야 한다.
  - `APPROVED`
  - `APPROVE_WITH_CHANGES`
  - `REJECTED`
  - `HUMAN_REVIEW_REQUIRED`

### MFR-010 Workflow Export

- 시스템은 Slack/Notion mock payload를 생성해야 한다.
- payload에는 콘텐츠 요약, 위험 표현, 수정안, 승인 상태, audit id가 포함되어야 한다.

### MFR-011 Audit & Safety

- 원문 PII는 LLM 호출 및 audit log에 남지 않아야 한다.
- 모든 판단은 audit log에 append-only로 기록되어야 한다.

### MFR-012 Evaluation Dataset

- 시스템은 최소 5개 다국어 샘플과 JB 계열사 광고 수집 데이터셋 확장 포인트를 가져야 한다.

## 6. 출력 스키마

```json
{
  "review_type": "marketing_content_compliance",
  "status": "PASSED | HUMAN_REVIEW_REQUIRED | FAILED",
  "approval_status": "APPROVED | APPROVE_WITH_CHANGES | REJECTED | HUMAN_REVIEW_REQUIRED",
  "risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
  "confidence": "PERFECT | VERIFIED | PARTIAL | FEEDBACK | FAILED",
  "language": "ko | en | zh | vi | ja | id | unknown",
  "channel": "banner | app_push | sns | email | landing_page | notice | unknown",
  "content_type": "deposit_ad | loan_ad | card_event | investment_ad | insurance_ad | generic_financial_ad",
  "product_type": "deposit | loan | card | investment | insurance | unknown",
  "findings": [],
  "revision_suggestions": [],
  "workflow_exports": {"slack": {}, "notion": {}},
  "model_plan": {},
  "llm_calls": [],
  "audit_log_id": "AUD-...",
  "disclaimer": "본 결과는 법률 자문이 아닌 준법 심의 보조 및 리스크 탐지 결과입니다."
}
```

## 7. 다국어 데모 샘플

| 언어 | 샘플 | 기대 탐지 |
|---|---|---|
| en | `Guaranteed 8% return with zero risk for everyone.` | guaranteed, zero risk, everyone |
| zh | `零风险，保证收益，所有客户都可以获得最高利率。` | 무위험, 보장수익, 모든 고객 최고금리 |
| vi | `Lợi nhuận chắc chắn, không rủi ro, ai cũng được duyệt vay.` | 확정 수익, 무위험, 대출 승인 보장 |
| ja | `元本保証で必ず利益が出ます。今すぐ申し込めば全員対象です。` | 원금보장, 반드시 이익, 전원 대상 |
| id | `Untung pasti tanpa risiko, semua nasabah langsung disetujui.` | 확정 이익, 무위험, 즉시 승인 |

## 8. Acceptance Criteria

- MAC-001: 한국어 예금 광고에서 `원금 보장`, `확정 수익`, `무조건` 표현을 탐지한다.
- MAC-002: 영어/중국어/베트남어/일본어/인도네시아어 샘플의 위험 표현을 각각 1개 이상 탐지한다.
- MAC-003: 대출 광고에서 `100% 승인`, `신용점수 상관없이` 표현을 반려 또는 human review로 라우팅한다.
- MAC-004: 각 finding은 evidence, rationale, suggested_revision을 포함한다.
- MAC-005: 최종 보고서는 approval_status와 revision_suggestions를 포함한다.
- MAC-006: Slack/Notion mock payload가 생성된다.
- MAC-007: PII는 final report/audit log에 원문으로 남지 않는다.
- MAC-008: LangGraph primary path와 deterministic fallback 모두 동작한다.
- MAC-009: 모델 라우팅은 provider-agnostic tier(`CS_MODEL_SHALLOW`, `CS_MODEL_STANDARD`, `CS_MODEL_DEEP`, `CS_MODEL_CRITIC`)로 동작하며 OpenAI/Anthropic/Gemini/OpenAI-compatible provider를 선택할 수 있다.
- MAC-010: 전체 테스트는 통과해야 한다.
