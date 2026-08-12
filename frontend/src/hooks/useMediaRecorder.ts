import { useCallback, useEffect, useRef, useState } from 'react';

type RecState = 'idle' | 'requesting' | 'recording' | 'stopping' | 'error';

interface UseMediaRecorder {
  state: RecState;
  start: () => Promise<void>;
  stop: () => Promise<Blob | null>;
  durationMs: number;
  errorMessage: string | null;
}

const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];

function pickMime(): string {
  for (const m of MIME_CANDIDATES) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(m)) return m;
  }
  return '';
}

function microphoneErrorMessage(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
      return '没有麦克风权限，请在浏览器设置中允许访问后重试。';
    }
    if (error.name === 'NotFoundError') {
      return '没有检测到可用麦克风，请连接设备后重试。';
    }
    if (error.name === 'NotReadableError') {
      return '麦克风正被其他程序占用，请关闭占用程序后重试。';
    }
  }
  return '麦克风启动失败，请检查设备或改用文字回答。';
}

export function useMediaRecorder(): UseMediaRecorder {
  const [state, setState] = useState<RecState>('idle');
  const [durationMs, setDurationMs] = useState(0);
  const [errorMessage, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const startedAtRef = useRef<number>(0);
  const tickRef = useRef<number | null>(null);

  const cleanup = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recorderRef.current = null;
    if (tickRef.current !== null) {
      window.clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(async () => {
    if (state === 'recording' || state === 'requesting') return;
    setError(null);
    setState('requesting');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mime = pickMime();
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      recorderRef.current = rec;
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.start();
      startedAtRef.current = Date.now();
      setDurationMs(0);
      tickRef.current = window.setInterval(
        () => setDurationMs(Date.now() - startedAtRef.current),
        200,
      );
      setState('recording');
    } catch (err) {
      cleanup();
      setError(microphoneErrorMessage(err));
      setState('error');
    }
  }, [state, cleanup]);

  const stop = useCallback(async (): Promise<Blob | null> => {
    const rec = recorderRef.current;
    if (!rec || rec.state === 'inactive') {
      cleanup();
      setState('idle');
      return null;
    }
    setState('stopping');
    return new Promise<Blob | null>((resolve) => {
      rec.onstop = () => {
        const type = rec.mimeType || 'audio/webm';
        const blob = chunksRef.current.length > 0 ? new Blob(chunksRef.current, { type }) : null;
        chunksRef.current = [];
        cleanup();
        setState('idle');
        resolve(blob);
      };
      try {
        rec.stop();
      } catch {
        cleanup();
        setState('idle');
        resolve(null);
      }
    });
  }, [cleanup]);

  return { state, start, stop, durationMs, errorMessage };
}
