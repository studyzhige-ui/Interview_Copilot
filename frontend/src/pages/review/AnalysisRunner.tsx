import { useEffect } from 'react';
import { tokenStore } from '@/lib/token';

export interface AnalysisProgress {
  phase: 'connecting' | 'progress' | 'done' | 'error';
  percent: number;
  status?: string;
  message?: string;
}

interface Props {
  recordId: string;
  onProgress: (p: AnalysisProgress) => void;
  onDone: (analysis: unknown) => void;
  onError: (message: string) => void;
}

interface ProgressEvent { type: 'progress'; status: string; percent: number; analyzed_qa_count?: number }
interface DoneEvent { type: 'done'; record_id: string; status: string; percent: number; analysis?: unknown }
interface ErrorEvent { type: 'error'; status?: string; message?: string }
type Event = ProgressEvent | DoneEvent | ErrorEvent;

/**
 * Headless component that subscribes to /interview-records/{id}/events SSE for
 * a single record_id. Mounting starts the stream; unmounting aborts it. Lives
 * in ReviewPage so it survives even when the user navigates away from the
 * UploadCards that started it.
 */
export function AnalysisRunner({ recordId, onProgress, onDone, onError }: Props) {
  useEffect(() => {
    const controller = new AbortController();
    onProgress({ phase: 'connecting', percent: 0 });

    (async () => {
      try {
        const token = tokenStore.getAccess() ?? '';
        const res = await fetch(`/api/v1/interview-records/${encodeURIComponent(recordId)}/events`, {
          headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' },
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          const msg = `HTTP ${res.status}`;
          onProgress({ phase: 'error', percent: 0, message: msg });
          onError(msg);
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
            let evt: Event;
            try { evt = JSON.parse(payload); } catch { continue; }
            if (evt.type === 'progress') {
              onProgress({ phase: 'progress', percent: evt.percent, status: evt.status });
            } else if (evt.type === 'done') {
              onProgress({ phase: 'done', percent: 100, status: evt.status });
              onDone(evt.analysis);
              return;
            } else if (evt.type === 'error') {
              const msg = evt.message ?? evt.status ?? 'unknown';
              onProgress({ phase: 'error', percent: 0, message: msg });
              onError(msg);
              return;
            }
          }
        }
      } catch (err) {
        if ((err as { name?: string }).name === 'AbortError') return;
        const msg = err instanceof Error ? err.message : 'stream error';
        onProgress({ phase: 'error', percent: 0, message: msg });
        onError(msg);
      }
    })();

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordId]);

  return null;
}
