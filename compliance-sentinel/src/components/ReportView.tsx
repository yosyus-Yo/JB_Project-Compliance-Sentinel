import { useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Copy,
  Database,
  FileCheck2,
  FileText,
  Lock,
  Scale,
  ShieldCheck,
  Terminal,
  XCircle,
} from 'lucide-react';
import type { BoardDiagnostic, ComplianceFinding, ComplianceReport } from '../types.js';
import WorkflowSteps from './WorkflowSteps.js';

// 다국어 깃발 매핑 (P1-5 from UI개선요청서)
const LANGUAGE_FLAGS: Record<string, { flag: string; name: string }> = {
  ko: { flag: '🇰🇷', name: '한국어' },
  en: { flag: '🇺🇸', name: '영어' },
  zh: { flag: '🇨🇳', name: '중국어' },
  'zh-cn': { flag: '🇨🇳', name: '중국어(간체)' },
  'zh-tw': { flag: '🇹🇼', name: '중국어(번체)' },
  vi: { flag: '🇻🇳', name: '베트남어' },
  ja: { flag: '🇯🇵', name: '일본어' },
  th: { flag: '🇹🇭', name: '태국어' },
  id: { flag: '🇮🇩', name: '인도네시아어' },
  ar: { flag: '🇸🇦', name: '아랍어' },
};

function detectLanguage(text: string): string {
  if (!text) return 'unknown';
  // 본문 첫 200자 표본
  const sample = text.slice(0, 200);
  if (/[぀-ゟ゠-ヿ]/.test(sample)) return 'ja';
  if (/[一-鿿]/.test(sample)) return 'zh';
  if (/[가-힯]/.test(sample)) return 'ko';
  if (/[฀-๿]/.test(sample)) return 'th';
  if (/[؀-ۿ]/.test(sample)) return 'ar';
  // 베트남어: 라틴 + 성조 부호
  if (/[ăâđêôơưĂÂĐÊÔƠƯạảấầẩẫậắằẳẵặẹẻẽếềểễệỉĩịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]/i.test(sample))
    return 'vi';
  if (/[a-zA-Z]/.test(sample)) return 'en';
  return 'unknown';
}

function groupFindingsByLanguage(
  findings: ComplianceFinding[],
): Array<{ lang: string; flag: string; name: string; items: ComplianceFinding[] }> {
  const groups: Record<string, ComplianceFinding[]> = {};
  for (const f of findings) {
    const lang = (
      (f as { language?: string }).language ||
      detectLanguage(f.source_text || f.finding_text || '')
    ).toLowerCase();
    const key = LANGUAGE_FLAGS[lang] ? lang : lang.split('-')[0];
    const finalKey = LANGUAGE_FLAGS[key] ? key : 'unknown';
    if (!groups[finalKey]) groups[finalKey] = [];
    groups[finalKey].push(f);
  }
  return Object.entries(groups).map(([lang, items]) => {
    const meta = LANGUAGE_FLAGS[lang] || { flag: '🌐', name: '미분류' };
    return { lang, flag: meta.flag, name: meta.name, items };
  });
}

interface ReportViewProps {
  report: ComplianceReport;
  onApplyRevision: (revisedText: string) => void;
}

