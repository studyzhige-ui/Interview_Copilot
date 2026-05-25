import { useEffect, useRef, useState } from 'react';
import { authedFetch } from '@/api/client';

// SSE event shapes (per backend/app/api/interview.py:interview_record_events_stream)
export type AnalysisEvent =
  | { type: 'progress'; status: string; percent: number; analyzed_qa_count?: number }
  | { type: 'done'; record_id: string; status: string; percent: number; analysis?: unknown }
  | { type: 'error'; status?: string; message?: string };

export interface AnalysisState {
  phase: 'idle' | 'connecting' | 'progress' | 'done' | 'error';
  status?: string;
  percent: number;
  message?: string;
}

// Browser EventSource can't send Authorization headers, so we roll our own
// minimal SSE consumer over fetch + ReadableStream. We parse text/event-stream
// frames split by blank line and surface "data: {...}" payloads only.
export function useAnalysisStream(
  recordId: string | null,
  onDone?: (analysis: unknown) => void,
  onError?: (msg: string) => void,
): AnalysisState {
  const [state, setState] = useState<AnalysisState>({ phase: 'idle', percent: 0 });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!recordId) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ phase: 'connecting', percent: 0 });

    (async () => {
      try {
        // ``authedFetch`` handles bearer + 401-refresh-retry — without
        // it an expired access token would surface here as an opaque
        // "HTTP 401" message and the user couldn't recover without a
        // manual page reload.
        const res = await authedFetch(
          `/api/v1/interview-records/${encodeURIComponent(recordId)}/events`,
          {
            headers: { Accept: 'text/event-stream' },
            signal: controller.signal,
          },
        );
        if (!res.ok || !res.body) {
          setState({ phase: 'error', percent: 0, message: `HTTP ${res.status}` });
          onError?.(`HTTP ${res.status}`);
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';

        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const frames = buf.split('\n\n');
          buf = frames.pop() ?? '';
          for (const frame of frames) {
            const line = frame.split('\n').find((l) => l.startsWith('data: '));
            if (!line) continue;
            const payload = line.slice(6).trim();
            if (!payload) continue;
            let evt: AnalysisEvent;
            try {
              evt = JSON.parse(payload);
            } catch {
              continue;
            }
            if (evt.type === 'progress') {
              setState({ phase: 'progress', status: evt.status, percent: evt.percent });
            } else if (evt.type === 'done') {
              setState({ phase: 'done', status: evt.status, percent: 100 });
              onDone?.(evt.analysis);
              return;
            } else if (evt.type === 'error') {
              const msg = evt.message ?? evt.status ?? 'unknown';
              setState({ phase: 'error', percent: 0, message: msg });
              onError?.(msg);
              return;
            }
          }
        }
      } catch (err) {
        if ((err as { name?: string }).name === 'AbortError') return;
        const msg = err instanceof Error ? err.message : 'stream error';
        setState({ phase: 'error', percent: 0, message: msg });
        onError?.(msg);
      }
    })();

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordId]);

  return state;
}
