# Compliance Sentinel — UI 기능 인벤토리 & 작동 상태

> **작성일**: 2026-06-01 · **대상**: `compliance-sentinel/` React UI (main `7fd7957` 기준, benchmark 머지 후)
> **목적**: "UI는 구현됐으나 기능이 없거나 mock/부분인" 요소를 전수 식별 → 개발자 작업 명세 + UI/UX 작업 체크리스트
> **방법**: 정적 코드 감사 3그룹(App.tsx / OperationsPanel / ReportView+컴포넌트) — 각 UI 액션의 핸들러 → API → server.ts 실동작 추적
> **작동 상태**: ✅작동(실 API+실동작) · 🟡부분(UI는 되나 뒤가 약함/일부만) · 🔴UI만(mock·장식·미연결)

---

## 🔴 완전 미작동 / mock — 우선 처리 대상

| # | 화면/영역 | 기능 | 무엇이 빠졌나 | 개발자 작업 | 근거 |
|---|----------|------|--------------|------------|------|
| **R1** | **인증/역할 (검토 권한 프로필)** | **역할별 UI·권한 분기** | 로그인하면 session.role은 바뀌나 탭/버튼/패널 어디도 role 기반 show/hide 없음. **3역할(ADMIN/COMPLIANCE/CONTENT_MANAGER) 동일 화면**. 삭제 버튼만 ADMIN 체크. | 역할별 화면 가드(CONTENT_MANAGER=운영탭 숨김, COMPLIANCE=Admin 숨김 등) + 핵심 액션(승인확정/삭제) 권한 게이트 | App.tsx:383(삭제만 role 체크), 나머지 role 무관 |
| **R2** | 분석 대시보드 | 평균 심의 속도 (avgDurationMs) | 서버가 항상 `0` 반환, 측정 로직 없음 → KPI 카드 "측정 미지원" | 리뷰 시작~완료 타임스탬프 측정 → `buildRealtimeMetrics()` 반영 | server.ts:2663, adapter.ts:421-422 |
| **R3** | 결과화면 / 감사함 | 검인필증·인증서 출력 (Print ×2) | `window.print()` 전체페이지 인쇄, 인증서 전용 CSS 없음 | `@media print`로 인증서 영역만 인쇄 or PDF 생성 | App.tsx:1552, 2595 |
| **R4** | Workflow 탭 | Notion live publish | 항상 `reason:'live_notion_not_enabled_in_react_bridge'` 하드코딩 false | Python `workflow_publishers` Notion 연동 구현 | server.ts:781-787 |
| **R5** | Workflow 탭 | Jira live publish | 동일 하드코딩 false | Jira REST 연동 구현 | server.ts:781-787 |
| **R6** | Workflow 탭 | HITL Resume 컨트롤 | 타임라인 표시만, Resume/승인/반려 버튼·엔드포인트 모두 없음 | `/api/workflow/resume` POST + HITL 버튼 + LangGraph checkpoint 계약 | OP:820-829, server.ts:578 `resume_endpoint_available:false` |
| **R7** | Workflow 탭 | LangGraph 체크포인트 | 상태 표시만, 실제 저장/복구 없음 | `LANGGRAPH_CHECKPOINT_PATH` 설정 + 체크포인트 구현 | server.ts:572-574 |
| **R8** | Knowledge 탭 | 지식 목록 조회/삭제 | ingest는 되나 기존 지식 열람·삭제 UI·엔드포인트 전무 | GET/DELETE `/api/knowledge` + 목록 컴포넌트 | server.ts에 `/api/knowledge` 없음 |
| **R9** | 결과화면 | 재심의 버튼 | 재심의 트리거 UI 없음 | 재심의 버튼 + `handleScreeningSubmit` 재호출 | ReportView.tsx 전체 |
| **R10** | (구조) | **死컴포넌트 3개** | `AuditHistory`·`DemoPanel`·`PipelineLoader`가 App.tsx에 **import 안 됨** → 화면에 안 뜸. App이 동일 기능 inline 중복 구현 | 컴포넌트 채택 or 중복 코드 정리(택1) | App.tsx import grep 0건; App.tsx:1274-1308(inline loader), :205-234(inline demo) |
| **R11** | 분석 대시보드 | 실시간 TPS 그래프 | Python worker 미실행 시 하드코딩 더미 데이터(18:50~55) 렌더 | 더미 제거 → 빈 상태 UI | App.tsx:2046-2053 |
| **R12** | 결과화면(DemoPanel) | "Python engine ready" 배지 | 하드코딩 텍스트, 실제 health 미반영 | `health.python_worker.status` 동적 연결 | DemoPanel.tsx:65 |

---

## 🟡 부분 작동 — 보강 필요

