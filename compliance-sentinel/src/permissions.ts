// 역할 기반 권한 판정 — 단일 출처 (R1 검토 권한 프로필)
// 권한 매트릭스(TAB_ROLES + canX)는 준법 SoD(직무분리) 일반 기준 기반 [추정].
// JB 내부규정 대조는 미수행 — 운영팀 확정 시 본 파일의 TAB_ROLES/canX만 수정하면 전역 반영.
import type { UserSession } from "./ui-types.js";

export type Role = UserSession["role"];

// 탭 노출 매트릭스. 미등록 탭(screen/history/architecture)은 게스트 포함 전체 공개.
// 등록된 탭은 명시된 역할만 노출(게스트=role undefined는 항상 불가).
const TAB_ROLES: Record<string, Role[]> = {
  dashboard: ["ADMIN", "COMPLIANCE_OFFICER"],
  admin: ["ADMIN"],
  audit: ["ADMIN", "COMPLIANCE_OFFICER"],
  knowledge: ["ADMIN", "COMPLIANCE_OFFICER"],
  workflow: ["ADMIN", "COMPLIANCE_OFFICER"],
  batch: ["ADMIN", "COMPLIANCE_OFFICER", "CONTENT_MANAGER"], // 인증 필요(게스트 불가), 3역할 허용
  // screen / history / architecture = 공개(미등록 = 전체 허용)
};

// 데모/제출 UI에서 숨기는 탭. RBAC 로직(canSeeTab/canDelete)은 그대로 유지되므로
// "책임질 수 있는 AI"(RBAC/SoD) 근거는 코드로 남고, 시연 화면에서만 노출을 차단한다.
// 재노출하려면 이 집합에서 해당 탭을 제거하면 nav·접근가드·렌더가 한 번에 복원된다.
const HIDDEN_TABS = new Set<string>([]);

export const canSeeTab = (role: Role | undefined, tab: string): boolean =>
  HIDDEN_TABS.has(tab)
    ? false
    : !TAB_ROLES[tab] || (role ? TAB_ROLES[tab].includes(role) : false);

// 세부 액션 권한은 canDelete만 실제 사용(App.tsx 삭제 액션 게이트). 나머지 액션은
// canSeeTab 탭 게이트로 접근이 제어되므로 별도 per-action 헬퍼는 두지 않는다.
export const canDelete = (r?: Role): boolean => r === "ADMIN";

export interface RoleBadge {
  label: string;
  tone: "admin" | "compliance" | "content" | "guest";
}

export const roleBadge = (r?: Role): RoleBadge => {
  switch (r) {
    case "ADMIN":
      return { label: "감사본부장 · ADMIN", tone: "admin" };
    case "COMPLIANCE_OFFICER":
      return { label: "사내변호사 · COMPLIANCE", tone: "compliance" };
    case "CONTENT_MANAGER":
      return { label: "마케팅팀 · CONTENT", tone: "content" };
    default:
      return { label: "게스트 모드", tone: "guest" };
  }
};
