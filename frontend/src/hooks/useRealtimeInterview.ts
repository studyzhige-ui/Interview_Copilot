import { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from '@/api/client';
import { rememberAnswerIntent, clearAnswerIntent, readAnswerIntent } from '@/api/answerIntent';
import type { MockLiveMessage } from '@/types/api';
import type { components } from '@/types/generated/realtime';

type Control = components['schemas']['MediaControl'];
type Answer = components['schemas']['MediaAnswer'];
export interface LiveDraft { request_id: string; question_message_id: number; text: string }
interface Callbacks {
  onCommit: (draft: LiveDraft) => void;
  onResult: (message: MockLiveMessage, endSuggested: boolean) => void;
  onState: (messages: MockLiveMessage[]) => void;
  onUnconfirmed: () => void;
}
interface Playback { source: AudioBufferSourceNode; offset: number; samples: number; started: number; id: string }
interface Connection {
  pc: RTCPeerConnection; channel: RTCDataChannel; abort: AbortController;
  stream?: MediaStream; audio: AudioContext; id?: string; clientId: string; seq: number;
  heartbeat?: ReturnType<typeof setInterval>; deadline?: ReturnType<typeof setTimeout>;
  playback?: Playback; chunk?: { id: string; offset: number; samples: number; bytes: number; parts: Uint8Array[] };
  draft?: LiveDraft; submitted?: string; autoCommit: boolean;
}
const uuid = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f-]{36}$/.test(value);
const positive = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0;
function clientIdentity(recordId: string) {
  const key = `mock-media-client:${recordId}`;
  try {
    const previous = sessionStorage.getItem(key);
    if (uuid(previous)) return previous;
    const value = crypto.randomUUID(); sessionStorage.setItem(key, value); return value;
  } catch { return crypto.randomUUID(); }
}
export function waitForIce(pc: RTCPeerConnection, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const finish = (error?: Error) => {
      clearTimeout(timer); pc.removeEventListener('icegatheringstatechange', changed);
      signal.removeEventListener('abort', cancelled); if (error) reject(error); else resolve();
    };
    const changed = () => { if (pc.iceGatheringState === 'complete') finish(); };
    const cancelled = () => finish(new Error('连接已取消'));
    const timer = setTimeout(() => finish(new Error('本地媒体连接超时')), 10_000);
    pc.addEventListener('icegatheringstatechange', changed); signal.addEventListener('abort', cancelled);
    if (signal.aborted) cancelled(); else changed();
  });
}