export default function ReportView({ report, onApplyRevision }: ReportViewProps) {
  const [copiedText, setCopiedText] = useState<string | null>(null);
  const [showRawLog, setShowRawLog] = useState(false);
  const [showFindingGuidance, setShowFindingGuidance] = useState(false);
  const status = statusConfig(report);
  const runtime = runtimeEvidence(report);
  const hasRewrite = Boolean(report.marketing_rewrite?.rewritten);

  const copyToClipboard = async (text: string, label: string) => {
    await navigator.clipboard?.writeText(text);
    setCopiedText(label);
    window.setTimeout(() => setCopiedText(null), 1800);
  };

  return (
    <div className="space-y-5" id="compliance-report-display">
      <section className={`report-hero ${status.className}`}>
        <div className="min-w-0">
          <p className="eyebrow">Decision</p>
          <div className="flex flex-wrap items-center gap-2">
            {status.icon}
            <h2>{status.title}</h2>
          </div>
          <p>{report.summary || status.description}</p>
        </div>
        <div className="report-hero-side">
          <span className="mini-chip strong">{backendLabel(report)}</span>
          <span className={`status-pill ${riskTone(report.risk_level)}`}>{report.risk_level}</span>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <MetricBlock label="Review ID" value={report.review_request_id} copy={() => copyToClipboard(report.review_request_id, 'review-id')} copied={copiedText === 'review-id'} />
        <MetricBlock label="Audit ID" value={report.audit_log_id} copy={() => copyToClipboard(report.audit_log_id, 'audit-id')} copied={copiedText === 'audit-id'} />
        <MetricBlock label="Confidence" value={`${Math.round(report.confidence_score * 100)}%`} sub={report.confidence} />
        <MetricBlock label="Route" value={report.human_review_needed ? 'HITL' : 'Auto'} sub={report.channel || 'unknown'} />
      </section>

      <section className="panel" id="llm-runtime-evidence">
        <div className="section-title">
          <div>
            <p className="eyebrow">Runtime Evidence</p>
            <h2>LLM 검증 라우팅</h2>
          </div>
          <span className={`status-pill ${runtime.liveCalls > 0 ? 'tone-green' : 'tone-amber'}`}>
            {runtime.liveCalls > 0 ? 'Live LLM' : 'Fallback only'}
          </span>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <MetricBlock label="LLM calls" value={`${runtime.liveCalls}/${runtime.totalCalls}`} sub={runtime.fallbackCalls ? `${runtime.fallbackCalls} fallback` : 'called'} />
          <MetricBlock label="Verifier model" value={runtime.verifierModel} sub={runtime.verifierStatus} />
          <MetricBlock label="Cross-model" value={runtime.crossStatus} sub={runtime.crossModel} />
          <MetricBlock label="Bridge policy" value={runtime.bridgePolicy} sub={runtime.bridgeReason} />
        </div>
        {runtime.roleModels.length > 0 && (
          <div className="runtime-call-list">
            {runtime.roleModels.map((item) => (
              <span key={`${item.role}-${item.model}`} className="mini-chip">{item.role}: {item.model}</span>
            ))}
          </div>
        )}
        {runtime.errors.length > 0 && (
          <div className="runtime-errors">
            {runtime.errors.map((item) => (
              <span key={`${item.role}-${item.error}`}>{item.role}: {item.error}</span>
            ))}
          </div>
        )}
      </section>

      <section className="panel" id="pii-scrubber-comparison">
        <div className="section-title">
          <div>
            <p className="eyebrow">Runtime Guard</p>
            <h2>원문 및 마스킹 결과</h2>
          </div>
          <span className={`status-pill ${report.guard_flags?.pii_detected ? 'tone-amber' : 'tone-green'}`}>
            {report.guard_flags?.pii_detected ? `${report.guard_flags.pii_redacted_count}건 마스킹` : 'PII clear'}
          </span>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <TextPane icon={FileText} title="사용자 입력" text={report.raw_content} />
          <TextPane icon={Lock} title="보호 처리된 입력" text={report.redacted_content || redactSensitive(report.raw_content)} />
        </div>
      </section>

      <WorkflowSteps report={report} />

      {report.rag_metadata && (() => {
        const meta = report.rag_metadata;
        const provenance = meta.retrieved_law_provenance ?? [];
        const backend = meta.law_backend ?? 'unknown';
        const isHybrid = backend.includes('qdrant') || backend.includes('hybrid');
        const backendLabel = isHybrid
          ? 'Qdrant + Keyword (Hybrid RRF)'
          : backend === 'keyword_fallback'
            ? 'Keyword Only (Fallback)'
            : backend;
        const lawCount = typeof meta.law_count === 'number' ? meta.law_count : provenance.length;
        const cacheBadge = meta.rag_cache_hit ? '캐시 히트' : '실시간 검색';
        return (
          <section className="panel rag-results-panel" id="rag-retrieved-laws">
            <div className="section-title">
              <div>
                <p className="eyebrow">RAG Retrieval</p>
                <h2>법령 RAG 검색 결과</h2>
              </div>
              <Database className="h-5 w-5 text-forest-700" />
            </div>
            <div className="rag-results-meta">
              <span className={`status-pill ${isHybrid ? 'tone-green' : 'tone-amber'}`}>
                {backendLabel}
              </span>
              <span className="mini-chip">매칭 {lawCount}건</span>
              <span className="mini-chip">{cacheBadge}</span>
              {typeof meta.memory_hit_count === 'number' && meta.memory_hit_count > 0 && (
                <span className="mini-chip">Brain 메모리 {meta.memory_hit_count}건</span>
              )}
              {typeof meta.document_rag_count === 'number' && meta.document_rag_count > 0 && (
                <span className="mini-chip">문서 RAG {meta.document_rag_count}건</span>
              )}
            </div>
            {provenance.length === 0 ? (
              <div className="empty-state compact">검색된 법령이 없습니다 (deterministic rule만 적용).</div>
            ) : (
              <ul className="rag-results-list">
                {provenance.map((law, index) => (
                  <li className="rag-result-item" key={`${law.law_name ?? 'law'}-${law.article_no ?? index}`}>
                    <div className="rag-result-main">
                      <strong>{law.law_name ?? '미상 법령'}</strong>
                      {law.article_no && <span className="rag-result-article">제{law.article_no}조</span>}
                    </div>
                    <div className="rag-result-meta">
                      {law.effective_date && (
                        <span className="rag-result-date">시행일 {law.effective_date}</span>
                      )}
                      {law.source_url && (law.source_url.startsWith('http://') || law.source_url.startsWith('https://')) ? (
                        <a
                          href={law.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="rag-result-link"
                        >
                          원문 ↗
                        </a>
                      ) : law.source_url && law.law_name ? (
                        <a
                          href={`https://www.law.go.kr/lsSc.do?menuId=1&query=${encodeURIComponent(law.law_name)}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="rag-result-link"
                          title="법령정보센터에서 검색"
                        >
                          {law.source_url.startsWith('local://jb-internal/') || law.source_url.includes('JB-') ? '내부 기준 (검색) ↗' : '원문 검색 ↗'}
                        </a>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })()}

      <section className="panel" id="six-personas-board-opinions">
        <div className="section-title">
          <div>
            <p className="eyebrow">Board</p>
            <h2>6인 준법 보드 의견</h2>
          </div>
          <Scale className="h-5 w-5 text-forest-700" />
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {report.board_diagnostics.map((diagnostic, index) => (
            <BoardCard key={`${diagnostic.persona}-${index}`} diagnostic={diagnostic} />
          ))}
        </div>
      </section>

      <section className="panel" id="findings-scrubber-comparison">
        <div className="section-title">
          <div>
            <p className="eyebrow">Findings</p>
            <h2>표현 리스크 및 수정 근거</h2>
          </div>
          <span className="mini-chip">{report.findings.length} findings</span>
        </div>

        {report.findings.length === 0 ? (
          <div className="empty-state">
            <CheckCircle2 className="h-9 w-9 text-forest-700" />
            <strong>자동 검토 기준에서 주요 위반 사항이 발견되지 않았습니다.</strong>
          </div>
        ) : (
          (() => {
            const groups = groupFindingsByLanguage(report.findings);
            // 단일 언어만이면 grouping 헤더 생략 (UX noise 회피)
            if (groups.length <= 1) {
              return (
                <div className="space-y-3">
                  {report.findings.map((finding) => (
                    <FindingCard key={finding.id} finding={finding} />
                  ))}
                </div>
              );
            }
            return (
              <div className="space-y-5">
                {groups.map((g) => (
                  <div key={g.lang} className="finding-language-group">
                    <div className="finding-language-header">
                      <span className="finding-language-flag" aria-hidden="true">{g.flag}</span>
                      <span className="finding-language-name">{g.name}</span>
                      <span className="mini-chip">{g.items.length}건</span>
                    </div>
                    <div className="space-y-3">
                      {g.items.map((finding) => (
                        <FindingCard key={finding.id} finding={finding} />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            );
          })()
        )}
      </section>

      <section className="panel" id="atomic-citation-checker-laws">
        <div className="section-title">
          <div>
            <p className="eyebrow">Evidence</p>
            <h2>근거 검증</h2>
          </div>
          <span className={`status-pill ${verifierTone(report.verifier_result.status)}`}>
            Verifier {report.verifier_result.status}
          </span>
        </div>
        {report.verifier_result.details && (
          <p className="mb-3 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-sm text-muted">
            {report.verifier_result.details}
          </p>
        )}
        {report.evidence.length === 0 ? (
          <div className="empty-state compact">연결된 근거 조항이 없습니다.</div>
        ) : (
          <div className="evidence-table">
            {report.evidence.map((evidence, index) => (
              <div className="evidence-row" key={`${evidence.clause}-${index}`}>
                <div className="min-w-0">
                  <strong>{evidence.clause}</strong>
                  <p>{evidence.verbatim}</p>
                </div>
                <div className="evidence-flags">
                  <span className={`status-pill ${evidence.exists ? 'tone-green' : 'tone-red'}`}>exists</span>
                  <span className={`status-pill ${evidence.match ? 'tone-green' : 'tone-red'}`}>match</span>
                  <span className={`status-pill ${evidence.applicable ? 'tone-green' : 'tone-amber'}`}>applicable</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {report.marketing_rewrite?.rewritten && (
        <section className="revision-panel rewrite-panel" id="marketing-rewrite-box">
          <div className="section-title">
            <div>
              <p className="eyebrow">LLM Rewrite</p>
              <h2>✨ 마케팅 카피 수정안</h2>
            </div>
            <button
              type="button"
              onClick={() => copyToClipboard(report.marketing_rewrite!.rewritten!, 'rewrite')}
              className="secondary-button"
            >
              <Copy className="h-4 w-4" />
              {copiedText === 'rewrite' ? '복사됨' : '복사'}
            </button>
          </div>
          <pre className="revision-text rewrite-text">{report.marketing_rewrite.rewritten}</pre>
          {(report.marketing_rewrite.removed_terms?.length || report.marketing_rewrite.added_notices?.length) ? (
            <div className="rewrite-meta">
              {report.marketing_rewrite.removed_terms?.length ? (
                <div className="rewrite-meta-block">
                  <strong>삭제된 표현 ({report.marketing_rewrite.removed_terms.length})</strong>
                  <ul>
                    {report.marketing_rewrite.removed_terms.map((t, i) => (
                      <li key={`rm-${i}`}>{t}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {report.marketing_rewrite.added_notices?.length ? (
                <div className="rewrite-meta-block">
                  <strong>추가된 필수 고지 ({report.marketing_rewrite.added_notices.length})</strong>
                  <ul>
                    {report.marketing_rewrite.added_notices.map((t, i) => (
                      <li key={`ad-${i}`}>{t}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
          <div className="rewrite-footer">
            <span className="mini-chip">{report.marketing_rewrite.model ?? 'LLM'}</span>
            <span className="rewrite-footer-note">아래는 finding별 일반 권고문 (compliance guidance).</span>
          </div>
        </section>
      )}

      <section className="revision-panel" id="copyable-revision-box">
        {hasRewrite ? (
          <button
            type="button"
            onClick={() => setShowFindingGuidance((v) => !v)}
            className="raw-toggle"
            aria-expanded={showFindingGuidance}
          >
            <span className="flex items-center gap-2">
              <FileText className="h-4 w-4" />
              <span>📋 위반별 컴플라이언스 권고 (audit 용도, finding별 일반 안내)</span>
            </span>
            <span>{showFindingGuidance ? '접기' : '펼치기'}</span>
          </button>
        ) : (
          <div className="section-title">
            <div>
              <p className="eyebrow">Approved Draft</p>
              <h2>수정 권고 문구</h2>
            </div>
            <button
              id="btn-copy-suggestions"
              type="button"
              onClick={() => copyToClipboard(report.revision_suggestions, 'revision')}
              className="secondary-button"
            >
              <Copy className="h-4 w-4" />
              {copiedText === 'revision' ? '복사됨' : '복사'}
            </button>
          </div>
        )}
        {(!hasRewrite || showFindingGuidance) && (
          <>
            {hasRewrite && (
              <div className="finding-guidance-intro">
                <p className="finding-guidance-help">
                  위쪽 <strong>위반 표현 (Findings)</strong> 패널의 각 항목 (MF-001 등)이 받은 일반 컴플라이언스 안내입니다.
                  마케터는 <strong>✨ 마케팅 카피 수정안</strong>을 그대로 사용하세요. 본 권고는 감사·audit log 용도입니다.
                </p>
                <button
                  type="button"
                  onClick={() => copyToClipboard(report.revision_suggestions, 'revision')}
                  className="secondary-button"
                >
                  <Copy className="h-4 w-4" />
                  {copiedText === 'revision' ? '복사됨' : '복사'}
                </button>
              </div>
            )}
            <pre className="revision-text">{report.revision_suggestions}</pre>
            <div className="flex justify-end">
              <button
                id="btn-apply-original-input"
                type="button"
                onClick={() => onApplyRevision(report.revision_suggestions)}
                className="text-button"
              >
                <ClipboardCheck className="h-4 w-4" />
                편집기에 적용
              </button>
            </div>
          </>
        )}
      </section>

      <section className="panel">
        <button
          id="toggle-raw-log"
          type="button"
          onClick={() => setShowRawLog((value) => !value)}
          className="raw-toggle"
        >
          <span className="flex items-center gap-2">
            <Terminal className="h-4 w-4" />
            JSON 감사 로그
          </span>
          <span>{showRawLog ? '접기' : '열기'}</span>
        </button>
        {showRawLog && (
          <pre className="raw-log">
            {JSON.stringify(
              {
                review_request_id: report.review_request_id,
                audit_log_id: report.audit_log_id,
                approval_status: report.approval_status,
                risk_level: report.risk_level,
                confidence: report.confidence,
                integration: report.integration,
                schema_validation: report.schema_validation,
                guard_flags: report.guard_flags,
                llm_calls: runtime.rawCalls,
                model_plan: report.raw_report?.model_plan,
                cross_model_result: report.raw_report?.cross_model_result,
                board_member_opinions: report.raw_report?.board_member_opinions,
              },
              null,
              2,
            )}
          </pre>
        )}
      </section>
    </div>
  );
}

interface RuntimeCallView {
  role: string;
  model: string;
  called: boolean;
  deterministic_fallback: boolean;
  error?: string;
}

function runtimeEvidence(report: ComplianceReport) {
  const raw = asRecord(report.raw_report);
  const calls: RuntimeCallView[] = asArray(raw.llm_calls).map((item) => {
    const call = asRecord(item);
    return {
      role: asString(call.role, 'unknown'),
      model: asString(call.model, 'n/a'),
      called: call.called === true,
      deterministic_fallback: call.deterministic_fallback === true,
      error: asOptionalString(call.error),
    };
  });
  const modelPlan = asRecord(raw.model_plan);
  const assignments = asRecord(modelPlan.role_assignments);
  const verifierAssignment = asRecord(assignments.verifier);
  const crossPlan = asRecord(modelPlan.cross_model);
  const crossResult = asRecord(raw.cross_model_result);
  const verifierCall = calls.find((call) => call.role === 'verifier');
  const liveCalls = calls.filter((call) => call.called).length;
  const fallbackCalls = calls.filter((call) => call.deterministic_fallback).length;
  const roleModels = calls
    .filter((call) => call.called)
    .map((call) => ({ role: call.role, model: call.model }));
  const errors = calls
    .filter((call) => call.error)
    .map((call) => ({ role: call.role, error: call.error || '' }));
  const crossEnabled = crossResult.enabled === true;
  const crossStatus = crossEnabled
    ? asString(crossResult.cross_model_confidence, 'ENABLED')
    : asString(crossResult.cross_model_confidence || crossResult.reason || crossPlan.level, 'SKIPPED');

  return {
    rawCalls: calls,
    totalCalls: calls.length,
    liveCalls,
    fallbackCalls,
    verifierModel: asString(verifierCall?.model || verifierAssignment.model, 'not routed'),
    verifierStatus: verifierCall ? (verifierCall.called ? 'called' : 'fallback') : 'planned',
    crossStatus,
    crossModel: asString(crossResult.model || crossPlan.model, 'not attached'),
    bridgePolicy: report.integration?.cache_hit ? 'Cache hit' : report.integration?.backend === 'local-rule-engine' ? 'Fail closed' : 'Normal',
    bridgeReason: report.integration?.fallback_reason || report.integration?.cache_expires_at || asString(crossResult.level || crossPlan.level, 'ready'),
    roleModels,
    errors,
  };
}

function MetricBlock({ label, value, sub, copy, copied }: { label: string; value: string; sub?: string; copy?: () => void; copied?: boolean }) {
  return (
    <div className="report-metric">
      <span>{label}</span>
      <div className="flex min-w-0 items-center justify-between gap-2">
        <strong title={value}>{value}</strong>
        {copy && (
          <button type="button" className="icon-button small" onClick={copy} title="복사">
            <Copy className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <em>{copied ? 'copied' : sub || ' '}</em>
    </div>
  );
}

function TextPane({ icon: Icon, title, text }: { icon: typeof FileText; title: string; text: string }) {
  return (
    <div className="text-pane">
      <h3>
        <Icon className="h-4 w-4" />
        {title}
      </h3>
      <p>{text}</p>
    </div>
  );
}

function BoardCard({ diagnostic }: { diagnostic: BoardDiagnostic; key?: string }) {
  return (
    <article className="board-card">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="avatar-badge">{diagnostic.avatar}</span>
          <span className="min-w-0">
            <strong>{diagnostic.title}</strong>
            <em>{diagnostic.persona}</em>
          </span>
        </div>
        <span className={`status-pill ${opinionTone(diagnostic.opinion)}`}>{diagnostic.opinion}</span>
      </div>
      <p>{diagnostic.comment}</p>
    </article>
  );
}

function FindingCard({ finding }: { finding: ComplianceFinding; key?: string }) {
  return (
    <article className="finding-card">
      <div className="finding-header">
        <span className={`status-pill ${severityTone(finding.severity)}`}>{finding.severity || finding.category}</span>
        <span className="font-mono text-xs text-muted">{finding.id}</span>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <h3>탐지 표현</h3>
          <p className="finding-problem">{finding.finding_text}</p>
          <p className="finding-reason">{finding.reason}</p>
        </div>
        <div>
          <h3>권고 수정</h3>
          <p className="finding-fix">{finding.suggested_revision}</p>
          {(finding.law_name || finding.article_no) && (
            <p className="finding-law">
              {finding.law_name} {finding.article_no ? `/ ${finding.article_no}` : ''}
            </p>
          )}
        </div>
      </div>
    </article>
  );
}

function statusConfig(report: ComplianceReport) {
  switch (report.approval_status) {
    case 'APPROVED':
      return {
        title: '승인 가능',
        description: '자동 심의 기준에서 주요 배포 차단 사유가 없습니다.',
        className: 'report-approved',
        icon: <CheckCircle2 className="h-6 w-6" />,
      };
    case 'APPROVE_WITH_CHANGES':
      return {
        title: '수정 후 승인',
        description: '권고 문구를 반영하면 실무 배포 검토가 가능합니다.',
        className: 'report-amend',
        icon: <AlertTriangle className="h-6 w-6" />,
      };
    case 'REJECTED':
      return {
        title: '반려',
        description: '고위험 표현이 포함되어 재작성과 담당자 확인이 필요합니다.',
        className: 'report-rejected',
        icon: <XCircle className="h-6 w-6" />,
      };
    case 'HUMAN_REVIEW_REQUIRED':
      return {
        title: '담당자 검토 필요',
        description: '자동 판단만으로 확정하기 어려운 케이스입니다.',
        className: 'report-human',
        icon: <ShieldCheck className="h-6 w-6" />,
      };
    default:
      return {
        title: '검토 완료',
        description: '심의 결과가 생성되었습니다.',
        className: 'report-human',
        icon: <FileCheck2 className="h-6 w-6" />,
      };
  }
}

function backendLabel(report: ComplianceReport) {
  if (report.integration?.backend === 'python-engine') return `Python ${report.integration.engine}`;
  if (report.integration?.backend === 'local-rule-engine') return 'Local fallback';
  if (report.integration?.backend === 'seed') return 'Seed report';
  return 'Engine report';
}

function riskTone(risk: string) {
  if (risk === 'CRITICAL' || risk === 'HIGH') return 'tone-red';
  if (risk === 'MEDIUM') return 'tone-amber';
  return 'tone-green';
}

function verifierTone(status: string) {
  if (status === 'FAIL') return 'tone-red';
  if (status === 'PARTIAL') return 'tone-amber';
  return 'tone-green';
}

function opinionTone(opinion: string) {
  if (opinion === 'REJECT') return 'tone-red';
  if (opinion === 'AMEND' || opinion === 'HUMAN') return 'tone-amber';
  return 'tone-green';
}

function severityTone(severity?: string) {
  if (severity === 'CRITICAL' || severity === 'HIGH') return 'tone-red';
  if (severity === 'MEDIUM') return 'tone-amber';
  return 'tone-neutral';
}

function redactSensitive(content: string) {
  return content
    .replace(/\b\d{6}-[1-4]\d{6}\b/g, '[주민등록번호 마스킹]')
    .replace(/\b010[-.]?\d{3,4}[-.]?\d{4}\b/g, '[전화번호 마스킹]')
    .replace(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g, '[이메일 마스킹]')
    .replace(/\b\d{3,6}-\d{2,6}-\d{3,6}\b/g, '[계좌번호 마스킹]');
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asString(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function asOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}
