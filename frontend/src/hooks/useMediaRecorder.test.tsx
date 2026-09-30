import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MAX_RECORDING_BYTES, MAX_RECORDING_MS, useMediaRecorder } from './useMediaRecorder';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const recorders: Recorder[] = [];
class Recorder {
  static isTypeSupported = () => true;
  mimeType = 'audio/webm';
  state = 'inactive';
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  start = vi.fn(() => { this.state = 'recording'; });
  stop = vi.fn(() => { this.state = 'inactive'; });
  constructor() { recorders.push(this); }
}
const getUserMedia = vi.fn();
const stream = () => {
  const track = { stop: vi.fn() };
  return { track, value: { getTracks: () => [track] } as unknown as MediaStream };
};
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks(); getUserMedia.mockReset(); recorders.length = 0;
  vi.stubGlobal('MediaRecorder', Recorder);
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it('unmount fences a late microphone grant and releases its tracks', async () => {
  const request = deferred<MediaStream>(); const media = stream(); getUserMedia.mockReturnValue(request.promise);
  const { result, unmount } = renderHook(useMediaRecorder);
  let starting!: Promise<void>; act(() => { starting = result.current.start(); });
  unmount(); await act(async () => { request.resolve(media.value); await starting; });
  expect(media.track.stop).toHaveBeenCalledTimes(1); expect(recorders).toHaveLength(0);
});
it('stop cancels pending permission; its late grant cannot replace a newer recording', async () => {
  const request = deferred<MediaStream>(); const old = stream(); const latest = stream();
  getUserMedia.mockReturnValueOnce(request.promise).mockResolvedValueOnce(latest.value);
  const { result } = renderHook(useMediaRecorder);
  let starting!: Promise<void>; act(() => { starting = result.current.start(); });
  await act(() => result.current.stop()); await act(() => result.current.start());
  await act(async () => { request.resolve(old.value); await starting; });
  expect(old.track.stop).toHaveBeenCalledTimes(1); expect(latest.track.stop).not.toHaveBeenCalled();
  expect(recorders).toHaveLength(1); expect(result.current.state).toBe('recording');
});
it('rapid start calls open one microphone request', async () => {
  const request = deferred<MediaStream>(); getUserMedia.mockReturnValue(request.promise);
  const { result } = renderHook(useMediaRecorder);
  let first!: Promise<void>; act(() => { first = result.current.start(); void result.current.start(); });
  expect(getUserMedia).toHaveBeenCalledTimes(1);
  await act(async () => { request.resolve(stream().value); await first; });
  expect(recorders[0].start).toHaveBeenCalledWith(1000);
});
it('duplicate stop calls resolve the same final chunk and release resources once', async () => {
  const media = stream(); getUserMedia.mockResolvedValue(media.value);
  const { result } = renderHook(useMediaRecorder); await act(() => result.current.start());
  let first!: Promise<Blob | null>; let second!: Promise<Blob | null>;
  act(() => { first = result.current.stop(); second = result.current.stop(); });
  expect(first).toBe(second); expect(recorders[0].stop).toHaveBeenCalledTimes(1);
  let final: Blob | null = null;
  await act(async () => {
    recorders[0].ondataavailable?.({ data: new Blob(['tail']) }); recorders[0].onstop?.();
    final = await first; expect(await second).toBe(final);
  });
  expect(final).toMatchObject({ size: 4, type: 'audio/webm' });
  expect(media.track.stop).toHaveBeenCalledTimes(1); expect(result.current.state).toBe('idle');
});
it('missing onstop has a bounded failure, not an unresolved promise', async () => {
  const media = stream(); getUserMedia.mockResolvedValue(media.value);
  const { result } = renderHook(useMediaRecorder); await act(() => result.current.start());
  let stopping!: Promise<Blob | null>; act(() => { stopping = result.current.stop(); });
  await act(async () => { vi.advanceTimersByTime(5000); expect(await stopping).toBeNull(); });
  expect(result.current.errorMessage).toContain('结束超时'); expect(media.track.stop).toHaveBeenCalledTimes(1);
});
it.each(['bytes', 'duration'] as const)('%s limit rejects partial recording and stops capture', async (limit) => {
  const media = stream(); getUserMedia.mockResolvedValue(media.value);
  const { result } = renderHook(useMediaRecorder); await act(() => result.current.start());
  act(() => {
    if (limit === 'duration') vi.advanceTimersByTime(MAX_RECORDING_MS);
    else recorders[0].ondataavailable?.({ data: { size: MAX_RECORDING_BYTES + 1 } as Blob });
  });
  expect(result.current.state).toBe('error'); expect(media.track.stop).toHaveBeenCalledTimes(1);
  await expect(result.current.stop()).resolves.toBeNull();
});
it('permission timeout releases a subsequent grant without creating a recorder', async () => {
  const request = deferred<MediaStream>(); const media = stream(); getUserMedia.mockReturnValue(request.promise);
  const { result } = renderHook(useMediaRecorder);
  let starting!: Promise<void>; act(() => { starting = result.current.start(); vi.advanceTimersByTime(60_000); });
  expect(result.current.errorMessage).toContain('授权超时');
  await act(async () => { request.resolve(media.value); await starting; });
  expect(media.track.stop).toHaveBeenCalledTimes(1); expect(recorders).toHaveLength(0);
});
it('unmount while stopping resolves waiters and drops late recorder events', async () => {
  const media = stream(); getUserMedia.mockResolvedValue(media.value);
  const { result, unmount } = renderHook(useMediaRecorder); await act(() => result.current.start());
  let stopping!: Promise<Blob | null>; act(() => { stopping = result.current.stop(); });
  const lateData = recorders[0].ondataavailable; const lateStop = recorders[0].onstop;
  unmount(); await expect(stopping).resolves.toBeNull();
  act(() => { lateData?.({ data: new Blob(['late']) }); lateStop?.(); });
  expect(media.track.stop).toHaveBeenCalledTimes(1);
});
it('device errors stop capture and remain visible without an automatic restart', async () => {
  const media = stream(); getUserMedia.mockResolvedValue(media.value);
  const { result } = renderHook(useMediaRecorder); await act(() => result.current.start());
  act(() => recorders[0].onerror?.());
  expect(result.current.state).toBe('error'); expect(result.current.errorMessage).toContain('设备');
  expect(media.track.stop).toHaveBeenCalledTimes(1); expect(getUserMedia).toHaveBeenCalledTimes(1);
});
