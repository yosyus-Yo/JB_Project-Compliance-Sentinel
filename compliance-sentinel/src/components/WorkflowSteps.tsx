import {
  CheckCircle2,
  Circle,
  Eye,
  FileSearch,
  Gavel,
  Lock,
  Scale,
  Send,
  ShieldCheck,
  Tags,
  Workflow,
} from 'lucide-react';
import type { ComplianceReport } from '../types.js';

interface StepDef {
  id: string;
  label: string;
  Icon: typeof CheckCircle2;
}

const STEPS: StepDef[] = [
  { id: 'pii', label: 'PII 제거', Icon: Lock },
  { id: 'classify', label: '분류', Icon: Tags },
  { id: 'law', label: '법령 검색', Icon: FileSearch },
  { id: 'board', label: '6인 보드', Icon: Scale },
  { id: 'ceo', label: 'CEO 종합', Icon: Gavel },
  { id: 'verifier', label: 'Verifier 검증', Icon: ShieldCheck },
  { id: 'routing', label: '승인 라우팅', Icon: Workflow },
  { id: 'publish', label: '외부 공유', Icon: Send },
  { id: 'audit', label: '감사 로그', Icon: Eye },
];

function deriveStatus(report: ComplianceReport): Record<string, boolean> {
  return {
    pii: Boolean(report.guard_flags),
    classify: Boolean(
      report.input_completeness?.accepted ||
        report.channel ||
        report.product_type ||
        report.language,
    ),
    law:
      report.findings?.some((f) => Boolean(f.law_name || f.article_no)) ||
      (report.evidence?.length ?? 0) > 0,
    board: (report.board_diagnostics?.length ?? 0) > 0,
    ceo: Boolean(report.summary),
    verifier: Boolean(report.verifier_result?.status),
    routing: Boolean(report.approval_status),
    publish: Boolean(report.workflow_publish_plan || report.workflow_exports),
    audit: Boolean(report.audit_log_id),
  };
}

interface Props {
  report: ComplianceReport;
}

export default function WorkflowSteps({ report }: Props) {
  const status = deriveStatus(report);
  const doneCount = Object.values(status).filter(Boolean).length;

  return (
    <section className="panel" id="workflow-9-steps">
      <div className="section-title">
        <div>
          <p className="eyebrow">Pipeline</p>
          <h2>9단계 심의 워크플로우</h2>
        </div>
        <span className="mini-chip strong">{doneCount}/9 완료</span>
      </div>

      <ol className="workflow-steps">
        {STEPS.map((step, idx) => {
          const done = status[step.id];
          const Icon = done ? CheckCircle2 : Circle;
          return (
            <li
              key={step.id}
              className={`workflow-step ${done ? 'is-done' : 'is-pending'}`}
              data-step={idx + 1}
            >
              <div className="workflow-step-marker">
                <Icon className="h-4 w-4" />
              </div>
              <div className="workflow-step-body">
                <span className="workflow-step-num">{String(idx + 1).padStart(2, '0')}</span>
                <span className="workflow-step-label">
                  <step.Icon className="h-3.5 w-3.5 inline-block mr-1 align-text-bottom" />
                  {step.label}
                </span>
              </div>
              {idx < STEPS.length - 1 && (
                <span className={`workflow-step-arrow ${done ? 'is-done' : ''}`} aria-hidden="true">
                  →
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
