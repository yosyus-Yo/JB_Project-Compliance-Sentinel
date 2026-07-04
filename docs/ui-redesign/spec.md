# UI Redesign Spec — Acceptance Criteria

> **Source**: `/Users/seohun/Downloads/UI개선요청서_250522.md` (PM, 2026-05-22)
> **Deadline**: 시연 영상 촬영 전 (6/5)
> **Scope**: `apps/streamlit_app.py` + 커스텀 CSS
> **참고**: `/Users/seohun/Documents/에이전트/infiniteAgent/Impeccable-Design-System` (디자인 토큰만 read-only 참조)

---

## P0-1: 사이드바 단순화 (관리자 기능 접기)

**문제**: 첫 화면 사이드바에 설정창/전문가 문서 주입/Memory 승인 등 관리자 기능이 모두 노출돼 심사위원에게 "복잡한 어드민 도구" 인상.

**AC**:
- [ ] AC-1.1 사이드바 **첫 화면**에 보이는 항목 = (a) 샘플 문구 선택 (b) 샘플 불러오기 (c) 설정창(API키) 진입 버튼 — **이 3개만**
- [ ] AC-1.2 "전문가 문서 주입 / 출처 라벨 / Memory 승인" 3종은 `st.expander("⚙️ 관리자 도구", expanded=False)` 안으로 이동 — **접힌 상태**가 기본
- [ ] AC-1.3 사이드바 전체 세로 길이 단축 — 펼치기 전 첫 화면에 스크롤 없이 보여야 함 (1280×800 기준)

**검증**: 브라우저에서 첫 진입 시 관리자 도구가 접혀 있고, expander 클릭해야 펼쳐짐

---

## P0-2: 결과 화면 카드화 (raw JSON 제거)

**문제**: 심의 실행 후 raw JSON이 그대로 노출됨. 준법전문가·심사위원 둘 다 JSON을 읽고 싶어하지 않음.

**AC**:
- [ ] AC-2.1 결과 **최상단 = 판정 배지** (크게):
  - 한글 + 영문 병기 (예: "❌ **반려** (REJECTED)")
  - 위험도 배지 (🟢 LOW / 🟡 MEDIUM / 🟠 HIGH / 🔴 CRITICAL)
  - 신뢰도 + 감사 ID inline
  - 승인상태별 색: 승인 🟢 / 조건부승인 🟡 / 반려 🔴 / 사람검토 🟠
- [ ] AC-2.2 **중간 = 위험 표현 카드** — 각 finding을 카드 1개로:
  - 헤더: severity 색 + 표현 + severity 배지
  - 본문: 문제 설명 + 수정안 (한 카드 안에)
- [ ] AC-2.3 **하단 = "상세 보기" expander** (심사위원용, AC-3 워크플로우 시각화로 연결)
- [ ] AC-2.4 raw JSON expander는 **"개발자 정보" expander 안에만** (기본 접힘, 보고싶은 사람만)

**검증**: 분석 1건 실행 → 화면에 JSON 키(`approval_status`, `risk_level` 같은 영어 키)가 직접 노출되지 않아야

---

## P1-3: 9-step 워크플로우 + 6인 보드 시각화 ⭐ (차별화 핵심)

**문제**: 9단계 과정과 6인 보드가 화면에 안 보임 → 심사위원이 "그냥 챗봇"으로 오해.

**AC**:
- [ ] AC-3.1 `st.expander("🔍 심의 과정 9단계 보기")` 안에 가로 진행 표시:
  ```
  ✅ PII 제거 → ✅ 분류 → ✅ 법령 검색 → ✅ 6인 보드 →
  ✅ CEO 종합 → ✅ Verifier 검증 → ✅ 승인 라우팅 → ✅ 외부 공유 → ✅ 감사 로그
  ```
  - 완료된 단계는 ✅, 진행 중은 🔄, 실패는 ❌
  - 단계 수: **9개 고정** (요청서 본문 명시)
- [ ] AC-3.2 6인 보드는 **표로** — `final_report.board_diagnostics` 데이터 매핑:
  | 심의 위원 | 위험 판정 | 의견 |
  - 6명: 법률 자문 / 개인정보(PIPA) / 소비자보호 / 운영 리스크(AML) / 업무 실무성 / 반론자(Contrarian)
  - 각자 다른 판정/의견이 보여야 (다관점 심의 차별화)
