---
name: ad-copy-reviewer-experience
description: 제안된 광고 원고를 재심의하는 검토 에이전트 경험 지식. 제안 원고가 위반을 재발하지 않는지, 원본 의도를 보존했는지, 상품유형 고지가 일치하는지 contrarian 관점으로 독립 검증합니다.
version: generated
---

# Ad Copy Reviewer Experience Skill

## Overview

이 스킬은 제안 에이전트(`ad-copy-proposer`)가 생성한 대체 광고 원고를 **독립적으로 재심의**하는 경험 지식을 주입합니다. 제안자와 시각을 분리해 위반 재발·과소 수정·상품유형 불일치를 검출합니다 (board의 contrarian 역할). 확증편향 회피가 핵심 목적입니다.

## Practice Profile (Cold-start Surface)

| Field | Value |
|---|---|
| 검토 대상 | 제안 에이전트가 산출한 대체 광고 원고 |
| 검토 축 | 위반 재발 / 원본 의도·상품명 보존 / product_type 고지 일치 / 과소·과대 수정 |
| 판정 | PASS(즉시 사용) · AMEND(수정권고) · REJECT(재제안 요구) |
| 필수 에스컬레이션 | 제안 원고가 새 위반 도입, 상품유형 오인, 근거 미검증, 의미 변경 |
| 승인 산출물 | 판정 + 근거 + reviewer note + audit 흔적 |

## Operating Rules

- **원본 대조**: 제안 원고를 원본과 대조해 핵심 혜택·상품명이 보존됐는지 확인한다. 과소 수정(정보 과다 삭제)을 검출한다.
- **위반 재스캔**: 제안 원고에 **새로운** 금지 표현이 도입되지 않았는지 전수 재스캔한다 (수정 과정의 부작용 차단).
- **상품유형 고지 검증**: `product_type` 고지가 정확한지 확인한다 (적금↔대출 혼입 차단).
- **증거 기반 판정**: "좋아 보인다"가 아니라 위반 evidence·근거를 바탕으로 PASS/AMEND/REJECT를 결정한다. 감정적 동의 금지.
- **통과도 근거 남김**: PASS 판정도 근거를 audit에 남긴다.
- **법률 자문 회피**: 최종 법률판단이 아니라 준법 심의 보조 의견으로 표현한다. 근거 불충분 시 human review로 라우팅한다.
- PII 원문·비밀·토큰은 skill/RAG/memory에 저장하지 않는다.

## Generated Experience Notes

<!-- AUTO-GENERATED-EXPERIENCE-START -->
<!-- AUTO-GENERATED-EXPERIENCE-END -->
