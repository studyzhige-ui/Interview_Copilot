import { apiClient } from '@/api/client';
import { rememberAnswerIntent, clearAnswerIntent } from '@/api/answerIntent';
import type { components } from '@/types/generated/shared-protocols';
import { RealtimePlayback } from './playback';

type Offer = components['schemas']['MediaOfferRequestContract'];
type Answer = components['schemas']['MediaAnswerResponseContract'];
type Command = components['schemas']['MediaCommandRequestContract'];
type WireEvent = components['schemas']['MediaEventResponseContract'];
export interface RealtimeView {
  phase: 'offline' | 'connecting' | 'listening' | 'final' | 'submitting' | 'recovering' | 'error';
  text: string; notice: string; draftId?: string;
}
export const INITIAL_MEDIA_VIEW: RealtimeView = { phase: 'offline', text: '', notice: '' };
interface Lifetime {
  controller: AbortController; peer: RTCPeerConnection; channel: RTCDataChannel;
  context: AudioContext; playback: RealtimePlayback; stream?: MediaStream;
  lease?: Answer; heartbeat?: ReturnType<typeof setInterval>; progress?: ReturnType<typeof setInterval>;
  deadline?: ReturnType<typeof setTimeout>; seq: number; questionId?: number; renewing: boolean;
}
const path = (record: string) => `/mock-interviews/${encodeURIComponent(record)}/media`;
function clientIdentity(record: string) {
  const key = `mock-media-client:${record}`;
  try {
    const saved = sessionStorage.getItem(key);
    if (saved && /^[0-9a-f-]{36}$/.test(saved)) return saved;
    const value = crypto.randomUUID(); sessionStorage.setItem(key, value); return value;
  } catch { return crypto.randomUUID(); }
}
function bounded<T>(promise: Promise<T>, signal: AbortSignal, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const finish = () => { clearTimeout(timer); signal.removeEventListener('abort', cancel); };
    const cancel = () => { finish(); reject(new Error('media_cancelled')); };
    const timer = setTimeout(() => { finish(); reject(new Error('media_deadline')); }, ms);
    signal.addEventListener('abort', cancel, { once: true });
    promise.then(value => { finish(); resolve(value); }, error => { finish(); reject(error); });
    if (signal.aborted) cancel();
  });
}
function iceComplete(peer: RTCPeerConnection, signal: AbortSignal) {
  return bounded(new Promise<void>(resolve => {
    if (peer.iceGatheringState === 'complete') { resolve(); return; }
    const change = () => { if (peer.iceGatheringState === 'complete') { peer.removeEventListener('icegatheringstatechange', change); resolve(); } };
    peer.addEventListener('icegatheringstatechange', change);
    signal.addEventListener('abort', () => peer.removeEventListener('icegatheringstatechange', change), { once: true });
  }), signal, 15000);
}

