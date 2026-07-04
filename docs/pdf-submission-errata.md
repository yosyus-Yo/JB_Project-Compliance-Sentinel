# 제출 PDF 정합성 Errata

> 목적: `JB_Compliance_Sentinel_기능명세서_v2_심사위원용.pdf`와 `JB_Compliance_Sentinel_MVP_제안서_v2_심사위원용.pdf`를 최종 제출 전 재생성할 때 반영해야 할 코드 정합성 보정 사항이다.

## 1. 데모 Case A 결과 보정

현재 코드의 보수적 준법 정책은 `100% 승인`을 CRITICAL 승인보장 표현으로 처리한다.

- 입력: `캐피탈 앱푸시: 누구나 100% 승인, 최저금리 보장 자동차 할부`
- 실제 출력: `risk_level=CRITICAL`, `approval_status=REJECTED`, `product_type=loan`, `verifier_result.status=FAILED`
- PDF 기존 기대값: `HIGH`, `APPROVE_WITH_CHANGES`

최종 PDF에는 아래처럼 수정하는 것이 안전하다.

```text
CASE A · 캐피탈 “누구나 100% 승인, 최저금리 보장” 자동차 할부 앱푸시
기대 결과: CRITICAL, REJECTED, 수정 불가/재작성 요청, AUD ID
합격 기준: 승인보장 표현 1개 이상 + 필수고지 누락 탐지 + audit_log_id 발급
```

## 2. Confidence 표기 보정

실제 보고서는 심사용 가독성을 위해 등급형과 수치형을 함께 노출한다.

- `confidence`: `PERFECT | VERIFIED | PARTIAL | FEEDBACK | FAILED`
- `confidence_score`: `0.0 ~ 1.0`

PDF 예시 JSON에는 `confidence_score`를 추가하거나 `confidence`를 등급형으로 바꾼다.

## 3. Schema validation 보정

코드는 `compliance_sentinel.report_schema.validate_final_report()`로 final_report contract를 검사하고, 보고서에 아래 필드를 포함한다.

```json
"schema_validation": {
  "schema_version": "compliance-sentinel-final-report/v2",
  "passed": true,
  "errors": []
}
```

참조 스키마: `docs/final-report-schema.json`

## 4. F1 입력 접수 보정

예선 MVP는 텍스트 단일 입력을 허용하며, 언어/채널/상품/타깃은 자동 추론 후 `input_completeness`에 명시한다. 운영형 폼에서는 해당 필드를 필수값으로 전환한다.

```json
"review_request_id": "RR-...",
"input_completeness": {
  "accepted": true,
  "mode": "text_only_demo_with_inferred_metadata",
  "provided_fields": ["content"],
  "requires_form_completion_for_production": false
}
```

## 5. Runtime Guard 표기 보정

실시간 hot path에는 경량 guard가 적용된다.

- prompt injection pattern
- secret-like token
- non-allowlisted URL

단, AgentShield/AgentLoop/AgentCompiler는 현재 기본 decision path가 아니라 opt-in/본선 고도화/운영 gate로 표기한다.
