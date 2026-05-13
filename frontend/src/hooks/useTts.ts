/**
 * Minimal TTS hook for the mock-interview interviewer voice.
 *
 * Sends interviewer text to POST /chat/mock-interview/tts which fronts
 * edge-tts on the backend and returns audio/mpeg bytes. We blob-URL the
 * response and play through a single shared <audio> element so a new utterance
 * cancels the previous one (real interviewers don't talk over themselves).
 *
 * The hook is intentionally not "streaming" — edge-tts can synthesize a 2-3
 * sentence interviewer reply in ~500ms, and the playback latency is bounded by
 * one round-trip plus the audio length. Sentence-level chunking is a future
 * optimization once we move to a streaming TTS provider.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from '@/api/client';

export type TtsState =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'playing' }
  | { phase: 'error'; message: string };

interface UseTtsOptions {
  enabled: boolean;
  voice?: string;
}

export function useTts({ enabled, voice }: UseTtsOptions) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastUrlRef = useRef<string | null>(null);
  const [state, setState] = useState<TtsState>({ phase: 'idle' });

  // Lazily create the audio element on first speak() — Safari needs an
  // element constructed inside a user gesture frame for autoplay to work.
  const ensureAudio = useCallback((): HTMLAudioElement => {
    if (audioRef.current) return audioRef.current;
    const el = new Audio();
    el.preload = 'auto';
    el.onended = () => setState({ phase: 'idle' });
    el.onerror = () => setState({ phase: 'error', message: '音频播放失败' });
    audioRef.current = el;
    return el;
  }, []);

  const stop = useCallback(() => {
    const el = audioRef.current;
    if (el) {
      el.pause();
      el.currentTime = 0;
    }
    if (lastUrlRef.current) {
      URL.revokeObjectURL(lastUrlRef.current);
      lastUrlRef.current = null;
    }
    setState({ phase: 'idle' });
  }, []);

  const speak = useCallback(
    async (text: string) => {
      if (!enabled) return;
      const trimmed = text.trim();
      if (!trimmed) return;

      stop();
      const el = ensureAudio();
      setState({ phase: 'loading' });

      try {
        const res = await apiClient.post(
          '/chat/mock-interview/tts',
          { text: trimmed, voice },
          { responseType: 'blob' },
        );
        const blob = res.data as Blob;
        const url = URL.createObjectURL(blob);
        lastUrlRef.current = url;
        el.src = url;
        await el.play();
        setState({ phase: 'playing' });
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'TTS 失败';
        setState({ phase: 'error', message: msg });
      }
    },
    [enabled, voice, ensureAudio, stop],
  );

  useEffect(() => {
    return () => {
      if (lastUrlRef.current) URL.revokeObjectURL(lastUrlRef.current);
      audioRef.current?.pause();
    };
  }, []);

  return { state, speak, stop };
}
