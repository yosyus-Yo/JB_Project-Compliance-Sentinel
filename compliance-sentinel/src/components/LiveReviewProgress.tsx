import { CheckCircle2, Circle, Loader2 } from 'lucide-react';
import type { ReviewNodeStatus } from '../streamReview.js';

interface StreamStep {
  node: string;
  label: string;
}

// 노드 → UI 단계 매핑. 광고(marketing)와 약관/일반(compliance) 경로는 노드명이 다르므로
// 두 시퀀스를 별도로 정의하고, 들어온 노드로 경로를 감지해 해당 시퀀스를 표시한다.
// (compliance 경로에서 로더가 일부만 켜지던 버그 수정 — 노드명 불일치)
// final_report 노드는 완료 신호이므로 별도 단계로 표시하지 않는다.
const MARKETING_STEPS: StreamStep[] = [
  { node: 'content_intake', label: '콘텐츠 입력·정규화' },
  { node: 'understand_content', label: '언어·상품유형 분류' },
  { node: 'memory_review', label: '과거 사례·법률 RAG 조회' },
  { node: 'llm_advisory_board', label: '6인 자문 보드 심의' },
  { node: 'synthesize', label: '종합 판정' },
  { node: 'independent_validation', label: '독립 검증' },
  { node: 'human_review_gate', label: '사람 검토 판정' },
];

const COMPLIANCE_STEPS: StreamStep[] = [
  { node: 'classify_input', label: '입력 유형 분류' },
  { node: 'pii_guard', label: '개인정보 마스킹' },
  { node: 'retrieve_context', label: '법령 RAG 조회' },
  { node: 'board_review', label: '6인 컴플라이언스 보드 심의' },
  { node: 'synthesize', label: '종합 판정' },
  { node: 'verify_atomic_claims', label: '원자적 법령 검증' },
  { node: 'independent_validation', label: '독립 검증' },
];

// compliance 전용 노드가 하나라도 보이면 약관/일반 경로로 판단.
const COMPLIANCE_MARKERS = ['classify_input', 'pii_guard', 'retrieve_context', 'board_review', 'verify_atomic_claims'];

interface Props {
  nodes: Record<string, ReviewNodeStatus>;
}

export default function LiveReviewProgress({ nodes }: Props) {
  const isCompliance = COMPLIANCE_MARKERS.some((n) => nodes[n]);
  const STREAM_STEPS = isCompliance ? COMPLIANCE_STEPS : MARKETING_STEPS;
  const doneCount = STREAM_STEPS.filter((s) => nodes[s.node] === 'complete').length;
  const pct = Math.round((doneCount / STREAM_STEPS.length) * 100);

  return (
    <div className="w-full max-w-md bg-slate-50 border border-slate-200/80 rounded-xl p-5 space-y-3.5">
      <div className="flex justify-between text-[11px] font-mono font-bold text-slate-400">
        <span>실시간 단계 진행</span>
        <span>
          {doneCount}/{STREAM_STEPS.length} 완료
        </span>
      </div>
      <div className="w-full bg-slate-200/60 h-2 rounded-full overflow-hidden">
        <div
          className="bg-slate-800 h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <ol className="pt-1 space-y-1.5">
        {STREAM_STEPS.map((step, idx) => {
          const status = nodes[step.node];
          const isDone = status === 'complete';
          const isActive = status === 'start';
          return (
            <li
              key={step.node}
              data-node={step.node}
              data-state={isDone ? 'done' : isActive ? 'active' : 'pending'}
              className={`flex items-center gap-2 text-xs font-medium transition-colors ${
                isDone ? 'text-slate-700' : isActive ? 'text-slate-900' : 'text-slate-400'
              }`}
            >
              <span className="shrink-0">
                {isDone ? (
                  <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                ) : isActive ? (
                  <Loader2 className="h-4 w-4 text-slate-800 animate-spin" />
                ) : (
                  <Circle className="h-4 w-4 text-slate-300" />
                )}
              </span>
              <span className="font-mono text-[10px] text-slate-400 w-5">
                {String(idx + 1).padStart(2, '0')}
              </span>
              <span>{step.label}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
