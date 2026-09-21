import { useCallback, useEffect, useRef, useState } from 'react';

type RecState = 'idle' | 'requesting' | 'recording' | 'stopping' | 'error';
interface UseMediaRecorder {
  state: RecState;
  start: () => Promise<void>;
  stop: () => Promise<Blob | null>;
  durationMs: number;
  errorMessage: string | null;
}

export const MAX_RECORDING_MS = 10 * 60 * 1000;
export const MAX_RECORDING_BYTES = 25 * 1024 * 1024;
const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];

interface Capture {
  stream?: MediaStream;
  recorder?: MediaRecorder;
  chunks: Blob[];
  bytes: number;
  startedAt: number;
  tick?: ReturnType<typeof setInterval>;
  deadline?: ReturnType<typeof setTimeout>;
  stopping: boolean;
  result: Promise<Blob | null>;
  resolve: (blob: Blob | null) => void;
}

function microphoneErrorMessage(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
      return '没有麦克风权限，请在浏览器设置中允许访问后重试。';
    }
    if (error.name === 'NotFoundError') return '没有检测到可用麦克风，请连接设备后重试。';
    if (error.name === 'NotReadableError') return '麦克风正被其他程序占用，请关闭占用程序后重试。';
  }
  return '麦克风启动失败，请检查设备或改用文字回答。';
}

function dispose(capture: Capture) {
  clearInterval(capture.tick);
  clearTimeout(capture.deadline);
  const recorder = capture.recorder;
  if (recorder) {
    recorder.ondataavailable = null;
    recorder.onstop = null;
    recorder.onerror = null;
    try { if (recorder.state !== 'inactive') recorder.stop(); } catch { /* stop tracks below */ }
  }
  capture.stream?.getTracks().forEach((track) => track.stop());
  capture.chunks = [];
}

export function useMediaRecorder(): UseMediaRecorder {
  const [state, setState] = useState<RecState>('idle');
  const [durationMs, setDurationMs] = useState(0);
  const [errorMessage, setError] = useState<string | null>(null);
  const active = useRef<Capture | null>(null);
  const mounted = useRef(false);

  const finish = useCallback((capture: Capture, blob: Blob | null, error?: string) => {
    if (active.current !== capture) return;
    active.current = null; // Invalidate callbacks before stopping device resources.
    dispose(capture);
    capture.resolve(blob);
    if (mounted.current) {
      setState(error ? 'error' : 'idle');
      if (error) setError(error);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (active.current) finish(active.current, null);
    };
  }, [finish]);

  const start = useCallback(async () => {
    if (!mounted.current || active.current) return;
    let resolve!: Capture['resolve'];
    const result = new Promise<Blob | null>((done) => { resolve = done; });
    const capture: Capture = { chunks: [], bytes: 0, startedAt: 0, stopping: false, result, resolve };
    active.current = capture; // Synchronous guard also covers rapid double clicks.
    const current = () => mounted.current && active.current === capture;
    setError(null);
    setState('requesting');
    capture.deadline = setTimeout(() => finish(capture, null, '麦克风授权超时，请重试或改用文字回答。'), 60_000);
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
        throw new Error('microphone_not_supported');
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // getUserMedia cannot be aborted. A late grant belongs to the old request,
      // never to a newer recording or an unmounted page; release it immediately.
      if (!current()) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      clearTimeout(capture.deadline);
      capture.stream = stream;
      const mime = MIME_CANDIDATES.find((item) => MediaRecorder.isTypeSupported(item));
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      capture.recorder = recorder;
      recorder.ondataavailable = (event) => {
        if (!current() || !event.data?.size) return;
        capture.bytes += event.data.size;
        if (capture.bytes > MAX_RECORDING_BYTES) {
          finish(capture, null, '录音超过 25 MB 上限，请缩短回答或改用文字。');
          return;
        }
        capture.chunks.push(event.data);
      };
      recorder.onerror = () => finish(capture, null, '录音设备发生错误，请重新录制或改用文字。');
      recorder.onstop = () => {
        if (!current()) return;
        const blob = capture.chunks.length ? new Blob(capture.chunks, { type: recorder.mimeType || 'audio/webm' }) : null;
        finish(capture, blob);
      };
      // Periodic delivery lets us enforce a real accumulated byte budget.
      recorder.start(1000);
      capture.startedAt = performance.now();
      setDurationMs(0);
      capture.tick = setInterval(() => {
        if (current()) setDurationMs(Math.max(0, performance.now() - capture.startedAt));
      }, 200);
      capture.deadline = setTimeout(() => finish(capture, null, '录音超过 10 分钟上限，请缩短回答或改用文字。'), MAX_RECORDING_MS);
      setState('recording');
    } catch (error) {
      if (current()) finish(capture, null, microphoneErrorMessage(error));
    }
  }, [finish]);

  const stop = useCallback((): Promise<Blob | null> => {
    const capture = active.current;
    if (!capture) return Promise.resolve(null);
    if (!capture.recorder) {
      finish(capture, null); // Fence an unresolved permission request too.
      return capture.result;
    }
    if (capture.stopping) return capture.result; // Do not replace another caller's resolver.
    capture.stopping = true;
    if (mounted.current) setState('stopping');
    clearInterval(capture.tick);
    clearTimeout(capture.deadline);
    capture.deadline = setTimeout(() => finish(capture, null, '录音结束超时，请重新录制或改用文字。'), 5000);
    try {
      // An inactive recorder may still have its final data/onstop queued.
      if (capture.recorder.state !== 'inactive') capture.recorder.stop();
    } catch {
      finish(capture, null, '录音结束失败，请重新录制或改用文字。');
    }
    return capture.result;
  }, [finish]);

  return { state, start, stop, durationMs, errorMessage };
}
