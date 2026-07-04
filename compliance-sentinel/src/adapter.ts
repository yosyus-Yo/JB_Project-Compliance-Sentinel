/**
 * Adapter: real backend contract (`ComplianceReport`, types.ts) ->
 * new design presentation shape (`ProjectAuditListItem`, ui-types.ts).
 *
 * The new AI Studio UI was built against a Gemini mock that returned a flat,
 * presentation-oriented object with a synthesised 7-stage pipeline. The real
 * Python/OpenAI backend returns the rich `ComplianceReport`. This module maps
 * one to the other so the new design renders genuine review results.
 *
 * No data is fabricated: every field is derived from the report. Where the
 * design wants a value the backend does not produce (e.g. per-stage status),
 * it is computed from real fields (findings, board diagnostics, verifier).
 */
import type {
  ComplianceReport,
  BoardDiagnostic,
  ComplianceFinding,
  CitationEvidence,
} from './types.js';
import {
  ComplianceStatus,
  RiskLevel,
  ChannelType,
  type ProjectAuditListItem,
  type ScreeningStage,
  type BoardReviewItem,
  type RealTimeMetrics,
} from './ui-types.js';

const DEFAULT_USER_EMAIL = 'compliance@jbfinancial.com';

// ---------------------------------------------------------------------------
// enum / string mappers
// ---------------------------------------------------------------------------

export function mapApprovalToStatus(approval?: string): ComplianceStatus {
  switch ((approval || '').toUpperCase()) {
    case 'APPROVED':
      return ComplianceStatus.APPROVED;
    case 'APPROVE_WITH_CHANGES':
      return ComplianceStatus.AMENDED;
    case 'REJECTED':
      return ComplianceStatus.REJECTED;
    case 'HUMAN_REVIEW_REQUIRED':
      return ComplianceStatus.PENDING;
    case 'NOT_APPLICABLE':
      return ComplianceStatus.NOT_APPLICABLE;
    default:
      return ComplianceStatus.PENDING;
  }
}

export function mapRisk(risk?: string): RiskLevel {
  switch ((risk || '').toUpperCase()) {
    case 'CRITICAL':
      return RiskLevel.CRITICAL;
    case 'HIGH':
      return RiskLevel.HIGH;
    case 'MEDIUM':
      return RiskLevel.MEDIUM;
    case 'LOW':
    case 'NONE':
    default:
      return RiskLevel.LOW;
  }
}

export function mapChannel(channel?: string): ChannelType {
  const c = (channel || '').toLowerCase().replace(/[\s_-]/g, '');
  switch (c) {
    case 'banner':
    case 'webbanner':
      return ChannelType.BANNER;
    case 'apppush':
    case 'push':
    case 'notice':
      return ChannelType.APP_PUSH;
    case 'sns':
      return ChannelType.SNS;
    case 'email':
    case 'mail':
      return ChannelType.EMAIL;
    case 'landingpage':
    case 'landing':
      return ChannelType.LANDING;
    default:
      // accept enum values that already match
      if (channel === ChannelType.BANNER) return ChannelType.BANNER;
      if (channel === ChannelType.APP_PUSH) return ChannelType.APP_PUSH;
      if (channel === ChannelType.SNS) return ChannelType.SNS;
      if (channel === ChannelType.EMAIL) return ChannelType.EMAIL;
      if (channel === ChannelType.LANDING) return ChannelType.LANDING;
      return ChannelType.BANNER;
  }
}

/** Reverse: presentation channel enum -> backend metadata channel string. */
export function channelToBackend(channel: ChannelType): string {
  switch (channel) {
    case ChannelType.BANNER:
      return 'Banner';
    case ChannelType.APP_PUSH:
      return 'AppPush';
    case ChannelType.SNS:
      return 'SNS';
    case ChannelType.EMAIL:
      return 'Email';
    case ChannelType.LANDING:
      return 'LandingPage';
    default:
      return 'AppPush';
  }
}

