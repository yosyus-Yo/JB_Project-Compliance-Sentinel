# UI Redesign Plan — 구현 계획

> **Spec**: `docs/ui-redesign/spec.md`
> **Branch**: `benchmark-aieev-2026-05-21` (현재)
> **Approach**: 단일 Opus + Codex 1회 리뷰 (사용자 합의)

---

## 진행 단계 (turn 별)

| Turn | 단계 | 산출물 | 예상 비용 |
|:-:|---|---|---|
| 1 (완료) | spec + plan + tasks 작성 | 본 3파일 | 낮음 (메인 토큰만) |
| 2 (다음) | **P0×2 구현** | streamlit_app.py 사이드바 + 결과 카드화 | 중 |
| 3 | **P1×3 구현** | 9-step + 6인 보드 + 한글화 + 다국어 | 중-높음 (변경 많음) |
| 4 | **P2 + CSS 다듬기 + Impeccable 토큰 적용** | 커스텀 CSS 추가 | 중 |
| 5 | **UI 동작 검증 + 회귀** | 브라우저 확인 + pytest | 낮음 (API 0, deterministic) |
| 6 | **Codex 독립 리뷰 1회** | `/codex:rescue` cross-model | LLM 1회 |
| 7 | **배포** (commit + push) | benchmark 브랜치 반영 | 낮음 |

각 turn 사이 사용자 승인 게이트. "OK" 받으면 다음 turn.

---

## 파일 영향도

### 주 변경 파일

| 파일 | 변경 영역 | 비고 |
|---|---|---|
| `apps/streamlit_app.py` (575줄) | L354-394 (sidebar), L85-149 (render_*), 신규 함수 +200줄 | 핵심 |
| `apps/streamlit_app.py` 내 CSS | `st.markdown(STYLE_CSS, unsafe_allow_html=True)` | 새 모듈 변수 |

### 참고 (read-only)

| 위치 | 용도 |
|---|---|
| `/Users/seohun/Downloads/UI개선요청서_250522.md` | spec source |
| `/Users/seohun/Documents/에이전트/infiniteAgent/Impeccable-Design-System/design-systems/` | 디자인 토큰 추출 (색/spacing) |
| 기존 `apps/streamlit_app.py` render_* | 패턴 유지, 점진 교체 |

### 변경 안 함

- `src/compliance_sentinel/marketing_workflow.py` 등 비즈니스 로직 (UI는 view layer)
- `final_report` 스키마 (UI가 적응)
- pytest (회귀 검증만, 새 테스트는 P0~P2 안정화 후)

---

## Turn 2 — P0×2 상세 (다음 turn 즉시 진행 항목)

### P0-1 사이드바 단순화

**변경 위치**: `apps/streamlit_app.py` L354-394 `main()` 안 `with st.sidebar:` 블록

**Before** (현재 추정):
```python
with st.sidebar:
    st.header("설정")
    if st.button("⚙️ 설정창 열기", type="primary"): ...
    st.header("전문가 문서 주입")
    file = st.file_uploader(...)
    if st.button("문서 주입 실행", type="primary"): ...
    # 샘플 / Memory 승인 등 모두 노출
```

**After**:
```python
with st.sidebar:
    # 기본 (항상 보임)
    st.subheader("입력 도우미")
    sample = st.selectbox("샘플 문구", SAMPLES)
    if st.button("샘플 불러오기", use_container_width=True):
        st.session_state.input_text = sample
    if st.button("⚙️ 설정", use_container_width=True):  # type="primary" 제거
        st.session_state.show_settings = True

    st.divider()

    # 관리자 도구 (접힘)
    with st.expander("⚙️ 관리자 도구", expanded=False):
        st.caption("전문가/관리자 전용")
        # 전문가 문서 주입
        file = st.file_uploader(...)
        if st.button("문서 주입 실행", use_container_width=True):  # secondary
            ...
        # Memory 승인 등
```

**검증 (AC)**:
- AC-1.1 첫 화면에 3개만 보이는지 — 브라우저
- AC-1.2 관리자 도구 expanded=False — 코드 + 브라우저
- AC-1.3 1280×800 스크롤 없음 — 브라우저

