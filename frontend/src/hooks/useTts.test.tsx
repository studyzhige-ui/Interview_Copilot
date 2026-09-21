import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useTts } from './useTts';
import { apiClient } from '@/api/client';

vi.mock('@/api/client', () => ({ apiClient: { post: vi.fn() } }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const players: FakeAudio[] = [];
class FakeAudio {
  preload = '';
  src = '';
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  play = vi.fn().mockResolvedValue(undefined);
  pause = vi.fn();
  load = vi.fn();
  removeAttribute = vi.fn((key: string) => { if (key === 'src') this.src = ''; });
  constructor() { players.push(this); }
}

const response = () => ({ data: new Blob(['audio'], { type: 'audio/mpeg' }) });
const post = vi.mocked(apiClient.post);
const create = vi.fn(() => `blob:tts-${players.length}`);
const revoke = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  players.length = 0;
  vi.stubGlobal('Audio', FakeAudio);
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('TTS playback generation', () => {
  it('stopping aborts the request and discards a response that ignores cancellation', async () => {
    const request = deferred<ReturnType<typeof response>>();
    post.mockReturnValueOnce(request.promise);
    const { result } = renderHook(() => useTts({ enabled: true }));
    let speaking!: Promise<void>;
    act(() => { speaking = result.current.speak('first'); });
    const signal = post.mock.calls[0][2]?.signal;
    act(() => result.current.stop());
    expect(signal?.aborted).toBe(true);
    await act(async () => { request.resolve(response()); await speaking; });
    expect(players[0].play).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
    expect(result.current.state.phase).toBe('idle');
  });

  it('a late previous response cannot replace newer playback', async () => {
    const old = deferred<ReturnType<typeof response>>();
    post.mockReturnValueOnce(old.promise).mockResolvedValueOnce(response());
    const { result } = renderHook(() => useTts({ enabled: true }));
    let first!: Promise<void>;
    act(() => { first = result.current.speak('first'); });
    await act(() => result.current.speak('second'));
    const currentUrl = players[1].src;
    await act(async () => { old.resolve(response()); await first; });
    expect(players[0].play).not.toHaveBeenCalled();
    expect(players[1].src).toBe(currentUrl);
    expect(players[1].play).toHaveBeenCalledTimes(1);
    expect(result.current.state.phase).toBe('playing');
  });

  it('a late previous rejection or event cannot clear newer audio', async () => {
    const old = deferred<ReturnType<typeof response>>();
    post.mockReturnValueOnce(old.promise).mockResolvedValueOnce(response());
    const { result } = renderHook(() => useTts({ enabled: true }));
    let first!: Promise<void>;
    act(() => { first = result.current.speak('first'); });
    const previousEnded = players[0].onended;
    const previousError = players[0].onerror;
    await act(() => result.current.speak('second'));
    const currentUrl = players[1].src;
    await act(async () => {
      old.reject(new Error('stale failure'));
      previousEnded?.(); previousError?.();
      await first;
    });
    expect(players[1].src).toBe(currentUrl);
    expect(result.current.state.phase).toBe('playing');
    expect(revoke).not.toHaveBeenCalledWith(currentUrl);
  });

  it('stopping during play() prevents its late resolution from setting playing', async () => {
    const request = deferred<ReturnType<typeof response>>();
    const play = deferred<void>();
    post.mockReturnValueOnce(request.promise);
    const { result } = renderHook(() => useTts({ enabled: true }));
    let speaking!: Promise<void>;
    act(() => { speaking = result.current.speak('first'); });
    players[0].play.mockReturnValueOnce(play.promise);
    await act(async () => { request.resolve(response()); await Promise.resolve(); });
    const url = players[0].src;
    act(() => result.current.stop());
    await act(async () => { play.resolve(); await speaking; });
    expect(result.current.state.phase).toBe('idle');
    expect(players[0].src).toBe('');
    expect(revoke).toHaveBeenCalledWith(url);
  });

  it.each(['mute', 'voice'] as const)('%s cancels a pending generation', async (change) => {
    const request = deferred<ReturnType<typeof response>>();
    post.mockReturnValueOnce(request.promise);
    const { result, rerender } = renderHook((props) => useTts(props), {
      initialProps: { enabled: true, voice: 'one' },
    });
    let speaking!: Promise<void>;
    act(() => { speaking = result.current.speak('hello'); });
    rerender({ enabled: change !== 'mute', voice: change === 'voice' ? 'two' : 'one' });
    expect(post.mock.calls[0][2]?.signal?.aborted).toBe(true);
    await act(async () => { request.resolve(response()); await speaking; });
    expect(players[0].play).not.toHaveBeenCalled();
    expect(result.current.state.phase).toBe('idle');
  });

  it('unmount aborts and rejects late playback without allocating a URL', async () => {
    const request = deferred<ReturnType<typeof response>>();
    post.mockReturnValueOnce(request.promise);
    const { result, unmount } = renderHook(() => useTts({ enabled: true }));
    let speaking!: Promise<void>;
    act(() => { speaking = result.current.speak('hello'); });
    unmount();
    await act(async () => { request.resolve(response()); await speaking; });
    expect(post.mock.calls[0][2]?.signal?.aborted).toBe(true);
    expect(create).not.toHaveBeenCalled();
    expect(players[0].onended).toBeNull();
  });

  it('completed playback releases its source and callbacks exactly once', async () => {
    post.mockResolvedValueOnce(response());
    const { result } = renderHook(() => useTts({ enabled: true }));
    await act(() => result.current.speak('hello'));
    const url = players[0].src;
    const ended = players[0].onended;
    act(() => { ended?.(); ended?.(); });
    expect(result.current.state.phase).toBe('idle');
    expect(players[0].src).toBe('');
    expect(revoke.mock.calls.filter(([value]) => value === url)).toHaveLength(1);
  });

  it('play rejection cleans its own URL and remains a visible failure', async () => {
    const request = deferred<ReturnType<typeof response>>();
    post.mockReturnValueOnce(request.promise);
    const { result } = renderHook(() => useTts({ enabled: true }));
    let speaking!: Promise<void>;
    act(() => { speaking = result.current.speak('hello'); });
    players[0].play.mockRejectedValueOnce(new Error('autoplay denied'));
    await act(async () => { request.resolve(response()); await speaking; });
    expect(result.current.state).toEqual({ phase: 'error', message: 'autoplay denied' });
    expect(players[0].src).toBe('');
    expect(revoke).toHaveBeenCalledTimes(1);
  });

  it('disabled, empty and invalid audio do not play', async () => {
    const { result, rerender } = renderHook(({ enabled }) => useTts({ enabled }), { initialProps: { enabled: false } });
    await act(() => result.current.speak('hello'));
    rerender({ enabled: true });
    await act(() => result.current.speak(' '));
    expect(post).not.toHaveBeenCalled();
    post.mockResolvedValueOnce({ data: new Blob([]) });
    await act(() => result.current.speak('hello'));
    expect(result.current.state.phase).toBe('error');
    expect(players[0].play).not.toHaveBeenCalled();
  });
});