function mapOpinionToBoardStatus(opinion?: string): 'REJECT' | 'AMEND' | 'PASS' {
  switch ((opinion || '').toUpperCase()) {
    case 'REJECT':
      return 'REJECT';
    case 'APPROVE':
    case 'PASS':
      return 'PASS';
    case 'AMEND':
    case 'HUMAN':
    default:
      return 'AMEND';
  }
}

/** Map a board diagnostic persona/title to one of the 6 canonical board names
 *  the new design recognises (drives the emoji map). Falls back to the title. */
function mapPersonaName(diag: BoardDiagnostic): string {
  const key = `${diag.persona || ''} ${diag.title || ''}`.toLowerCase();
  if (/consumer|소비자/.test(key)) return '소비자보호';
  if (/legal|법(률|무)/.test(key)) return '법률검토';
  if (/privacy|개인정보|pii/.test(key)) return '개인정보';
  if (/aml|money|자금|운영|operation/.test(key)) return '운영리스크';
  if (/practic|실무|business/.test(key)) return '실무적용';
  if (/contrar|반대|devil|dissent/.test(key)) return '반대의견';
  return diag.title || diag.persona || '준법 검토';
}

// ---------------------------------------------------------------------------
// HTML highlight builder (for checkedContent)
// ---------------------------------------------------------------------------

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Build highlighted HTML from the original content, wrapping each detected
 * violation phrase in a <mark>. Prefers the redacted content (PII masked) as
 * the base when present so masking is visible. Output is consumed via
 * dangerouslySetInnerHTML; the trust boundary stays server-side per the
 * original contract — here we only escape + wrap known substrings.
 */
export function buildCheckedContent(
  base: string,
  violations: string[],
): string {
  let html = escapeHtml(base || '');
  const seen = new Set<string>();
  for (const raw of violations) {
    const phrase = (raw || '').trim();
    if (!phrase || phrase.length < 2 || seen.has(phrase)) continue;
    seen.add(phrase);
    const escaped = escapeHtml(phrase);
    const re = new RegExp(escapeRegExp(escaped), 'g');
    html = html.replace(
      re,
      `<mark class="bg-rose-100 text-rose-700 rounded px-0.5 font-semibold">$&</mark>`,
    );
  }
  return html.replace(/\n/g, '<br/>');
}

// ---------------------------------------------------------------------------
// 7-stage synthesis from the real report
// ---------------------------------------------------------------------------

function stageStatusFromBoard(
  board: BoardReviewItem[],
): ScreeningStage['status'] {
  if (board.some((b) => b.status === 'REJECT')) return 'FAILED';
  if (board.some((b) => b.status === 'AMEND')) return 'PARTIAL';
  return board.length ? 'SUCCESS' : 'WAITING';
}

