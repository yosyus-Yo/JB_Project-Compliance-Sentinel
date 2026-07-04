# Marketing 자가교정 폐쇄 루프 (Revise Loop) — 방식 C 하이브리드 설계

> **목적**: PDF 제안서 F-04 "수정안 재생성 → 보드 재검토(≤3회) → 통과 보장"을 **광고(marketing) 경로**에 구현.
> 현재 compliance(약관) 경로에만 revise loop가 있고 광고 경로는 1회 제안만 함 (갭).
>
> **방식 C (하이브리드)**: Delta 재심의(저비용) + 미해소 시 재교정 반복. 풀 6인 보드 재호출 대신 1 LLM 위험 스캔.

## 1. 현재 구조 (직선, revise 없음)

```
content_intake → understand_content → memory_review → llm_advisory_board
→ synthesize → independent_validation → human_review_gate → final_report → END
```

- `final_report` 노드(_make_final) 안에서 `generate_marketing_rewrite` **1회 호출만** — 보드 재검토 없음.

## 2. 목표 구조 (revise loop 추가)

```
synthesize → [revise_gate 조건분기]
  ├ 경미(APPROVED/APPROVE_WITH_CHANGES, HIGH/CRITICAL 없음) ──→ independent_validation (기존 직선)
  └ 심각(REJECTED 또는 HIGH/CRITICAL finding) + retry<3 →
       rewrite_loop  (수정안 생성, generate_marketing_rewrite)
       → delta_screen (수정안의 신규 위험만 1 LLM 스캔, llm_detect_risk_findings)
       → [revise_branch 조건분기]
            ├ 신규 CRITICAL/HIGH 없음        → independent_validation (통과, APPROVE_WITH_CHANGES)
            ├ 신규 위험 有 + retry<3          → rewrite_loop (루프 백엣지, retry+1)
            └ retry≥3                         → human_review_gate (HUMAN_REVIEW_REQUIRED 강제)
```

## 3. 재사용 빌딩블록 (이미 존재 — 신규 구현 최소화)

| 함수 | 역할 | 시그니처 |
|------|------|----------|
| `generate_marketing_rewrite` | 수정안 생성 | `(text, findings, *, product_type, channel, language, llm_client, role) → dict\|None` |
| `llm_detect_risk_findings` | **Delta 위험 스캔** (docstring "방안 C") | `(text, existing_findings, *, language, channel, product_type, llm_client) → list[MarketingFinding]` |
| `decide_approval` | 승인 판정 | `(findings, language) → str` |
| `risk_level` | 위험 등급 | `(findings) → "LOW"\|"MEDIUM"\|"HIGH"\|"CRITICAL"` |

## 4. State 필드 추가

```python
retry_count: NotRequired[int]          # revise 루프 횟수 (≤3 bounded)
revised_text: NotRequired[str]         # 현재 수정안 텍스트
revised_marketing_rewrite: NotRequired[dict]  # 통과한 수정안 (final_report에 주입)
revise_trace: NotRequired[list]        # 각 루프 trace (audit 용)
```

## 5. 비용 비교

| 방식 | 재검토 비용/루프 | 최대(3회) |
|------|------------------|-----------|
| 풀 보드 재검토 (PDF 문구 그대로) | 5 LLM | +15 LLM |
| **방식 C (Delta)** | rewrite 1 + delta 1 = 2 LLM | +6 LLM |

→ 약 60% 절감 [추정, 실측 필요]. "통과까지 ≤3회 + 초과 시 HITL" PDF 요구는 그대로 충족.

## 6. Task 분해

| Task | 내용 | 파일 | 리스크 |
|------|------|------|--------|
| **T1** | State 필드 추가 + final_report의 rewrite 로직을 helper(`_compute_marketing_rewrite`)로 추출. **그래프 미변경, 기존 동작 100% 보존** | marketing_langgraph_adapter.py | 낮음 |
| **T2** | `rewrite_loop` 노드 + `delta_screen` 노드 추가 (helper/llm_detect 재사용) | marketing_langgraph_adapter.py | 중 |
| **T3** | `_revise_gate` / `_revise_branch` 조건분기 + 그래프 엣지 재구성 (루프 백엣지) | marketing_langgraph_adapter.py | 중 |
| **T4** | revise_trace audit 기록 + final_report에 통과 수정안 주입 | marketing_langgraph_adapter.py | 낮음 |
| **T5** | 통합 테스트 — CASE A('원금 보장 연 8% 확정') E2E: 수정안→delta→통과 + 8+α 노드 무결성 + deterministic fallback | tests/ | 낮음 |

## 7. 안전 원칙

- **deterministic 모드**: revise loop 진입해도 generate_marketing_rewrite/llm_detect가 `[]`/`None` 반환 → 무한루프 없이 즉시 탈출 (기존 fallback 보존).
- **retry_count ≥ 3 하드 차단**: compliance 경로의 `_verifier_branch` 패턴 동일.
- **심의 결과 불변**: rewrite는 보조 제안. 원본 findings/approval은 보존 (revise는 "더 나은 수정안 탐색"일 뿐 원 판정 약화 금지).
