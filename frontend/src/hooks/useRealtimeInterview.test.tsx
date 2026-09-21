import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { apiClient } from '@/api/client';
import { readAnswerIntent } from '@/api/answerIntent';
import { useRealtimeInterview } from './useRealtimeInterview';
vi.mock('@/api/client', () => ({ apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
const id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
const requestId = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
const peers: Peer[] = [];
const sources: Source[] = [];
class Channel {
  readyState = 'open'; onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null; onerror: (() => void) | null = null;
  send = vi.fn(); close = vi.fn(() => { this.readyState = 'closed'; });
}
class Peer extends EventTarget {
  channel = new Channel(); iceGatheringState = 'complete'; localDescription = { type: 'offer', sdp: 'offer-sdp' };
  onconnectionstatechange = null; connectionState = 'connected';
  createDataChannel = () => this.channel; addTransceiver = vi.fn();
  createOffer = vi.fn(async () => this.localDescription);
  setLocalDescription = vi.fn(async () => undefined); setRemoteDescription = vi.fn(async () => undefined); close = vi.fn();
  constructor() { super(); peers.push(this); }
}
class Source {
  onended: (() => void) | null = null; buffer = null;
  connect = vi.fn(); start = vi.fn(); stop = vi.fn();
}
class Audio {
  currentTime = 0; destination = {}; state = 'running';
  resume = vi.fn(async () => undefined); close = vi.fn(async () => undefined);
  createBuffer = (_channels: number, length: number) => ({ getChannelData: () => new Float32Array(length) });
  createBufferSource = () => { const source = new Source(); sources.push(source); return source; };
}
const getUserMedia = vi.fn();
const track = { stop: vi.fn() };
const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
let sequence = 0;
function event(type: string, fields = {}) { peers.at(-1)!.channel.onmessage?.({ data: JSON.stringify({ type, connection_id: id, seq: ++sequence, ...fields }) }); }
const callbacks = () => ({ onCommit: vi.fn(), onResult: vi.fn(), onState: vi.fn(), onUnconfirmed: vi.fn() });
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear(); peers.length = sources.length = 0; sequence = 0;
  vi.stubGlobal('RTCPeerConnection', Peer); vi.stubGlobal('AudioContext', Audio);
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
  getUserMedia.mockReset().mockResolvedValue(stream);
  vi.mocked(apiClient.get).mockImplementation(async (path) => ({ data: path.includes('capabilities') ? { enabled: true, max_turn_seconds: 180 } : { messages: [] } }));
  vi.mocked(apiClient.post).mockImplementation(async (_path, body) => ({ data: { connection_id: id, client_session_id: (body as { client_session_id: string }).client_session_id, type: 'answer', sdp: 'answer-sdp' } }));
  vi.mocked(apiClient.delete).mockResolvedValue({ data: null });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
async function setup(auto = false) {
  const handlers = callbacks();
  const hook = renderHook(() => useRealtimeInterview('record', handlers));
  await waitFor(() => expect(hook.result.current.enabled).toBe(true));
  await act(() => hook.result.current.connect(auto));
  await act(async () => event('state', { phase: 'listening' }));
  return { ...hook, handlers };
}
it('negotiates once; canonical state is read without submitting a model answer', async () => {
  const { result, handlers } = await setup();
  expect(result.current.phase).toBe('listening'); expect(apiClient.post).toHaveBeenCalledTimes(1);
  expect(handlers.onState).toHaveBeenCalledWith([]); expect(handlers.onCommit).not.toHaveBeenCalled();
  expect(peers[0].addTransceiver).toHaveBeenCalledWith(track, { direction: 'sendonly' });
});
it('partial text remains provisional; final requires an explicit commit with a persisted identity', async () => {
  const { result, handlers } = await setup();
  act(() => event('transcript.partial', { text: 'draft' }));
  expect(result.current.partial).toBe('draft'); expect(handlers.onCommit).not.toHaveBeenCalled();
  act(() => event('transcript.final', { request_id: requestId, question_message_id: 10, text: 'complete' }));
  expect(result.current.phase).toBe('awaiting_commit'); expect(handlers.onCommit).not.toHaveBeenCalled();
  act(() => { result.current.control('commit'); result.current.control('commit'); });
  expect(readAnswerIntent('record')?.requestId).toBe(requestId);
  expect(handlers.onCommit).toHaveBeenCalledTimes(1);
  expect(peers[0].channel.send.mock.calls.filter(([raw]) => JSON.parse(raw).action === 'commit')).toHaveLength(1);
});
it('automatic send is opt-in and an unknown result retains the receipt identity', async () => {
  const { result, handlers } = await setup(true);
  act(() => event('transcript.final', { request_id: requestId, question_message_id: 10, text: 'complete' }));
  expect(handlers.onCommit).toHaveBeenCalledTimes(1);
  act(() => event('answer.unconfirmed', { request_id: requestId }));
  expect(result.current.phase).toBe('disconnected'); expect(handlers.onUnconfirmed).toHaveBeenCalledTimes(1);
  expect(readAnswerIntent('record')?.requestId).toBe(requestId); expect(apiClient.post).toHaveBeenCalledTimes(1);
});
it('a completed response clears its identity, without replaying on reconnect', async () => {
  const { result, handlers } = await setup(true);
  act(() => event('transcript.final', { request_id: requestId, question_message_id: 10, text: 'complete' }));
  const message = { id: 12, speaker: 'interviewer', text: 'next' };
  act(() => event('answer.completed', { request_id: requestId, message, end_suggested: false }));
  expect(result.current.phase).toBe('listening'); expect(handlers.onResult).toHaveBeenCalledWith(message, false);
  expect(readAnswerIntent('record')).toBeNull();
  act(() => result.current.disconnect()); expect(handlers.onUnconfirmed).not.toHaveBeenCalled();
});
it('late microphone grant after disconnect is stopped, not negotiated', async () => {
  let resolve!: (value: unknown) => void;
  getUserMedia.mockReturnValue(new Promise((done) => { resolve = done; }));
  const hook = renderHook(() => useRealtimeInterview('record', callbacks()));
  await waitFor(() => expect(hook.result.current.enabled).toBe(true));
  let starting!: Promise<void>; await act(async () => { starting = hook.result.current.connect(false); });
  act(() => hook.result.current.disconnect());
  await act(async () => { resolve(stream); await starting; });
  expect(track.stop).toHaveBeenCalledTimes(1); expect(apiClient.post).not.toHaveBeenCalled();
});
it('foreign and duplicate events cannot overwrite the current provisional text', async () => {
  const { result } = await setup();
  act(() => event('transcript.partial', { text: 'current' }));
  act(() => event('transcript.partial', { text: 'old', seq: 1 }));
  act(() => event('transcript.partial', { text: 'foreign', connection_id: requestId }));
  expect(result.current.partial).toBe('current');
});
it('interrupt drops queued audio and a late ended callback cannot acknowledge it', async () => {
  const { result } = await setup();
  act(() => {
    event('audio.start', { playback_id: requestId, offset: 0, samples: 2, sample_rate: 24000 });
    event('audio.data', { playback_id: requestId, data: btoa('\0\0\0\0') });
    event('audio.end', { playback_id: requestId, samples: 2 });
  });
  expect(sources).toHaveLength(1); const ended = sources[0].onended;
  act(() => { result.current.control('interrupt'); ended?.(); });
  expect(sources[0].stop).toHaveBeenCalledTimes(1);
  expect(peers[0].channel.send.mock.calls.some(([raw]) => JSON.parse(raw).action === 'ack')).toBe(false);
});
it('malformed audio capacity closes the connection instead of buffering indefinitely', async () => {
  const { result } = await setup();
  act(() => event('audio.start', { playback_id: requestId, offset: 0, samples: 1_440_001, sample_rate: 24000 }));
  expect(result.current.phase).toBe('disconnected'); expect(track.stop).toHaveBeenCalledTimes(1);
});
