/**
 * Presentation-layer types for the new (AI Studio) compliance UI design.
 *
 * Kept separate from `types.ts` (the real Python backend contract) to avoid a
 * name collision on `RiskLevel` — here it is an enum, in `types.ts` a string
 * union. The adapter (`adapter.ts`) maps `ComplianceReport` (types.ts) into the
 * `ProjectAuditListItem` shape the new design renders.
 */
import type { ComplianceReport } from './types.js';

export enum ComplianceStatus {
  PENDING = 'PENDING',
  PROCESSING = 'PROCESSING',
  COMPLETED = 'COMPLETED',
  REJECTED = 'REJECTED',
  APPROVED = 'APPROVED',
  AMENDED = 'AMENDED',
  NOT_APPLICABLE = 'NOT_APPLICABLE',
}

export enum RiskLevel {
  LOW = 'LOW',
  MEDIUM = 'MEDIUM',
  HIGH = 'HIGH',
  CRITICAL = 'CRITICAL',
}

export enum ChannelType {
  BANNER = 'BANNER',
  APP_PUSH = 'APP_PUSH',
  SNS = 'SNS',
  EMAIL = 'EMAIL',
  LANDING = 'LANDING',
}

export interface BoardReviewItem {
  id: string;
  name: string; // 소비자보호, 법률검토, 개인정보, 운영리스크, 실무적용, 반대의견
  status: 'REJECT' | 'AMEND' | 'PASS';
  comment: string;
}

export interface ScreeningStage {
  id: number; // 1 to 7
  title: string;
  subtitle: string;
  status: 'WAITING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'PARTIAL';
  details?: string;
  chips?: string[];
  boardItems?: BoardReviewItem[];
}

export interface ProjectAuditListItem {
  id: string;
  projectName: string;
  channel: ChannelType;
  inputContent: string;
  checkedContent?: string; // HTML with highlighted/masked areas
  riskLevel: RiskLevel;
  status: ComplianceStatus;
  userEmail: string;
  createdAt: string;
  stages: ScreeningStage[];
  detectedViolations: string[];
  findingsSum?: string;
  suggestedRewrite?: string; // 권고안(finding별 조치 사유) — revision_suggestions
  rewrittenAd?: string; // 실제 대체 광고문 — marketing_rewrite.rewritten (컴플라이언트 재작성본)
  fileName?: string;
  fileMimeType?: string;
  fileData?: string;
  /** Original backend report, attached by the adapter so operational tabs
   *  (Report/Workflow) can use the rich contract without a second fetch. */
  __report?: ComplianceReport;
}

export interface RealTimeMetrics {
  currentTps: number;
  totalAudited: number;
  criticalRatio: number;
  avgDurationMs: number;
  timelineGraph: { time: string; value: number }[];
  termFrequencies: { word: string; count: number }[];
}

export interface UserSession {
  userId: string;
  email: string;
  role: 'ADMIN' | 'COMPLIANCE_OFFICER' | 'CONTENT_MANAGER';
  name: string;
  token?: string;
}
