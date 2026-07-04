# UI Redesign Tasks — Checklist

> **Spec**: `docs/ui-redesign/spec.md` | **Plan**: `docs/ui-redesign/plan.md`
> **완료 기준**: 모든 ✅ + Codex 리뷰 PASS + benchmark push

---

## Turn 2 — P0×2 구현 (다음 turn)

### P0-1 사이드바 단순화 (AC-1.1~1.3)
- [ ] T2-1.1 `apps/streamlit_app.py` L354-394 `main()` 안 sidebar 블록 백업 (gpt-5.5 fix와 함께 같은 commit 전 working copy)
- [ ] T2-1.2 기본(항상 보임) 영역: 샘플 선택 + 샘플 불러오기 + 설정 진입 (3개만)
- [ ] T2-1.3 관리자 도구 `st.expander("⚙️ 관리자 도구", expanded=False)` 안으로 이동 (문서 주입 / 출처 라벨 / Memory 승인)
- [ ] T2-1.4 메인 액션이 아닌 버튼은 `type` 미지정 또는 `use_container_width=True`만 (빨강 제거)
- [ ] T2-1.5 자체 검증: pytest 188 passed 회귀 없음

### P0-2 결과 카드화 (AC-2.1~2.4)
- [ ] T2-2.1 모듈 상단에 `APPROVAL_KOR`, `RISK_COLOR` 매핑 dict 추가
- [ ] T2-2.2 `render_verdict_card(report)` 신규 — 한글+영문 병기, 색상 emoji, 신뢰도, 감사 ID
- [ ] T2-2.3 `render_finding_cards(findings)` 신규 — 각 finding을 카드 1개로 (표현 + 문제 + 수정안)
- [ ] T2-2.4 `main()`의 결과 렌더 흐름 교체: 카드 → 카드 → "개발자 정보" expander 안에 raw JSON
- [ ] T2-2.5 `render_json_sections` 호출은 "개발자 정보" expander 안에만 (기본 접힘)
- [ ] T2-2.6 자체 검증: 브라우저에서 영어 키(`approval_status` 등) 본문에 안 보임 확인

### Turn 2 종료 게이트
- [ ] pytest 188 passed
- [ ] 사용자에게 진행 상황 보고 + 다음 turn (P1) 승인 요청

---

## Turn 3 — P1×3 구현

### P1-3 9-step + 6인 보드 시각화 ⭐ (AC-3.1~3.3)
- [ ] T3-3.1 `render_workflow_progress(state_or_report)` 신규 — 9단계 진행 표시 (✅🔄❌)
  - 단계: PII 제거 → 분류 → 법령 검색 → 6인 보드 → CEO 종합 → Verifier 검증 → 승인 라우팅 → 외부 공유 → 감사 로그
- [ ] T3-3.2 `render_board_table(board_diagnostics)` 신규 — 6명 위원 표 (위원/판정/의견)
  - 6명: 법률 자문 / 개인정보(PIPA) / 소비자보호 / 운영 리스크(AML) / 업무 실무성 / 반론자(Contrarian)
- [ ] T3-3.3 HIGH/CRITICAL 행은 배경색 강조
- [ ] T3-3.4 `st.expander("🔍 심의 과정 9단계 보기")` 안에 두 신규 함수 배치
- [ ] T3-3.5 데이터 매핑 검증: `final_report.board_diagnostics` 또는 `state.llm_calls` 실제 키 확인 (Read marketing_workflow.py)

### P1-4 한글화 (AC-4.1~4.2)
- [ ] T3-4.1 `FIELD_LABELS_KOR` dict 추가 (영문 키 → 한글 라벨 8개)
- [ ] T3-4.2 모든 render_* 함수에서 사용자 노출 영문 키를 `FIELD_LABELS_KOR.get(key, key)`로 치환
- [ ] T3-4.3 grep으로 본문 노출 영문 키 0건 확인 (개발자 expander 제외)

### P1-5 다국어 결과 명확화 (AC-5.1~5.2)
- [ ] T3-5.1 `LANGUAGE_FLAGS` dict — 언어 코드 → 깃발 emoji 매핑 (ko/en/zh/vi 등)
- [ ] T3-5.2 `render_multilingual_findings(findings)` 신규 — 언어별 그룹핑 + 깃발
- [ ] T3-5.3 다국어 입력 테스트 케이스로 검증 (한국어 + 영어 + 중국어 혼합)

### Turn 3 종료 게이트
- [ ] pytest 188 passed
- [ ] 브라우저에서 9단계/6인 보드/한글화/다국어 시각 확인
- [ ] 사용자 보고 + 다음 turn (P2 + CSS) 승인

---

## Turn 4 — P2 디자인 톤 + CSS + Impeccable

### P2-6 디자인 톤 정리 (AC-6.1~6.4)
- [ ] T4-6.1 모든 버튼 grep — 빨강(`type="primary"`)은 "준법 심의 실행" 1개만 유지, 나머지 제거/secondary
- [ ] T4-6.2 모듈 상단 `STYLE_CSS` 변수 추가 — 카드 테두리/여백/폰트
- [ ] T4-6.3 `main()` 시작에 `st.markdown(STYLE_CSS, unsafe_allow_html=True)` 호출
- [ ] T4-6.4 Impeccable `design-systems/` 디렉토리 탐색 → 금융권 다크 톤 브랜드 1-2개 식별
- [ ] T4-6.5 색상값/spacing/타이포 토큰 추출하여 STYLE_CSS에 반영
- [ ] T4-6.6 다크 네이비 톤 유지 (MVP 제안서와 통일)

### Turn 4 종료 게이트
- [ ] pytest 188 passed
- [ ] 브라우저 시각 확인 — 빨강 버튼 1개, 카드 디자인 정돈
- [ ] 사용자 보고 + 다음 turn (검증) 승인

---

## Turn 5 — UI 동작 검증 + 회귀

- [ ] T5-1 브라우저 E2E (Chrome) — 6항목 시각 체크
- [ ] T5-2 분석 1건 — REJECTED/CRITICAL 케이스 + APPROVED 케이스 + 다국어 케이스 3종
- [ ] T5-3 pytest 188 passed 최종
- [ ] T5-4 deterministic 모드와 live LLM 모드 둘 다 동작 확인 (live는 비용 우려로 사용자에게 위임)
- [ ] T5-5 시연 시 흐름 시뮬레이션 — 문구 입력 → 결과 카드 → "심의 과정 9단계 보기" 펼치기 (요청서 §시연 흐름 참조)

---

## Turn 6 — Codex 독립 리뷰

- [ ] T6-1 `/codex:rescue UI 구현 검토 — 6 AC 충족 여부` 호출 (cross-model 1회)
- [ ] T6-2 Codex 피드백 정리 — PASS / NEEDS_WORK 항목 분류
- [ ] T6-3 NEEDS_WORK 항목 즉시 fix (turn 안에서)

---

## Turn 7 — 배포

- [ ] T7-1 git status 확인 — uncommitted 모두 검토
- [ ] T7-2 commit: `feat(ui): UI/UX 개선 — 6항목 (P0×2 + P1×3 + P2×1)` (또는 단계별 분리)
- [ ] T7-3 push origin benchmark-aieev-2026-05-21
- [ ] T7-4 사용자에게 GitHub 반영 확인 안내

---

## 완료 판정

- [ ] AC 6항목 모두 ✅
- [ ] 모든 Turn 종료 게이트 통과
- [ ] Codex 리뷰 PASS (또는 NEEDS_WORK 0건)
- [ ] benchmark 브랜치 origin push 반영 확인
- [ ] 시연 영상 촬영(6/5) 가능 상태