export function buildStages(
  report: ComplianceReport,
  board: BoardReviewItem[],
): ScreeningStage[] {
  const findings = report.findings || [];
  const evidence = report.evidence || [];
  const hasCritical = findings.some(
    (f) => (f.severity || '').toUpperCase() === 'CRITICAL',
  );
  const meta = report.input_completeness || ({} as Record<string, unknown>);
  const verifier = report.verifier_result || { status: 'PARTIAL' as const };

  const verifierStatus: ScreeningStage['status'] =
    verifier.status === 'FAIL'
      ? 'FAILED'
      : verifier.status === 'PARTIAL'
        ? 'PARTIAL'
        : 'SUCCESS';

  const approval = (report.approval_status || '').toUpperCase();
  const finalStatus: ScreeningStage['status'] =
    approval === 'REJECTED'
      ? 'FAILED'
      : approval === 'APPROVED'
        ? 'SUCCESS'
        : 'PARTIAL';

  const lawNames = Array.from(
    new Set(
      findings
        .map((f) => f.law_name)
        .filter((x): x is string => Boolean(x)),
    ),
  );
  const findingCategories = Array.from(
    new Set(findings.map((f) => f.category).filter(Boolean)),
  );

  return [
    {
      id: 1,
      title: '입력 접수 · Runtime Guard',
      subtitle: '콘텐츠 수신 및 런타임 가드',
      status: 'SUCCESS',
      details: report.guard_flags?.pii_detected
        ? `개인정보 ${report.guard_flags.pii_redacted_count}건 자동 마스킹`
        : '개인정보/인젝션 위험 미탐지',
      chips: [report.channel || '', report.language || ''].filter(Boolean),
    },
    {
      id: 2,
      title: '콘텐츠 분류',
      subtitle: '상품/채널/대상 분류',
      status: 'SUCCESS',
      chips: [report.product_type || '', report.target_audience || ''].filter(
        Boolean,
      ),
      details:
        typeof (meta as { mode?: string }).mode === 'string'
          ? `분류 모드: ${(meta as { mode?: string }).mode}`
          : undefined,
    },
    {
      id: 3,
      title: '규정 근거 검색',
      subtitle: '법령/약관 근거 매칭',
      status: evidence.length ? 'SUCCESS' : 'PARTIAL',
      chips: lawNames.slice(0, 4),
      details: `근거 ${evidence.length}건 매칭`,
    },
    {
      id: 4,
      title: '표현 규칙 검사',
      subtitle: '오인·과장·필수고지 위반 검사',
      status: hasCritical ? 'FAILED' : findings.length ? 'PARTIAL' : 'SUCCESS',
      chips: findingCategories.slice(0, 5),
      details: `위반/지적 ${findings.length}건${hasCritical ? ' (치명적 포함)' : ''}`,
    },
    {
      id: 5,
      title: '6인 준법 보드',
      subtitle: '다관점 준법 보드 심의',
      status: stageStatusFromBoard(board),
      boardItems: board,
      details: `${board.length}인 보드 평결 완료`,
    },
    {
      id: 6,
      title: '교차 검증 (Verifier)',
      subtitle: '인용·근거 교차 검증',
      status: verifierStatus,
      details:
        verifier.details ||
        `검증 ${verifier.checked_claims ?? 0}건 중 ${verifier.failed_claims ?? 0}건 실패`,
    },
    {
      id: 7,
      title: '최종 준법 판정',
      subtitle: '종합 판정 및 감사 기록',
      status: finalStatus,
      chips: [report.approval_status || '', report.risk_level || ''].filter(
        Boolean,
      ),
      details: report.summary,
    },
  ];
}

export function buildBoardItems(report: ComplianceReport): BoardReviewItem[] {
  // raw final_report는 board_diagnostics를 빈 객체 {}로 줄 수 있다(빈 객체는 truthy라
  // `|| []` 폴백을 통과해 .map에서 TypeError). 배열일 때만 사용하고 아니면 빈 배열로 방어.
  const diags: BoardDiagnostic[] = Array.isArray(report.board_diagnostics)
    ? report.board_diagnostics
    : [];
  return diags.map((d, i) => ({
    id: `${report.review_request_id || 'RR'}-board-${i}`,
    name: mapPersonaName(d),
    status: mapOpinionToBoardStatus(d.opinion),
    comment: d.comment || '',
  }));
}

// 하이라이트/칩에 쓸 위반 표현 추출.
// 개별 위험 표현(finding_text)을 우선 — LLM이 source_text를 종종 "문서 앞부분 전체"
// 같은 동일 덩어리로 채워, source_text만 쓰면 앞부분만 통째로 하이라이트되고 개별
// 위험어("원금 보장"·"누구나 부자" 등)는 칠해지지 않는 버그가 있었다. (RR-db528fabf307 진단)
// 너무 긴(>60자) 구절은 원문 전체 덩어리일 확률이 높아 하이라이트 정밀도를 떨어뜨리므로 제외.
function collectViolations(findings: ComplianceFinding[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const MAX_PHRASE_LEN = 60;
  for (const f of findings) {
    // finding_text(개별 표현)를 우선, source_text는 보조 — 둘 다 길이 cap 적용
    const candidates = [
      (f.finding_text || '').trim(),
      (f.source_text || '').trim(),
    ];
    for (const phrase of candidates) {
      if (
        phrase &&
        phrase.length >= 2 &&
        phrase.length <= MAX_PHRASE_LEN &&
        !seen.has(phrase)
      ) {
        seen.add(phrase);
        out.push(phrase);
      }
    }
  }
  return out;
}

/**
 * Mask PII before showing a violation phrase as a chip. The finding source text
 * can contain the offending PII itself (e.g. a resident-registration-number
 * misuse finding); rendering it verbatim would re-expose PII in a
 * privacy-sensitive product. Mirrors the backend redaction patterns.
 * Note: highlighting (buildCheckedContent) uses the un-masked phrase, but the
 * base it highlights against is already the redacted content, so masked PII is
 * simply not matched — no re-exposure there either.
 */
function redactPII(text: string): string {
  return (text || '')
    .replace(/\d{6}-[1-4]\d{6}/g, '[주민등록번호 마스킹]')
    .replace(/01[016789][-.]?\d{3,4}[-.]?\d{4}/g, '[전화번호 마스킹]')
    .replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, '[이메일 마스킹]')
    .replace(/\d{3,6}-\d{2,6}-\d{3,6}/g, '[계좌번호 마스킹]');
}

