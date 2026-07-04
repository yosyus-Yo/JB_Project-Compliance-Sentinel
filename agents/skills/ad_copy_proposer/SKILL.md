---
name: ad-copy-proposer-experience
description: 금융 마케팅 광고 원고 제안 에이전트 경험 지식. 심의 통과/반려 후 위반 표현을 제거하고 상품명·핵심 혜택을 보존한 안전한 대체 광고 원고를 제안하는 절차/원칙을 내부 에이전트에 주입합니다.
version: generated
---

# Ad Copy Proposer Experience Skill

## Overview

이 스킬은 심의된 광고 콘텐츠에 대해 위반 표현을 제거하고 컴플라이언트한 **대체 광고 원고**를 제안하는 경험 지식을 주입합니다. `marketing_rewrite`의 확장이며, 법률 자문이 아니라 준법 심의 보조 관점의 재작성안을 생성합니다. 제안 후에는 반드시 검토 에이전트(`ad-copy-reviewer`)의 재심의를 거칩니다.

## Practice Profile (Cold-start Surface)

운영 전 다음 항목을 JB 내부 기준으로 채웁니다. 문서 ingest가 이 영역을 덮어쓰지 않도록 수동 관리합니다.

| Field | Value |
|---|---|
| 상품 범위 | 예금/적금/대출/카드/투자/보험 및 신규 상품군 |
| 채널 범위 | 배너/앱푸시/SNS/이메일/랜딩/고지문 |
| 제안 원칙 | 위반 제거 + 상품명 보존 + product_type 일치 고지 + 과장→조건부 표현화 |
| 필수 에스컬레이션 | 상품유형 불명확, 근거 미검증, CRITICAL 위반, 원본 정보 부족 |
| 승인 산출물 | 대체 원고(rewritten), 제거된 표현, 추가된 필수 고지, 근거 |

## Operating Rules

- **상품명 보존**: 원본 상품명(예: "JB 슈퍼적금")을 그대로 유지한다. "JB 금융 상품" 같은 일반 명칭으로 뭉뚱그리지 않는다.
- **상품 유형 일치 고지**: `product_type`에 해당하는 고지만 추가한다. 적금(deposit)에 "대출 한도·상환 조건" 같은 여신 고지를 혼입하지 않는다 (반대도 금지).
- **위반 완전 제거**: findings의 모든 위반 표현(evidence)을 제거하거나 안전 대체한다. 동의어·암시도 제거한다.
- **과장 표현 안전화**: 확정 수익률·원금 보장 등 보장 표현은 "조건에 따라 달라질 수 있음"으로 표현화한다.
- **날조 금지**: 원본에 없는 정보(수치·혜택)를 새로 지어내지 않는다.
- **필수 고지 inject**: 예금→예금자보호 한도, 대출→심사 결과에 따른 변동/신용도 영향, 투자→원금 손실 가능성.
- **검토 연계**: 제안 산출물은 곧바로 사용하지 않고 `ad-copy-reviewer`의 재심의(PASS/AMEND/REJECT)를 거친다.
- PII 원문·비밀·토큰은 skill/RAG/memory에 저장하지 않는다.

## Generated Experience Notes

<!-- AUTO-GENERATED-EXPERIENCE-START -->
<!-- AUTO-GENERATED-EXPERIENCE-END -->
