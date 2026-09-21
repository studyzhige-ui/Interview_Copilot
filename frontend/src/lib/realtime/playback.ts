/** Bounded Web Audio scheduling. Reported rendering is not proof of human hearing. */
export interface AudioStart { audio_id: string; rate: number; samples: number }
interface Playing extends AudioStart { received: number; startedAt: number | null; ended: boolean; reported: number }
export class RealtimePlayback {
  private current: Playing | null = null;
  private nodes = new Set<AudioBufferSourceNode>();
  private ignored: string | null = null;
  constructor(private context: AudioContext, private report: (id: string, samples: number, complete: boolean) => void) {}
  begin(value: AudioStart) {
    if (this.current || !value.audio_id || value.rate !== 24000 || !Number.isSafeInteger(value.samples) || value.samples < 1 || value.samples > 1440000) throw new Error('invalid_audio_start');
    this.ignored = null;
    this.current = { ...value, received: 0, startedAt: null, ended: false, reported: 0 };
  }
  append(id: string, offset: number, encoded: string) {
    if (id === this.ignored) return;
    const group = this.current;
    if (!group || group.audio_id !== id || group.ended || offset !== group.received || encoded.length > 16384 || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) throw new Error('invalid_audio_chunk');
    const raw = atob(encoded);
    if (!raw.length || raw.length % 2 || group.received + raw.length / 2 > group.samples) throw new Error('audio_capacity');
    const buffer = this.context.createBuffer(1, raw.length / 2, group.rate);
    const values = buffer.getChannelData(0);
    for (let i = 0; i < values.length; i++) {
      const value = raw.charCodeAt(i * 2) | (raw.charCodeAt(i * 2 + 1) << 8);
      values[i] = (value >= 32768 ? value - 65536 : value) / 32768;
    }
    if (this.context.state !== 'running') throw new Error('audio_context_not_running');
    group.startedAt ??= this.context.currentTime + 0.12;
    const at = group.startedAt + offset / group.rate;
    if (at < this.context.currentTime - 0.1 || this.nodes.size >= 256) throw new Error('audio_playback_overrun');
    const node = this.context.createBufferSource();
    node.buffer = buffer; node.connect(this.context.destination);
    this.nodes.add(node);
    node.onended = () => { this.nodes.delete(node); node.disconnect(); };
    node.start(at); group.received += values.length;
  }
  end(id: string) {
    if (id === this.ignored) return;
    if (!this.current || this.current.audio_id !== id || this.current.received !== this.current.samples) throw new Error('audio_incomplete');
    this.current.ended = true;
  }
  progress() {
    const group = this.current;
    if (!group || group.startedAt === null || this.context.state !== 'running') return;
    const rendered = Math.max(group.reported, Math.min(group.received, Math.floor(Math.max(0, this.context.currentTime - group.startedAt) * group.rate)));
    const complete = group.ended && rendered === group.samples;
    if (rendered > group.reported || complete) {
      this.report(group.audio_id, rendered, complete); group.reported = rendered;
    }
    if (complete) this.current = null;
  }
  stop(report = false) {
    if (report) this.progress();
    this.ignored = this.current?.audio_id ?? this.ignored;
    this.current = null;
    for (const node of this.nodes) { node.onended = null; try { node.stop(); } catch { /* already ended */ } node.disconnect(); }
    this.nodes.clear();
  }
}
