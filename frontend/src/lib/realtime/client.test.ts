import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { RealtimeClient } from './client';
import { apiClient } from '@/api/client';
vi.mock('@/api/client', () => ({ apiClient: { post: vi.fn() } }));
const peers: Peer[] = [];
const contexts: Context[] = [];
const media = vi.fn();
const track = () => ({ enabled: true, stop: vi.fn(), onended: null });
class Context {
  state = 'running'; currentTime = 0;
  resume = vi.fn(async () => {}); close = vi.fn(async () => {});
  constructor() { contexts.push(this); }
}
class Peer extends EventTarget {
  connectionState = 'new'; iceGatheringState = 'complete';
  localDescription = { type: 'offer', sdp: 'local-offer' };
  onconnectionstatechange: (() => void) | null = null;
  channel = { readyState: 'open', bufferedAmount: 0, onmessage: null as ((e: { data: string }) => void) | null, onclose: null as (() => void) | null, send: vi.fn(), close: vi.fn() };
  addTrack = vi.fn(); close = vi.fn();
  createDataChannel = () => this.channel;
  createOffer = async () => this.localDescription;
  setLocalDescription = async () => {};
  setRemoteDescription = async () => { this.channel.onmessage?.({ data: JSON.stringify({ v: 1, generation: 1, seq: 1, type: 'state', question: { id: 1, text: 'q' }, answer_pending: false, request_id: null }) }); };
  constructor() { super(); peers.push(this); }
}
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks(); sessionStorage.clear(); peers.length = contexts.length = 0;
  vi.stubGlobal('AudioContext', Context); vi.stubGlobal('RTCPeerConnection', Peer); vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: media } });
  media.mockReset();
  vi.mocked(apiClient.post).mockImplementation(async (url) => ({ data: url.endsWith('/offer') ? { session_id: '11111111-1111-4111-8111-111111111111', generation: 1, protocol: 'interview-media-v1', type: 'answer', sdp: 'answer' } : { active: true } }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
it('cancels a pending permission without leaving a late microphone running', async () => {
  let resolve!: (stream: unknown) => void;
  media.mockReturnValue(new Promise(done => { resolve = done; }));
  const client = new RealtimeClient('r', vi.fn(), vi.fn());
  const starting = client.connect(); await Promise.resolve(); await Promise.resolve();
  client.disconnect(false); const device = track(); resolve({ getTracks: () => [device], getAudioTracks: () => [device] });
  await starting;
  expect(device.stop).toHaveBeenCalledOnce(); expect(peers[0].close).toHaveBeenCalledOnce(); expect(apiClient.post).not.toHaveBeenCalled();
});
it('reconnect uses a stable identity, fences old events and never commits automatically', async () => {
  const device = track(); media.mockResolvedValue({ getTracks: () => [device], getAudioTracks: () => [device] });
  const update = vi.fn(); const client = new RealtimeClient('r', update, vi.fn());
  await client.connect(); const old = peers[0].channel.onmessage;
  const first = vi.mocked(apiClient.post).mock.calls[0][1] as { client_session_id: string };
  client.disconnect(); await client.connect();
  const second = [...vi.mocked(apiClient.post).mock.calls].reverse().find(([url]) => url.endsWith('/offer'))![1] as { client_session_id: string };
  expect(first.client_session_id).toBe(second.client_session_id);
  const count = update.mock.calls.length;
  old?.({ data: JSON.stringify({ v: 1, generation: 1, seq: 2, type: 'final', draft_id: crypto.randomUUID(), text: 'old' }) });
  expect(update).toHaveBeenCalledTimes(count);
  expect(peers[1].channel.send).not.toHaveBeenCalled(); client.disconnect(false);
});
it('a final transcript is a draft until the user explicitly commits once', async () => {
  const device = track(); media.mockResolvedValue({ getTracks: () => [device], getAudioTracks: () => [device] });
  const client = new RealtimeClient('r', vi.fn(), vi.fn()); await client.connect();
  const draft = crypto.randomUUID();
  peers[0].channel.onmessage?.({ data: JSON.stringify({ v: 1, generation: 1, seq: 2, type: 'final', draft_id: draft, text: 'final' }) });
  expect(device.enabled).toBe(false); expect(peers[0].channel.send).not.toHaveBeenCalled();
  client.commit(); client.commit();
  expect(peers[0].channel.send).toHaveBeenCalledOnce();
  expect(JSON.parse(peers[0].channel.send.mock.calls[0][0])).toMatchObject({ type: 'commit', draft_id: draft });
  expect(sessionStorage.getItem('mock-answer-intent:r')).not.toContain('final'); client.disconnect(false);
});
it('authority is renewed over authenticated HTTP; failure releases the peer and tracks', async () => {
  const device = track(); media.mockResolvedValue({ getTracks: () => [device], getAudioTracks: () => [device] });
  const view = vi.fn(); const client = new RealtimeClient('r', view, vi.fn()); await client.connect();
  vi.mocked(apiClient.post).mockRejectedValueOnce(new Error('401'));
  await vi.advanceTimersByTimeAsync(10000);
  expect(view).toHaveBeenLastCalledWith(expect.objectContaining({ phase: 'error' }));
  expect(device.stop).toHaveBeenCalledOnce(); expect(contexts[0].close).toHaveBeenCalledOnce();
  expect(peers[0].channel.send).not.toHaveBeenCalled();
});