### P0-2 결과 카드화

**신규 함수** (`apps/streamlit_app.py` 상단 render_* 영역에 추가):
```python
APPROVAL_KOR = {
    "APPROVED": ("✅ 승인", "🟢"),
    "CONDITIONAL_APPROVAL": ("⚠️ 조건부 승인", "🟡"),
    "REJECTED": ("❌ 반려", "🔴"),
    "HUMAN_REVIEW_REQUIRED": ("👤 사람 검토 필요", "🟠"),
}
RISK_COLOR = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}

def render_verdict_card(report: dict) -> None:
    """판정 배지 카드 (최상단)."""
    approval = report.get("approval_status", "")
    risk = report.get("risk_level", "")
    confidence = report.get("confidence_score", 0)
    audit_id = report.get("audit_log_id", "")
    kor, color = APPROVAL_KOR.get(approval, (approval, "⚪"))
    risk_emoji = RISK_COLOR.get(risk, "⚪")
    # st.markdown 카드 HTML
    ...

def render_finding_cards(findings: list[dict]) -> None:
    """위험 표현 카드들 (중간)."""
    for f in findings:
        severity = f.get("severity", "MEDIUM")
        risk_emoji = RISK_COLOR.get(severity, "⚪")
        # 카드: 표현 + 문제 + 수정안
        ...
```

**기존 변경**: L146 `render_json_sections` → "개발자 정보" expander 안으로 (AC-2.4)

**검증 (AC)**:
- AC-2.1~2.4 — 브라우저 + 코드 grep ("approval_status" 같은 영어 키가 화면 노출 안 되는지)

---

## Impeccable Design System 참조 방법

**Read-only 참조** (직접 import 불가 — TS/Bun 프로젝트 vs Python):

1. `design-systems/` 디렉토리에서 금융권 + 다크 톤 브랜드 1-2개 식별 (Stripe, Linear, Vercel 등 추정)
2. 그 브랜드의 `tokens.json` 또는 `DESIGN.md`에서 다음만 추출:
   - **Primary/Secondary 색상값** (hex)
   - **간격 (spacing)** scale
   - **타이포그래피** (font-size, line-height, weight)
   - **카드 경계 (border-radius, border-color, shadow)**
3. 추출한 토큰을 Streamlit `STYLE_CSS` 변수에 inline:
   ```python
   STYLE_CSS = """
   <style>
   .verdict-card { background: #0d1b2a; padding: 16px 20px; border-radius: 12px; ... }
   .finding-critical { border-left: 4px solid #ef4444; ... }
   </style>
   """
   ```

**제한**: Impeccable의 React 컴포넌트는 사용 불가. **CSS 디자인 토큰**만 참조.

---

## 위험 / 롤백

| 위험 | 대응 |
|---|---|
| Streamlit `unsafe_allow_html=True` XSS | 사용자 입력은 escape 후 표시 (`html.escape`) |
| 기존 deterministic 분석 회귀 | pytest 188 passed 매 turn 확인 |
| Impeccable 토큰 부재/접근 불가 | 자체 디자인 토큰 fallback (현재 다크 네이비 톤 기반) |
| 시연 6/5 마감 압박 → 품질 저하 | P0×2를 최우선으로 완성, P1·P2는 시간 허용 시 |

**롤백**: 각 turn 단위 git commit → 문제 시 `git revert <hash>` 또는 brunch 이전 push로 강제 X (사용자 승인 후만)

---

## 완료 기준 (전체)

- [ ] AC 6개 항목 (P0×2 + P1×3 + P2×1) 모두 ✅
- [ ] pytest 188 passed 회귀 없음
- [ ] 브라우저(Chrome) E2E — 사이드바 단순 / 카드 / 9-step / 6인 보드 / 다국어 / 디자인 톤 6개 다 시각 확인
- [ ] Codex cross-model 리뷰 1회 (PASS 또는 NEEDS_WORK 정리 후 fix)
- [ ] benchmark 브랜치 commit + push 완료