export class RealtimeClient {
  private life: Lifetime | null = null;
  private view = INITIAL_MEDIA_VIEW;
  private identity: string;
  constructor(private recordId: string, private changed: (view: RealtimeView) => void, private synchronize: () => void) { this.identity = clientIdentity(recordId); }
  private update(value: Partial<RealtimeView>) { this.view = { ...this.view, ...value }; this.changed(this.view); }
  setSynchronize(callback: () => void) { this.synchronize = callback; }
  get active() { return this.life !== null; }
  private send(life: Lifetime, command: Command) {
    if (this.life !== life || life.channel.readyState !== 'open') throw new Error('media_not_connected');
    if (life.channel.bufferedAmount > 65536) throw new Error('media_control_backpressure');
    life.channel.send(JSON.stringify(command));
  }
  command(command: Command) {
    const life = this.life;
    if (!life) return;
    try { this.send(life, command); } catch { this.fail(life, '连接已中断，请重新连接核对现场。'); }
  }
  async connect(autoSubmit = false) {
    if (this.life) return;
    this.update({ phase: 'connecting', notice: '', text: '', draftId: undefined });
    let life: Lifetime | null = null;
    try {
      const context = new AudioContext();
      const peer = new RTCPeerConnection({ iceServers: [] });
      const channel = peer.createDataChannel('interview-media-v1', { ordered: true });
      const controller = new AbortController();
      life = { context, peer, channel, controller, seq: 0, renewing: false, playback: null as unknown as RealtimePlayback };
      const current = life;
      life.playback = new RealtimePlayback(context, (audio_id, played_samples, complete) => this.send(current, { type: 'playback', audio_id, played_samples, complete }));
      this.life = life;
      life.deadline = setTimeout(() => this.fail(current, '实时连接超时；没有提交回答。'), 60000);
      await bounded(context.resume(), controller.signal, 5000);
      if (this.life !== current) return;
      // A browser permission promise cannot be cancelled; release a late grant.
      const permission = navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
      void permission.then(stream => { if (this.life !== current) stream.getTracks().forEach(track => track.stop()); }, () => {});
      const stream = await bounded(permission, controller.signal, 45000);
      if (this.life !== life) { stream.getTracks().forEach(track => track.stop()); return; }
      life.stream = stream;
      for (const track of stream.getAudioTracks()) { track.enabled = false; peer.addTrack(track, stream); track.onended = () => this.fail(current, '麦克风已断开。'); }
      channel.onmessage = event => { if (this.life === current) { try { this.receive(current, event.data); } catch { this.fail(current, '收到无效媒体数据，已停止连接。'); } } };
      channel.onclose = () => this.fail(current, '实时连接已关闭，重新连接只同步已有回答。');
      peer.onconnectionstatechange = () => { if (['failed', 'disconnected', 'closed'].includes(peer.connectionState)) this.fail(current, '网络中断，未自动重发回答。'); };
      await peer.setLocalDescription(await peer.createOffer());
      await iceComplete(peer, controller.signal);
      const payload: Offer = { client_session_id: this.identity, type: 'offer', sdp: peer.localDescription!.sdp, auto_submit: autoSubmit };
      const response = await apiClient.post<Answer>(path(this.recordId) + '/offer', payload, { signal: controller.signal, timeout: 25000 });
      if (this.life !== life) {
        void apiClient.post(`${path(this.recordId)}/${response.data.session_id}/close`, { generation: response.data.generation }).catch(() => {}); return;
      }
      life.lease = response.data;
      if (life.lease.protocol !== 'interview-media-v1' || !Number.isSafeInteger(life.lease.generation)) throw new Error('invalid_media_answer');
      await peer.setRemoteDescription({ type: 'answer', sdp: life.lease.sdp });
      life.heartbeat = setInterval(() => { void this.renew(current); }, 10000);
      life.progress = setInterval(() => { if (this.life === current) { try { current.playback.progress(); } catch { this.fail(current, '音频播放确认失败，已停止实时连接。'); } } }, 500);
    } catch {
      if (life) this.fail(life, '无法连接实时语音：请检查授权、本地模型及允许的网络地址；仍可使用录音或文字。');
      else this.update({ phase: 'error', notice: '当前浏览器无法创建实时音频连接。' });
    }
  }
  private receive(life: Lifetime, raw: unknown) {
    if (typeof raw !== 'string' || raw.length > 65536) throw new Error('media_event_capacity');
    const event = JSON.parse(raw) as WireEvent;
    if (event.v !== 1 || event.generation !== life.lease?.generation || !Number.isSafeInteger(event.seq) || event.seq <= life.seq) throw new Error('stale_media_event');
    life.seq = event.seq;
    switch (event.type) {
      case 'state': {
        const question = event.question;
        if (question && Number.isSafeInteger(question.id) && typeof question.id === 'number') life.questionId = question.id;
        const first = this.view.phase === 'connecting';
        if (event.answer_pending && event.request_id && life.questionId) rememberAnswerIntent(this.recordId, event.request_id, life.questionId);
        if (event.answer_pending) {
          this.update({ phase: 'recovering', notice: '已有回答等待核对。请断开实时语音后使用“重新连接”同步收据；不会自动再生成。' });
          life.stream?.getTracks().forEach(t => { t.enabled = false; });
        } else if (first || this.view.phase === 'recovering') {
          this.update({ phase: 'listening', notice: '已连接。停顿后形成草稿；默认需要确认才提交。' });
          life.stream?.getTracks().forEach(t => { t.enabled = true; });
        }
        clearTimeout(life.deadline);
        if (first) this.synchronize();
        break;
      }
      case 'partial': if (typeof event.text !== 'string' || event.text.length > 16000) throw new Error('invalid_transcript'); this.update({ text: event.text }); break;
      case 'final':
        if (typeof event.text !== 'string' || event.text.length > 16000 || !event.draft_id) throw new Error('invalid_draft');
        this.update({ phase: 'final', text: event.text, draftId: event.draft_id });
        life.stream?.getTracks().forEach(t => { t.enabled = false; }); break;
      case 'submitting':
        if (!event.request_id || !life.questionId) throw new Error('invalid_answer_intent');
        rememberAnswerIntent(this.recordId, event.request_id, life.questionId);
        this.update({ phase: 'submitting', notice: '正在生成下一题；断开连接不会撤销已经保存的回答。' }); break;
      case 'answer':
        if (event.request_id) clearAnswerIntent(this.recordId, event.request_id);
        if (event.message && typeof event.message.id === 'number') life.questionId = event.message.id;
        this.update({ phase: 'listening', text: '', draftId: undefined, notice: '下一题已保存。说话可打断朗读。' });
        life.stream?.getTracks().forEach(t => { t.enabled = true; }); this.synchronize(); break;
      case 'cleared': this.update({ phase: 'listening', text: '', draftId: undefined }); life.stream?.getTracks().forEach(t => { t.enabled = true; }); break;
      case 'audio_start':
        if (typeof event.audio_id !== 'string' || typeof event.samples !== 'number' || typeof event.rate !== 'number') throw new Error('invalid_audio');
        life.playback.begin({ audio_id: event.audio_id, rate: event.rate, samples: event.samples }); break;
      case 'audio':
        if (typeof event.audio_id !== 'string' || typeof event.offset !== 'number' || typeof event.pcm !== 'string') throw new Error('invalid_audio');
        life.playback.append(event.audio_id, event.offset, event.pcm); break;
      case 'audio_end': if (!event.audio_id) throw new Error('invalid_audio'); life.playback.end(event.audio_id); break;
      case 'interrupt': life.playback.stop(); break;
      case 'speech_start': case 'speech_done': break;
      case 'notice': this.update({ notice: event.code === 'speech_unavailable' ? '朗读暂不可用，文字和回答不受影响。' : '语音预览暂不可用；仅最终确认的文字会提交。' }); break;
      case 'error': this.fail(life, event.code === 'answer_unconfirmed' ? '回答结果未确认，请断开后同步现场与收据；不会自动重发。' : '实时处理未完成，已停止。未提交的文字仍显示在本页。'); break;
      default: throw new Error('unsupported_media_event');
    }
  }
  private async renew(life: Lifetime) {
    if (this.life !== life || !life.lease || life.renewing) return;
    life.renewing = true;
    try {
      await apiClient.post(`${path(this.recordId)}/${life.lease.session_id}/heartbeat`, { generation: life.lease.generation }, { signal: life.controller.signal, timeout: 15000 });
      this.send(life, { type: 'sync' });
    } catch { this.fail(life, '实时会话授权已失效，请重新连接。'); }
    finally { life.renewing = false; }
  }
  commit() {
    const life = this.life;
    if (!life || this.view.phase !== 'final' || !this.view.draftId || !life.questionId) return;
    const id = crypto.randomUUID();
    rememberAnswerIntent(this.recordId, id, life.questionId);
    this.command({ type: 'commit', draft_id: this.view.draftId, request_id: id });
    if (this.life === life) this.update({ phase: 'submitting' });
  }
  disconnect(notify = true) {
    const life = this.life; this.life = null;
    if (life) {
      life.controller.abort(); clearTimeout(life.deadline); clearInterval(life.heartbeat); clearInterval(life.progress);
      life.playback.stop(); life.channel.onclose = null; life.channel.onmessage = null; life.peer.onconnectionstatechange = null;
      life.stream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
      life.channel.close(); life.peer.close(); void life.context.close().catch(() => {});
      if (life.lease) void apiClient.post(`${path(this.recordId)}/${life.lease.session_id}/close`, { generation: life.lease.generation }, { timeout: 5000 }).catch(() => {});
    }
    if (notify) { this.update({ phase: 'offline', draftId: undefined, notice: '实时连接已停止。未发送的转写不会在重连时自动提交。' }); this.synchronize(); }
  }
  private fail(life: Lifetime, notice: string) {
    if (this.life !== life) return;
    this.disconnect(false); this.update({ phase: 'error', notice }); this.synchronize();
  }
}