// ---------------------------------------------------------------------------
// top-level: ComplianceReport -> ProjectAuditListItem
// ---------------------------------------------------------------------------

export interface AdaptOptions {
  projectName?: string;
  userEmail?: string;
  channel?: ChannelType;
  fileName?: string;
  fileMimeType?: string;
  fileData?: string;
}

export function reportToAuditItem(
  report: ComplianceReport,
  opts: AdaptOptions = {},
): ProjectAuditListItem {
  const findings = report.findings || [];
  const violations = collectViolations(findings);
  const board = buildBoardItems(report);
  const base = report.redacted_content || report.raw_content || '';
  const suggested =
    report.revision_suggestions ||
    (report.revision_items && report.revision_items[0]?.revised) ||
    '';
  // 실제 대체 광고문(컴플라이언트 재작성본) — 권고안(suggested)과 분리.
  // deterministic_fallback이거나 비어있으면 권고안으로 폴백.
  const rewrittenAd = (report.marketing_rewrite?.rewritten || '').trim();
  const id =
    report.review_request_id || report.audit_log_id || `RR-${Date.now()}`;

  const projectName =
    opts.projectName ||
    (report.summary ? report.summary.slice(0, 48) : '') ||
    `심의 ${id}`;

  return {
    id,
    projectName,
    channel: opts.channel || mapChannel(report.channel),
    inputContent: base,
    checkedContent: buildCheckedContent(base, violations),
    riskLevel: mapRisk(report.risk_level),
    status: mapApprovalToStatus(report.approval_status),
    userEmail: opts.userEmail || DEFAULT_USER_EMAIL,
    createdAt: report.timestamp || new Date().toISOString(),
    stages: buildStages(report, board),
    detectedViolations: violations.map(redactPII),
    findingsSum: report.summary || '',
    suggestedRewrite: suggested,
    rewrittenAd: rewrittenAd || undefined,
    fileName: opts.fileName,
    fileMimeType: opts.fileMimeType,
    fileData: opts.fileData,
    __report: report,
  };
}

export function reportsToAuditItems(
  reports: ComplianceReport[],
): ProjectAuditListItem[] {
  return (reports || []).map((r) => reportToAuditItem(r));
}

// ---------------------------------------------------------------------------
// client-side metrics fallback (server endpoint is primary; see server.ts)
// ---------------------------------------------------------------------------

export function metricsFromItems(items: ProjectAuditListItem[]): RealTimeMetrics {
  const total = items.length;
  const critical = items.filter(
    (i) => i.riskLevel === RiskLevel.CRITICAL || i.riskLevel === RiskLevel.HIGH,
  ).length;
  const termMap = new Map<string, number>();
  for (const i of items) {
    for (const v of i.detectedViolations) {
      const key = v.slice(0, 18);
      termMap.set(key, (termMap.get(key) || 0) + 1);
    }
  }
  const termFrequencies = Array.from(termMap.entries())
    .map(([word, count]) => ({ word, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 7);

  return {
    currentTps: 0,
    totalAudited: total,
    criticalRatio: total ? Math.round((critical / total) * 100) : 0,
    avgDurationMs: 0,
    timelineGraph: [],
    termFrequencies,
  };
}
