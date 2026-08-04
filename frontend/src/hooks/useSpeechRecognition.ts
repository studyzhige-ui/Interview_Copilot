/**
 * Web Speech API wrapper for in-browser STT.
 *
 * Why have this when the backend already exposes /transcribe?
 *   - Zero round-trip: partial transcripts appear as the user speaks.
 *   - Zero infra: no Whisper warmup, no S3 audio retention.
 *   - Free: uses the browser's built-in recognizer.
 *
 * Cost: only Chromium-family browsers (Chrome / Edge / Brave) ship a working
 * implementation today. We feature-detect and let callers fall back to the
 * MediaRecorder → /transcribe path when unavailable.
 *
 * State machine: idle → listening (continuous) → idle. The `interim` field
 * streams partial results so the UI can render a live caption; `finalText`
 * accumulates only finalized fragments.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

type Phase = 'idle' | 'listening' | 'error';

interface State {
  phase: Phase;
  finalText: string;
  interim: string;
  message?: string;
}

interface RecognitionEvent {
  resultIndex: number;
  results: ArrayLike<{
    0: { transcript: string };
    isFinal: boolean;
    length: number;
  }>;
}

interface RecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: RecognitionEvent) => void) | null;
  onerror: ((e: { error?: string; message?: string }) => void) | null;
  onend: (() => void) | null;
}

type RecognitionCtor = new () => RecognitionLike;

function getRecognitionCtor(): RecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const SPEECH_RECOGNITION_AVAILABLE = getRecognitionCtor() !== null;

export function useSpeechRecognition(lang = 'zh-CN') {
  const [state, setState] = useState<State>({ phase: 'idle', finalText: '', interim: '' });
  const recRef = useRef<RecognitionLike | null>(null);
  const transcriptRef = useRef({ finalText: '', interim: '' });
  const stopResolveRef = useRef<((text: string) => void) | null>(null);

  const stop = useCallback((): Promise<string> => {
    const rec = recRef.current;
    if (!rec) {
      return Promise.resolve(
        (transcriptRef.current.finalText + transcriptRef.current.interim).trim(),
      );
    }
    return new Promise((resolve) => {
      stopResolveRef.current = resolve;
      try {
        rec.stop();
      } catch {
        stopResolveRef.current = null;
        resolve((transcriptRef.current.finalText + transcriptRef.current.interim).trim());
      }
    });
  }, []);

  const reset = useCallback(() => {
    transcriptRef.current = { finalText: '', interim: '' };
    setState({ phase: 'idle', finalText: '', interim: '' });
  }, []);

  const start = useCallback(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) {
      setState({
        phase: 'error',
        finalText: '',
        interim: '',
        message: '浏览器不支持原生语音识别（请用 Chrome/Edge）',
      });
      return;
    }
    const rec = new Ctor();
    rec.lang = lang;
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (e: RecognitionEvent) => {
      let finalChunk = '';
      let interimChunk = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        const t = r[0].transcript;
        if (r.isFinal) finalChunk += t;
        else interimChunk += t;
      }
      transcriptRef.current = {
        finalText: transcriptRef.current.finalText + finalChunk,
        interim: interimChunk,
      };
      setState((s) => ({
        phase: 'listening',
        finalText: s.finalText + finalChunk,
        interim: interimChunk,
      }));
    };
    rec.onerror = (e) => {
      setState((s) => ({
        phase: 'error',
        finalText: s.finalText,
        interim: '',
        message: e.error || e.message || 'recognition error',
      }));
      stopResolveRef.current?.(
        (transcriptRef.current.finalText + transcriptRef.current.interim).trim(),
      );
      stopResolveRef.current = null;
    };
    rec.onend = () => {
      const text = (transcriptRef.current.finalText + transcriptRef.current.interim).trim();
      transcriptRef.current.interim = '';
      recRef.current = null;
      setState((s) => (s.phase === 'listening'
        ? { ...s, phase: 'idle', interim: '' }
        : s));
      stopResolveRef.current?.(text);
      stopResolveRef.current = null;
    };
    recRef.current = rec;
    transcriptRef.current = { finalText: '', interim: '' };
    setState({ phase: 'listening', finalText: '', interim: '' });
    try {
      rec.start();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'start failed';
      setState({ phase: 'error', finalText: '', interim: '', message: msg });
    }
  }, [lang]);

  useEffect(() => {
    return () => {
      try {
        recRef.current?.abort();
      } catch {
        /* ignore */
      }
      stopResolveRef.current?.('');
      stopResolveRef.current = null;
    };
  }, []);

  return { state, start, stop, reset, available: SPEECH_RECOGNITION_AVAILABLE };
}
