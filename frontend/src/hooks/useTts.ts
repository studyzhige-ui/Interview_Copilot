/** One active playback generation; stopping also invalidates late responses. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from '@/api/client';

type TtsState =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'playing' }
  | { phase: 'error'; message: string };

interface UseTtsOptions {
  enabled: boolean;
  voice?: string;
}

interface Speech {
  generation: number;
  abort: AbortController;
  audio: HTMLAudioElement;
  url: string | null;
}

function dispose(speech: Speech) {
  speech.abort.abort();
  speech.audio.onended = null;
  speech.audio.onerror = null;
  speech.audio.pause();
  speech.audio.removeAttribute('src');
  speech.audio.load();
  if (speech.url) {
    URL.revokeObjectURL(speech.url);
    speech.url = null;
  }
}

export function useTts({ enabled, voice }: UseTtsOptions) {
  const active = useRef<Speech | null>(null);
  const generation = useRef(0);
  const mounted = useRef(false);
  const [state, setState] = useState<TtsState>({ phase: 'idle' });

  const invalidate = useCallback(() => {
    generation.current += 1;
    const previous = active.current;
    active.current = null; // Fence callbacks before abort/pause can dispatch them.
    if (previous) dispose(previous);
  }, []);

  const stop = useCallback(() => {
    invalidate();
    if (mounted.current) setState({ phase: 'idle' });
  }, [invalidate]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      invalidate();
    };
  }, [invalidate]);

  // Muting, changing the selected voice and leaving the page cancel the same
  // owned request. Re-enabling audio never replays a cancelled generation.
  useEffect(() => {
    if (!enabled) stop();
    return stop;
  }, [enabled, voice, stop]);

  const speak = useCallback(async (text: string) => {
    if (!enabled || !mounted.current || !text.trim()) return;
    stop();
    if (text.length > 600) {
      setState({ phase: 'error', message: '本地朗读每次最多 600 字，请阅读完整文字；不会截断内容。' });
      return;
    }
    const speech: Speech = {
      generation: generation.current,
      abort: new AbortController(),
      audio: new Audio(),
      url: null,
    };
    active.current = speech;
    const isCurrent = () => mounted.current
      && active.current === speech
      && generation.current === speech.generation
      && !speech.abort.signal.aborted;
    const finish = (next: TtsState) => {
      if (!isCurrent()) return;
      active.current = null;
      dispose(speech);
      setState(next);
    };
    speech.audio.preload = 'auto';
    speech.audio.onended = () => finish({ phase: 'idle' });
    speech.audio.onerror = () => finish({ phase: 'error', message: '音频播放失败' });
    setState({ phase: 'loading' });
    try {
      const response = await apiClient.post(
        '/mock-interviews/tts',
        { text: text.trim(), voice: voice === 'default' ? undefined : voice },
        { responseType: 'blob', signal: speech.abort.signal },
      );
      // Abort is best effort. A response can already be queued, or an adapter
      // may ignore it; generation identity is the authoritative playback fence.
      if (!isCurrent()) return;
      const blob = response.data;
      if (!(blob instanceof Blob) || !blob.size || blob.size > 10_000_000) {
        throw new Error('语音响应为空或超出大小限制');
      }
      speech.url = URL.createObjectURL(blob);
      speech.audio.src = speech.url;
      await speech.audio.play();
      if (isCurrent()) setState({ phase: 'playing' });
    } catch (error) {
      finish({ phase: 'error', message: error instanceof Error ? error.message : 'TTS 失败' });
    }
  }, [enabled, voice, stop]);

  return { state, speak, stop };
}
