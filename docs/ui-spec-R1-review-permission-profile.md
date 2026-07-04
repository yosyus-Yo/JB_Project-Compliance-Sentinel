# R1 — 검토 권한 프로필 (역할 기반 화면·권한) 구현 스펙

> **대상**: `compliance-sentinel/` React UI + `server.ts` · **상태**: 인벤토리 R1 (🔴 UI만/mock)
> **한 줄**: 역할(role)은 이미 있으나 **삭제 1건 외에는 어떤 화면·액션도 역할별로 다르지 않다.** 본 스펙은 "역할 프로필을 실제로 작동시키는" 최소 구현을 정의한다.
> **범위 주의**: 실 인증(SSO/비번/JWT 발급)은 **본 스펙 범위 밖**(별도 Y1). 현재의 역할 시뮬레이터(self-select) 위에 **화면 가드 + 서버 ACL**을 얹는 것이 목표.

---

## 1. 현황 (검증됨)
| 항목 | 현재 | 근거 |
|------|------|------|
| 역할 3종 | ADMIN(감사본부장) / COMPLIANCE_OFFICER(사내변호사) / CONTENT_MANAGER(마케팅팀) | App.tsx:841-843 |
| 역할 선택 | self-select 드롭다운 → `/api/auth/login` → 서버 인메모리 세션 | App.tsx:329-340, server.ts:2554 |
| 화면 분기 | **없음** — 세 역할 모두 동일 탭/버튼/패널 | App.tsx 전역 |
| 액션 게이트 | **삭제 1건만** ADMIN 체크 (프론트+서버) | App.tsx:383, server.ts:2594 |
| 탭 구성 | screen / dashboard / history / architecture + ops(admin·audit·knowledge·workflow·batch) | App.tsx:683-736 |

---

## 2. 역할 정의 (책임)
| 역할 | 누구 | 핵심 책임 |
|------|------|----------|
| **CONTENT_MANAGER** (마케팅팀) | 콘텐츠 작성자 | 심의 제출 + 본인 결과 열람 + 수정 후 재제출 |
| **COMPLIANCE_OFFICER** (사내변호사) | 준법 검토자 | 전체 심의 열람 + **최종 승인/반려 확정** + 지식/기준 관리 |
| **ADMIN** (감사본부장) | 감사 관리자 | 전부 + 감사기록 삭제·초기화 + 시스템 설정(키/모델) |

---

## 3. 권한 매트릭스 (구현 기준표)

### 3-1. 탭 노출 (visibility)
| 탭 | CONTENT_MGR | COMPLIANCE | ADMIN |
|----|:---:|:---:|:---:|
| screen(심의 요청) | ✅ | ✅ | ✅ |
| dashboard(분석) | ❌ | ✅ | ✅ |
| history(감사함) | 본인 것 | ✅ 전체 | ✅ 전체 |
| architecture | ✅ | ✅ | ✅ |
| **Admin**(키/모델/설정) | ❌ | ❌ | ✅ |
| Audit Log | ❌ | ✅ | ✅ |
| Knowledge | ❌ | ✅ | ✅ |
| Workflow | ❌ | ✅ | ✅ |
| Batch | ✅ | ✅ | ✅ |

### 3-2. 액션 권한 (gate)
| 액션 | CONTENT_MGR | COMPLIANCE | ADMIN | 현재 위치 |
|------|:---:|:---:|:---:|---|
| 심의 요청(/api/review) | ✅ | ✅ | ✅ | App.tsx:490 |
| **최종 승인/반려 확정** | ❌ | ✅ | ✅ | (신규 — 현재 액션 자체 없음, R9 재심의와 함께) |
| 감사기록 삭제(/api/history DELETE) | ❌ | ❌ | ✅ | App.tsx:383, server.ts:2594 (이미 ADMIN) |
| DB 초기화(reset) | ❌ | ❌ | ✅ | server.ts:205 |
| Secure Settings 저장/적용/삭제 | ❌ | ❌ | ✅ | server.ts:246/264/282 |
| 지식 ingest(apply=true) | ❌ | ✅ | ✅ | server.ts:319 |
| Workflow publish | ❌ | ✅ | ✅ | server.ts:748 |

---

## 4. 프론트 구현 명세 (App.tsx)

### 4-1. 권한 헬퍼 추가 (단일 출처)
```ts
// 역할 → 권한 판정 헬퍼 (예: src/permissions.ts 신규)
type Role = "ADMIN" | "COMPLIANCE_OFFICER" | "CONTENT_MANAGER";
const TAB_ROLES: Record<string, Role[]> = {
  dashboard:["ADMIN","COMPLIANCE_OFFICER"], admin:["ADMIN"],
  audit:["ADMIN","COMPLIANCE_OFFICER"], knowledge:["ADMIN","COMPLIANCE_OFFICER"],
  workflow:["ADMIN","COMPLIANCE_OFFICER"], // screen/history/architecture/batch = 전체
};
export const canSeeTab = (role: Role|undefined, tab: string) =>
  !TAB_ROLES[tab] || (role ? TAB_ROLES[tab].includes(role) : false);
export const canApprove = (r?:Role)=> r==="ADMIN"||r==="COMPLIANCE_OFFICER";
export const canDelete  = (r?:Role)=> r==="ADMIN";
export const canSettings= (r?:Role)=> r==="ADMIN";
```