export function useRealtimeInterview(recordId: string, callbacks: Callbacks) {
  const handlers = useRef(callbacks);
  useEffect(() => { handlers.current = callbacks; }, [callbacks]);
  const active = useRef<Connection | null>(null);
  const mounted = useRef(true);
  const [phase, setPhase] = useState('disconnected');
  const [error, setError] = useState<string | null>(null);
  const [partial, setPartial] = useState('');
  const [draft, setDraft] = useState<LiveDraft | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [maxSeconds, setMaxSeconds] = useState(180);
  const send = (resource: Connection, command: Omit<Control, 'connection_id'>) => {
    if (!resource.id || resource.channel.readyState !== 'open') return false;
    resource.channel.send(JSON.stringify({ ...command, connection_id: resource.id })); return true;
  };
  const stopPlayback = (resource: Connection) => {
    const playing = resource.playback;
    if (playing) { playing.source.onended = null; try { playing.source.stop(); } catch { /* ended */ } }
    resource.playback = undefined; resource.chunk = undefined;
  };
  const dispose = useCallback((resource: Connection) => {
    resource.abort.abort(); clearInterval(resource.heartbeat); clearTimeout(resource.deadline);
    resource.stream?.getTracks().forEach((track) => track.stop());
    if (resource.playback) { resource.playback.source.onended = null; try { resource.playback.source.stop(); } catch { /* ended */ } }
    resource.pc.onconnectionstatechange = null; resource.channel.onmessage = null;
    resource.channel.onclose = null; resource.channel.onerror = null;
    resource.channel.close(); resource.pc.close(); void resource.audio.close().catch(() => undefined);
    if (resource.id) void apiClient.delete(`/mock-interviews/${encodeURIComponent(recordId)}/media/${resource.clientId}/${resource.id}`).catch(() => undefined);
  }, [recordId]);
  const disconnect = useCallback(() => {
    const resource = active.current; active.current = null;
    if (resource) dispose(resource);
    if (mounted.current) {
      setPhase('disconnected'); setPartial(''); setDraft(null);
      if (resource?.submitted) handlers.current.onUnconfirmed();
    }
  }, [dispose]);
  useEffect(() => {
    mounted.current = true;
    const abort = new AbortController();
    void apiClient.get('/mock-interviews/media-capabilities', { signal: abort.signal }).then(({ data }) => {
      if (!abort.signal.aborted) {
        setEnabled(data.enabled === true);
        if (positive(data.max_turn_seconds)) setMaxSeconds(data.max_turn_seconds);
      }
    }).catch(() => undefined);
    return () => { mounted.current = false; abort.abort(); const resource = active.current; active.current = null; if (resource) dispose(resource); };
  }, [dispose]);

  const commit = (resource: Connection) => {
    if (!resource.draft || resource.submitted) return;
    const value = resource.draft;
    // Persist identity before crossing the mutation boundary, never the text.
    rememberAnswerIntent(recordId, value.request_id, value.question_message_id);
    if (readAnswerIntent(recordId)?.requestId !== value.request_id) throw new Error('无法保存恢复编号，请改用文字回答');
    resource.submitted = value.request_id;
    handlers.current.onCommit(value);
    if (!send(resource, { action: 'commit', request_id: value.request_id })) throw new Error('连接中断，请核对回答收据');
    setPhase('answering'); setDraft(null);
  };

  const connect = async (autoCommit: boolean) => {
    if (active.current || !enabled) return;
    setError(null); setPartial(''); setDraft(null); setPhase('connecting');
    let resource: Connection | undefined;
    let createdAudio: AudioContext | undefined;
    let createdPeer: RTCPeerConnection | undefined;
    try {
      createdAudio = new AudioContext();
      const pc = new RTCPeerConnection({ iceServers: [] }); createdPeer = pc;
      const channel = pc.createDataChannel('copilot-media-v1', { ordered: true });
      resource = { pc, channel, abort: new AbortController(), audio: createdAudio, clientId: clientIdentity(recordId), seq: 0, autoCommit };
      const owned = resource;
      active.current = owned;
      const current = () => mounted.current && active.current === owned && !owned.abort.signal.aborted;
      const fail = (message: string) => { if (current()) { setError(message); disconnect(); } };
      owned.deadline = setTimeout(() => fail('麦克风授权或连接超时，请重试。'), 30_000);
      await owned.audio.resume();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false });
      if (!current()) { stream.getTracks().forEach((track) => track.stop()); return; }
      owned.stream = stream;
      for (const track of stream.getAudioTracks()) pc.addTransceiver(track, { direction: 'sendonly' });
      channel.onclose = () => fail('实时连接已断开；重连不会重复提交回答。');
      channel.onerror = () => fail('实时媒体传输失败，请核对已提交的回答。');
      pc.onconnectionstatechange = () => { if (pc.connectionState === 'failed') fail('本地 WebRTC 连接失败，请使用文字或录音回答。'); };
      channel.onmessage = (event) => {
        if (!current()) return;
        try {
          if (typeof event.data !== 'string' || event.data.length > 64000) throw new Error();
          const value = JSON.parse(event.data);
          if (value.connection_id !== owned.id || !positive(value.seq) || value.seq <= owned.seq) return;
          owned.seq = value.seq;
          if (value.type === 'state') {
            clearTimeout(owned.deadline); setPhase(value.phase === 'blocked' ? 'blocked' : 'listening');
            clearInterval(owned.heartbeat);
            owned.heartbeat = setInterval(() => {
              send(owned, { action: 'ping' });
              const p = owned.playback;
              if (p && owned.audio.state === 'running') {
                const played = Math.min(p.samples, Math.max(0, Math.floor((owned.audio.currentTime - p.started) * 24000)));
                send(owned, { action: 'ack', playback_id: p.id, samples: p.offset + played });
              }
            }, 1000);
            void apiClient.get(`/mock-interviews/${encodeURIComponent(recordId)}/live-state`, { signal: owned.abort.signal }).then(({ data }) => {
              if (current()) handlers.current.onState(data.messages);
            }).catch(() => fail('无法同步面试现场，请重新连接。'));
          } else if (value.type === 'phase') {
            if (typeof value.phase !== 'string') throw new Error(); setPhase(value.phase);
          } else if (value.type === 'speech.start') {
            stopPlayback(owned); setPartial('');
          } else if (value.type === 'transcript.partial') {
            if (typeof value.text !== 'string' || value.text.length > 16000) throw new Error(); setPartial(value.text);
          } else if (value.type === 'transcript.final') {
            if (!uuid(value.request_id) || !positive(value.question_message_id) || typeof value.text !== 'string' || !value.text.trim() || value.text.length > 16000) throw new Error();
            owned.draft = { request_id: value.request_id, question_message_id: value.question_message_id, text: value.text };
            setDraft(owned.draft); setPhase('awaiting_commit'); setPartial('');
            if (owned.autoCommit) commit(owned);
          } else if (value.type === 'answer.completed') {
            if (value.request_id !== owned.submitted || !positive(value.message?.id) || value.message.speaker !== 'interviewer' || typeof value.message.text !== 'string' || value.message.text.length > 16000) throw new Error();
            clearAnswerIntent(recordId, owned.submitted); owned.submitted = undefined; owned.draft = undefined;
            setPhase('listening'); handlers.current.onResult(value.message, value.end_suggested === true);
          } else if (value.type === 'answer.unconfirmed') {
            fail('回答执行结果尚未确认；请核对收据，不要自动重发。');
          } else if (value.type === 'audio.cancel') {
            stopPlayback(owned);
          } else if (value.type === 'audio.start') {
            if (!uuid(value.playback_id) || value.sample_rate !== 24000 || !positive(value.samples) || value.samples > 1_440_000 || !Number.isSafeInteger(value.offset) || value.offset < 0 || owned.playback || owned.chunk) throw new Error();
            owned.chunk = { id: value.playback_id, offset: value.offset, samples: value.samples, bytes: 0, parts: [] };
          } else if (value.type === 'audio.data') {
            const chunk = owned.chunk;
            if (!chunk || value.playback_id !== chunk.id || typeof value.data !== 'string' || value.data.length > 16000) throw new Error();
            const binary = atob(value.data); chunk.bytes += binary.length;
            if (chunk.bytes > chunk.samples * 2) throw new Error();
            chunk.parts.push(Uint8Array.from(binary, (c) => c.charCodeAt(0)));
          } else if (value.type === 'audio.end') {
            const chunk = owned.chunk;
            if (!chunk || value.playback_id !== chunk.id || chunk.bytes !== chunk.samples * 2 || value.samples !== chunk.offset + chunk.samples) throw new Error();
            const pcm = new Uint8Array(chunk.bytes); let offset = 0;
            for (const part of chunk.parts) { pcm.set(part, offset); offset += part.length; }
            const data = new DataView(pcm.buffer); const buffer = owned.audio.createBuffer(1, chunk.samples, 24000); const floats = buffer.getChannelData(0);
            for (let i = 0; i < chunk.samples; i++) floats[i] = data.getInt16(i * 2, true) / 32768;
            const source = owned.audio.createBufferSource(); source.buffer = buffer; source.connect(owned.audio.destination);
            const playback = { source, offset: chunk.offset, samples: chunk.samples, started: owned.audio.currentTime, id: chunk.id };
            owned.playback = playback; owned.chunk = undefined;
            source.onended = () => {
              if (current() && owned.playback === playback) { owned.playback = undefined; send(owned, { action: 'ack', playback_id: playback.id, samples: playback.offset + playback.samples }); }
            };
            source.start();
          } else if (value.type === 'error') {
            setPhase('blocked'); setError('实时处理暂停：请丢弃当前语音后重录，或断开后改用文字。'); stopPlayback(owned);
          } else if (value.type === 'notice') {
            setError('本地语音服务暂不可用，文字与已保存的回答不受影响。');
          }
        } catch { fail('实时消息不完整或超出限制，已停止连接。'); }
      };
      await pc.setLocalDescription(await pc.createOffer());
      await waitForIce(pc, owned.abort.signal);
      if (!current()) return;
      const { data } = await apiClient.post<Answer>(`/mock-interviews/${encodeURIComponent(recordId)}/media/offer`, { client_session_id: owned.clientId, type: 'offer', sdp: pc.localDescription?.sdp }, { signal: owned.abort.signal });
      if (!current()) return;
      if (!uuid(data.connection_id) || data.client_session_id !== owned.clientId || typeof data.sdp !== 'string' || data.sdp.length > 65536 || data.type !== 'answer') throw new Error('服务返回的连接信息无效');
      owned.id = data.connection_id;
      await pc.setRemoteDescription({ type: 'answer', sdp: data.sdp });
    } catch (failure) {
      if (!resource) { createdPeer?.close(); void createdAudio?.close().catch(() => undefined); }
      if (!resource || active.current === resource) { setError(failure instanceof Error ? failure.message : '本地实时语音连接失败'); disconnect(); }
    }
  };
  const control = (action: Control['action']) => {
    const resource = active.current; if (!resource) return;
    if (action === 'commit') { try { commit(resource); } catch { disconnect(); } return; }
    if (action === 'interrupt') stopPlayback(resource);
    if (action === 'discard') { resource.draft = undefined; setDraft(null); setPartial(''); }
    send(resource, { action });
  };
  return { phase, enabled, maxSeconds, error, partial, draft, connect, disconnect, control };
}
