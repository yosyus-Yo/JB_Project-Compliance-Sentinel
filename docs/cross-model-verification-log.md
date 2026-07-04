# Cross-Model 독립검증 실행 로그

> **목적**: "검증 주체가 대상 시스템 내부에 있어 self-verified"라는 지적에 대한 실증. 별도 critic 모델(`claude-opus-4-8`)이 1차 심의 결과를 **독립 컨텍스트**에서 재검증한 실제 실행 기록.
> **실행일**: 2026-07-04 · **비용**: ~$0.05/건 (`estimated_cost_usd`)

## 재현 방법

```bash
# .env 또는 셸에 3개 조건 설정 (ANTHROPIC_API_KEY는 각자 발급)
export CS_ENABLE_LLM_RUNTIME=1
export CS_USE_LLM_BOARD_VERDICTS=1
export ANTHROPIC_API_KEY=<your-key>

PYTHONPATH=src python3 -m compliance_sentinel.cli --json \
  "JB 슈퍼적금 출시! 누구나 연 8% 확정 수익, 원금 보장!" \
  | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['cross_model_result'], ensure_ascii=False, indent=2))"
```

키가 없으면 `cross_model_result.enabled=false` (deterministic 모드, 정상 폴백). 키가 있으면 아래처럼 실제 critic 재검증이 실행된다.

## 실행 결과 (실측)

- **입력**: `JB 슈퍼적금 출시! 누구나 연 8% 확정 수익, 원금 보장!`
- **1차 심의**: 6인 보드(`claude-sonnet-5`) → CEO 종합/검증(`claude-opus-4-8`), findings MF-001~004
- **독립 critic**: `claude-opus-4-8` (별도 컨텍스트, `deterministic_fallback: false`)
- **종합 판정**: `cross_model_confidence: PARTIAL` · `recommendation: human_review_recommended` · `level: STRONG`

### 합의 (agreed_findings)
4개 finding 전부 존재 자체는 합의: `MF-001, MF-002, MF-003, MF-004`

### 이견 (disputed_findings) — critic이 severity 상향 권고
| finding | 1차 판정 | critic 견해 | 근거 |
|---|---|---|---|
| MF-001 | PARTIAL | **FAIL** | '원금 보장'+적금인데 예금자보호 한도 고지 없이 무조건 원금보장 단정 → 자본시장법·금소법상 오인유발 광고 |
| MF-002 | PARTIAL | **FAIL** | '연 8% 확정 수익'은 비현실적 고금리+확정표현 → 금소법 제22조 부당광고 명백 |
| MF-003 | PARTIAL | PARTIAL | '누구나'는 심사·우대조건 충돌 소지 (타당), 단 확정수익 결합 시 오인 가중 반영 권고 |

### critic이 잡은 blind spot (self-verify가 놓친 영역)
1. **조문 환각 가능성** — 금소법 "허위·과장 광고 금지" 조문 번호/제목 정합성 미검증 (LLM 환각 위험)
2. **예금자보호법 교차검토 누락** — '원금 보장'을 금소법으로만 판단, 예금자보호 한도(5천만원) 고지의무 + 자본시장법 투자권유 규제 누락
3. **factual claim 실증 미확인** — 연 8% 확정 표현의 실제 약관 대조 없이 표현 리스크로만 처리
4. **과소평가 정황** — verifier_output이 비어 모든 finding이 PARTIAL로 하향 통일된 정황 (critical 콘텐츠 대비 과소평가 위험)

## 해석

- 독립 critic이 **동일 모델 계열의 self-verify가 놓친 4개 blind spot을 포착**했고, 2개 finding의 severity 상향을 권고했다. cross-model 검증이 형식이 아니라 **실질적 오류 교정 기능**을 함을 보인다.
- `recommendation: human_review_recommended` — 시스템이 스스로 "사람 검토 필요"로 라우팅한 것도 설계대로 동작.
- 본 로그는 단일 실행 샘플이다. 운영 시 critical 심의마다 자동 부착(`level: STRONG`)되며, 비용은 건당 ~$0.05.