### 4-2. 탭 nav 가드 (App.tsx:683-736)
- dashboard 버튼(697), ops 탭 배열(732-736 `[["admin",...],...]`) 렌더를 `canSeeTab(session?.role, id)`로 필터.
- 미인증(session=null) 시 ops 탭 전부 숨김 + "인증 후 이용" 안내.
- 현재 활성 탭이 권한 없는 탭이면 → `setActiveTab("screen")`로 강제 이동(역할 변경 시 stale 탭 방지).

### 4-3. 액션 게이트
- 기존 삭제 게이트(383)는 유지 + `canDelete()`로 치환.
- "승인/반려 확정" 버튼(신규, R9와 함께): `canApprove()` false면 버튼 미표시 또는 disabled+사유.
- Settings 저장/적용/삭제(OperationsPanel): `canSettings()` 게이트.

### 4-4. 역할 배지 (UX)
- 헤더에 현재 역할 칩 상시 표시(예: "사내변호사 · COMPLIANCE"). 권한 없는 기능은 **숨김 우선**, 단 "왜 안 보이는지" 중요한 경우(예: 승인 버튼)는 **disabled + 툴팁("준법 검토자만 확정 가능")**.

---

## 5. 백엔드 구현 명세 (server.ts) — defense-in-depth
> 프론트 숨김만으로는 불충분(누구나 role self-select). 서버 ACL이 실 방어선.

- **중앙 ACL 헬퍼**: `requireRole(session, ["ADMIN"])` 미들웨어/가드로 통일.
- 적용 엔드포인트:
  - `DELETE /api/history/:id`, reset → ADMIN (이미 부분 적용, 2594)
  - `/api/settings/save|apply`, `DELETE /api/settings` → ADMIN
  - `/api/ingest`(apply=true), `/api/workflow/*` publish → COMPLIANCE_OFFICER|ADMIN
  - (신규) 승인 확정 엔드포인트 → COMPLIANCE_OFFICER|ADMIN
- 위반 시 일관 `403 {status:'error', message, required_role}`.
- **세션 신뢰성(Y1 연계, 권장)**: 현재 인메모리 단일 변수 → 최소 쿠키 기반 세션으로. (실 SSO는 별도)

---

## 6. 수용 기준 (AC)
- [ ] CONTENT_MANAGER 로그인 시 Admin/Audit/Knowledge/Workflow/dashboard 탭 **안 보임**, screen/batch/architecture만 보임
- [ ] COMPLIANCE_OFFICER는 Admin 탭만 안 보임, 나머지 운영탭 보임
- [ ] ADMIN은 전체 보임
- [ ] 역할 변경 시 현재 탭이 권한 밖이면 screen으로 자동 이동
- [ ] 비-ADMIN이 삭제/설정 API 직접 호출(curl) 시 서버가 **403** (프론트 우회 방어)
- [ ] 승인/반려 확정은 COMPLIANCE/ADMIN만 (버튼+서버 양쪽)
- [ ] 각 역할 헤더에 역할 배지 표시

## 7. 범위 / 비범위
- **범위**: 역할별 탭 가드 + 액션 게이트(프론트) + 서버 ACL 확장 + 역할 배지.
- **비범위(별도)**: 실 인증(SSO/비번/JWT 발급), 커스텀 역할 생성, 세분화 권한 토글 UI, 본인-콘텐츠 소유권 필터링(history "본인 것"은 2단계).

## 8. 작업 분해 (제안)
1. `permissions.ts` 헬퍼 + 매트릭스(§3) — 프론트 단일 출처
2. 탭 nav 가드(§4-2) + 역할 변경 시 강제 이동
3. 액션 게이트(§4-3) + 역할 배지(§4-4)
4. server.ts 중앙 ACL 헬퍼 + 엔드포인트 적용(§5)
5. (연계) R9 승인/반려 확정 액션 신설 시 canApprove 게이트 동시 적용

---

### 검증 수준
| 주장 | 수준 | 근거 |
|------|------|------|
| 현재 역할=self-select 시뮬레이터, 삭제만 게이트 | [검증됨] | App.tsx:329/383, server.ts:2554/2594 |
| 탭 구성/위치 | [검증됨] | App.tsx:683-736 grep |
| 권한 매트릭스 | [추정] | 준법 SoD 일반 + 제품 맥락 기반 설계 — JB 내부규정 대조는 미수행, 운영팀 확정 필요 |
| 서버 ACL 미적용(삭제 외) | [검증됨] | 인벤토리 감사에서 다른 엔드포인트 role 체크 부재 확인 |
