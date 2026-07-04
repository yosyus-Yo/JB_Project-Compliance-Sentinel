import type { ComplianceReport } from './types.js';

export type ReviewNodeStatus = 'start' | 'complete';

export interface ReviewStreamRequest {
  content: string;
  metadata?: Record<string, unknown>;
  /** 입력 시 "수정 제안 생성" 토글. true면 수정 원고/제안 생성, 미지정/false면 심의만. */
  include_revision?: boolean;
}

export interface ReviewStreamCallbacks {
  onNode: (node: string, status: ReviewNodeStatus) => void;
  signal?: AbortSignal;
}

interface ParsedFrame {
  event: string;
  data: unknown;
}

/**
 * Subscribe to the realtime review SSE stream (`POST /api/review/stream`) and
 * drive the loader UI (T4 of realtime-loader-langgraph-design).
 *
 * Each LangGraph node emits a `data:` frame consumed via `onNode`; the terminal
 * `event: result` frame resolves to the final {@link ComplianceReport}. Transport
 * failures and `event: error` frames throw so callers can fall back to the
 * non-streaming `/api/review` endpoint without losing the verdict.
 */
export async function streamReview(
  request: ReviewStreamRequest,
  callbacks: ReviewStreamCallbacks,
): Promise<ComplianceReport> {
  const res = await fetch('/api/review/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal: callbacks.signal,
  });

  if (!res.ok || !res.body) {
    throw new Error(`review_stream_http_${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let result: ComplianceReport | null = null;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line ("\n\n").
      let sep: number;
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const parsed = parseFrame(frame);
        if (!parsed) continue;
        if (parsed.event === 'result') {
          result = parsed.data as ComplianceReport;
        } else if (parsed.event === 'error') {
          throw new Error(`review_stream_error:${JSON.stringify(parsed.data).slice(0, 200)}`);
        } else {
          const node = parsed.data as { node?: string; status?: ReviewNodeStatus };
          if (node.node && node.status) {
            callbacks.onNode(node.node, node.status);
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  if (!result) {
    throw new Error('review_stream_no_result');
  }
  return result;
}

function parseFrame(frame: string): ParsedFrame | null {
  let event = 'message';
  let dataStr = '';
  for (const rawLine of frame.split('\n')) {
    const line = rawLine.replace(/\r$/, '');
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      // Accumulate multi-line data fields per the SSE spec.
      dataStr += line.slice(5).trim();
    }
  }
  if (!dataStr) return null;
  try {
    return { event, data: JSON.parse(dataStr) };
  } catch {
    return null;
  }
}
