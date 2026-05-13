import { useEffect, useRef, useState } from 'react';
import { tokenStore } from '@/lib/token';

// SSE event shapes (per backend/app/api/interview.py:analyze_events_stream)
export type AnalysisEvent =
  | { type: 'progress'; status: string; percent: number }
  | { type: 'done'; interview_id: number; status: string; percent: number; analysis?: unknown }
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
  interviewId: number | null,
  onDone?: (analysis: unknown) => void,
  onError?: (msg: string) => void,
): AnalysisState {
  const [state, setState] = useState<AnalysisState>({ phase: 'idle', percent: 0 });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (interviewId === null) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ phase: 'connecting', percent: 0 });

    (async () => {
      try {
        const token = tokenStore.getAccess() ?? '';
        const res = await fetch(`/api/v1/analyze/${interviewId}/events`, {
          headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' },
          signal: controller.signal,
        });
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
  }, [interviewId]);

  return state;
}