- [ ] AC-3.3 6인 중 위험판정 HIGH/CRITICAL은 색으로 강조

**검증**: 분석 1건 실행 → "심의 과정 9단계 보기" 클릭 → 9단계 진행바 + 6인 보드 표가 보임. 6명의 판정이 모두 같지 않아야 함 (다관점 시각화)

---

## P1-4: 한글화 (전문 용어 친절하게)

**문제**: `verifier_result`, `approval_status`, `confidence_score` 등 영어 필드명이 화면에 그대로 노출.

**AC**:
- [ ] AC-4.1 화면 표시용 한글 라벨 매핑 적용 (코드 내부 필드명은 유지):
  | 영어 (코드) | 화면 표시 (한글) |
  |---|---|
  | approval_status | 승인 상태 |
  | risk_level | 위험도 |
  | confidence_score | 신뢰도 |
  | findings | 위험 표현 |
  | revision_suggestions | 수정 제안 |
  | verifier_result | 검증 결과 |
  | audit_log_id | 감사 번호 |
  | board_diagnostics | 심의 위원 의견 |
- [ ] AC-4.2 사용자 화면에 영어 키 노출 0건 (개발자 정보 expander 내부 제외)

**검증**: 결과 화면 본문에 `approval_status`, `findings` 같은 snake_case 영어 키가 안 보여야

---

## P1-5: 다국어 결과 명확화

**문제**: Case B(다국어 입력) 결과가 불명확.

**AC**:
- [ ] AC-5.1 다국어 위험 표현 → 언어 깃발 + 표현 형식:
  ```
  🇰🇷 한국어: (위험 표현 없음)
  🇺🇸 영어: "zero risk" — 무위험 과장
  🇨🇳 중국어: "零风险" — 무위험 과장
  🇻🇳 베트남어: "không rủi ro" — 무위험 과장
  ```
- [ ] AC-5.2 finding의 `language` 또는 감지된 텍스트 언어에 따라 깃발 자동 부여

**검증**: 다국어 입력 (예: "원금 보장 + zero risk + 零风险") 분석 → 언어별 그룹핑 표시

---

## P2-6: 디자인 톤 정리

**문제**: 빨강 버튼이 3개(설정창/문서주입/심의실행) → 무엇이 주요 액션인지 불명확. Streamlit 기본 디자인 빈약.

**AC**:
- [ ] AC-6.1 **빨강 = "준법 심의 실행" 메인 버튼 1개만** — 나머지(설정창/문서주입)는 중립(secondary 또는 회색)
- [ ] AC-6.2 카드 테두리·여백·폰트 정돈 — 커스텀 CSS (`st.markdown(unsafe_allow_html=True)`)
- [ ] AC-6.3 다크 네이비 톤 유지 (금융권 + MVP 제안서 표지 통일감)
- [ ] AC-6.4 Impeccable Design System의 금융권 디자인(있다면) **토큰만 참조** — 색상값/spacing/typography를 streamlit CSS에 inline (직접 import 아님, TypeScript와 Python 호환 안 됨)

**검증**: 첫 화면에서 빨강 버튼은 "준법 심의 실행" 1개만 보여야

---

## 비-기능 요구사항

- [ ] NF-1 기존 deterministic 분석 동작 유지 (pytest 188 passed 회귀 없음)
- [ ] NF-2 기존 LLM 호출 경로 유지 (CS_ENABLE_LLM_RUNTIME=1 + 키 → 실호출)
- [ ] NF-3 시연 환경: 한국어 + Chrome/Safari (Korean rendering 확인)
- [ ] NF-4 데이터 흐름: `MarketingContentReviewAgent().analyze(text).final_report` 그대로 활용 — UI는 view layer만

---

## 검증 수준 (Spec 자체)

| 항목 | 수준 | 근거 |
|---|---|---|
| 6항목 모두 요청서 직접 인용 | [검증됨] | `UI개선요청서_250522.md` 라인 직접 매핑 |
| streamlit_app.py 현 구조 | [검증됨] | 575줄, render_* 함수 위치 grep 확인 |
| `board_diagnostics` 데이터 형태 | [추정] | analyze() 결과 키 추정, 다음 turn 실제 키 검증 필요 |
| Impeccable token 추출 가능 여부 | [미확인] | 다음 turn에서 design-systems/ 디렉토리 확인 필요 |