| # | 화면/영역 | 기능 | 무엇이 약한가 | 개발자 작업 | 근거 |
|---|----------|------|--------------|------------|------|
| Y1 | 인증 | 세션 유지 | `currentUiSession`이 인메모리 단일 변수 → 새로고침/멀티탭 시 소멸, 실 JWT/쿠키 없음 | express-session/쿠키 or JWT | server.ts:2554 |
| Y2 | Workflow | Slack publish | 키+`CS_ENABLE_WORKFLOW_PUBLISH=1`+`live=true` 모두 충족 시만 실전송, 기본 dry-run인데 UI 안내 없음 | 설정 상태/모드를 UI에 명시 | server.ts:748-778 |
| Y3 | Audit 탭 | 로그 필터링 | placeholder는 "status/route/text"인데 실제는 전체 JSON 문자열 검색만, 날짜/severity/route 구조화 필터 없음 | structured 필터 UI + 서버 파라미터 | OP:479, server.ts:596-609 |
| Y4 | Batch 탭 | fallback 경고 | Python 브리지 없을 때 local rule engine로 조용히 fallback(`dynamic:false`), 품질 저하 미표시 | fallback 시 경고 배너 | server.ts:496-498, OP 미사용 |
| Y5 | Batch 탭 | 25건 초과 방어 | 클라이언트 차단 없음(서버만 400), UX 없음 | item>25 시 버튼 disable/경고 | OP:891-895 |
| Y6 | 감사함 | 이력 "영구 삭제"/초기화 | 인메모리만 삭제, JSONL 영속파일은 의도적 보존 → 재시작 시 복원. UI에 범위 설명 없음 | "인메모리 삭제(재시작 시 복원)" 문구 | server.ts:2587-2610 주석 |
| Y7 | 결과화면 | "편집기에 적용"(onApplyRevision) | App.tsx가 ReportView를 직접 안 쓰고 inline 렌더 → 콜백 미연결 | 연결 or inline에 동등 기능 | ReportView.tsx:441 |
| Y8 | 결과화면 | RAG 법령 원문 링크 | `local://jb-internal/`는 법령정보센터 fallback로 우회(원문 아님) | 실 내부문서 URL 매핑 | ReportView.tsx:210-229 |
| Y9 | 입력 | 파일 첨부 OCR/추출 | `/api/extract` Python subprocess 의존, 미설치 시 fallback 없음 | 의존성 가이드 + 실패 시 텍스트 입력 유도 | server.ts:700-729 |

---

## ✅ 작동 확인 (보강 불필요)
텍스트 심의(`/api/review`)·파일 드래그/클립보드·결과 뷰 전환·수정문구 복사·탭 전환·헬스 표시·이력 조회/검색/채널·위험도 필터·CSV 다운로드·KPI(TPS/누적/위험비율)·위험분포·채널 파이차트·Batch 일괄심의·Audit Log 브라우저·Admin 모델라우팅·Secure Settings(load/apply/save/delete)·6인 보드·findings·근거검증 테이블·JSON 감사로그 토글.

---

## 🎯 권장 우선순위 (UI/UX 작업 순서)
1. **R1 검토 권한 프로필** — 제품 정체성(준법 SoD) + 사용자 지정 1순위. R1 해결 시 운영탭 노출도 역할별로 정리돼 IA 복잡도 동시 완화.
2. **R10 死컴포넌트 정리** — 채택할지/inline 유지할지 결정해야 이후 작업 혼선 방지(구조 기반).
3. **R2·R11·R12 대시보드 mock 제거** — "측정 미지원/더미"가 신뢰도 직접 훼손.
4. **R3 인증서 출력** — 준법 산출물 핵심, 비교적 독립적.
5. **R4~R8 Workflow/Knowledge** — 외부 연동(Notion/Jira/HITL)은 범위 크므로 별도 스코프.
6. **🟡 Y1~Y9** — 안내문구/경고 추가는 저비용 즉시 개선(Y2/Y4/Y5/Y6).

> 각 항목은 "UI는 이미 있음 → 뒤를 연결/구현"이 핵심. R1·R10은 **프론트 작업**으로 상당부분 가능(권한 게이트·컴포넌트 정리), R4~R8은 **백엔드 연동** 필요.

---

### 검증 수준
| 주장 | 수준 | 근거 |
|------|------|------|
| R1 역할 UI 분기 미구현 | [검증됨] | App.tsx role 체크 1곳(삭제)만 — grep |
| R4/R5 Notion/Jira 하드코딩 false | [검증됨] | server.ts:781-787 직독 |
| R6 HITL resume 엔드포인트 없음 | [검증됨] | server.ts:578 `resume_endpoint_available:false` |
| R10 3컴포넌트 import 안 됨 | [검증됨] | App.tsx import grep 0건 (현재 코드) |
| R2 avgDurationMs=0 | [검증됨] | server.ts:2663 하드코딩 |
| 🟡 항목 부분작동 | [검증됨] | 각 핸들러→API 추적 + server.ts 대조 |
| Python 의존(OCR 등) 실패 동작 | [추정] | 코드만 확인, 미설치 환경 실행 안 함 |
