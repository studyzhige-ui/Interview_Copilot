import { useEffect, useRef, useState } from 'react';
import { getTranscriptAudio, type TranscriptPage } from '@/api/transcripts';

/** Blob URLs are bounded clips, owned by this versioned component and revoked. */
export function TranscriptAudio({ recordId, page }: { recordId: string; page: TranscriptPage }) {
  const [first, setFirst] = useState(page.words[0]?.word_id ?? '');
  const [last, setLast] = useState(page.words[0]?.word_id ?? '');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [loadedRange, setLoadedRange] = useState('');
  const request = useRef<AbortController | null>(null);
  const objectUrl = useRef('');
  const player = useRef<HTMLAudioElement | null>(null);
  useEffect(() => {
    const audio = player.current;
    return () => {
      request.current?.abort();
      if (audio) { audio.pause(); audio.removeAttribute('src'); }
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    };
  }, []);
  const reset = () => {
    request.current?.abort(); player.current?.pause();
    player.current?.removeAttribute('src');
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = ''; setUrl(''); setLoadedRange(''); setBusy(false);
  };
  const load = async () => {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    player.current?.pause();
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = ''; setUrl(''); setLoadedRange(''); setBusy(true); setError('');
    try {
      const blob = await getTranscriptAudio(recordId, {
        transcript_id: page.transcript_id, first_word_id: first, last_word_id: last,
      }, page.audio_sha256, controller.signal);
      if (controller.signal.aborted) return;
      const next = URL.createObjectURL(blob);
      objectUrl.current = next; setUrl(next); setLoadedRange(`${first} → ${last}`);
    } catch {
      if (!controller.signal.aborted) setError('无法回放所选原录音。请选择有时间证据、顺序正确且不超过 30 秒的词段；来源变化时不会播放替代文件。');
    } finally { if (!controller.signal.aborted) setBusy(false); }
  };
  return <section aria-label="原录音片段回放" className="space-y-2 rounded-lg border p-3 text-sm">
    <p>按原始词时间回放（最多 30 秒）。已纠正词的时间可能是估计值。</p>
    <div className="flex flex-wrap gap-3">
      <label>起始词 <select aria-label="回放起始词" value={first} onChange={(event) => { reset(); setFirst(event.target.value); setLast(event.target.value); }}>
        {page.words.map((word) => <option key={word.word_id} value={word.word_id}>{word.word_id} {word.text}</option>)}
      </select></label>
      <label>结束词 <select aria-label="回放结束词" value={last} onChange={(event) => { reset(); setLast(event.target.value); }}>
        {page.words.map((word) => <option key={word.word_id} value={word.word_id}>{word.word_id} {word.text}</option>)}
      </select></label>
      <button disabled={busy || !first || !last} onClick={() => void load()}>读取原录音片段</button>
    </div>
    {error && <p role="alert">{error}</p>}
    {loadedRange && <p>已载入：{loadedRange} · {page.transcript_id}</p>}
    <audio ref={player} controls src={url || undefined} preload="none" aria-label="所选原录音" />
  </section>;
}
