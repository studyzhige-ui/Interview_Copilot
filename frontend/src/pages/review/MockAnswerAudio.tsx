import { useEffect, useRef, useState } from 'react';
import { getInterviewRecord } from '@/api/interview';
import { useAuthStore } from '@/store/authStore';

interface Props { recordId: string; qaId: string; assetId?: string | null; url: string }

/** One renewal per supplied capability, never substitute another answer's source. */
export function MockAnswerAudio(props: Props) {
  const subjectId = useAuthStore((state) => state.subjectId);
  const [originalOwner] = useState(subjectId);
  // Stale record props must not carry an old owner's bearer capability across login.
  if (!subjectId || subjectId !== originalOwner) return null;
  return <AnswerPlayer key={`${subjectId}:${props.recordId}:${props.qaId}:${props.assetId ?? ''}:${props.url}`} {...props} />;
}

function AnswerPlayer({ recordId, qaId, assetId, url }: Props) {
  const audio = useRef<HTMLAudioElement>(null);
  const request = useRef<AbortController | null>(null);
  const renewed = useRef(false);
  const pending = useRef(false);
  const restoreTime = useRef<number | null>(null);
  const [source, setSource] = useState<string | undefined>(url);
  const [generation, setGeneration] = useState(0);
  const [status, setStatus] = useState<'ready' | 'renewing' | 'renewed' | 'failed'>('ready');
  useEffect(() => {
    const player = audio.current;
    return () => {
      request.current?.abort();
      player?.pause();
      player?.removeAttribute('src');
    };
  }, [generation]);
  const recover = async () => {
    const player = audio.current;
    if (pending.current) return;
    const position = player?.currentTime ?? 0;
    player?.pause();
    player?.removeAttribute('src');
    setSource(undefined);
    if (renewed.current || !assetId) { setStatus('failed'); return; }
    renewed.current = true;
    const controller = new AbortController();
    request.current = controller;
    pending.current = true;
    setStatus('renewing');
    try {
      const detail = await getInterviewRecord(recordId, { signal: controller.signal });
      if (controller.signal.aborted) return;
      const answer = detail.id === recordId ? detail.qa.find((item) => item.id === qaId) : undefined;
      if (!answer?.answer_audio_url || answer.answer_audio_file_asset_id !== assetId) throw new Error('Original audio is no longer readable');
      restoreTime.current = Number.isFinite(position) ? Math.max(0, position) : 0;
      setSource(answer.answer_audio_url);
      setGeneration((value) => value + 1);
      setStatus('renewed');
    } catch {
      if (!controller.signal.aborted) setStatus('failed');
    } finally { pending.current = false; }
  };
  return <span className="min-w-0">
    <audio key={generation} ref={audio} controls preload="none" src={source} className="h-7 max-w-[220px]"
      aria-label="回答原录音" onError={() => { void recover(); }} onLoadedMetadata={() => {
        const player = audio.current;
        if (!player || restoreTime.current === null) return;
        const position = restoreTime.current;
        restoreTime.current = null;
        try { player.currentTime = Number.isFinite(player.duration) ? Math.min(position, Math.max(0, player.duration - 0.01)) : position; } catch { /* Some media backends cannot seek until playback starts. */ }
      }} />
    {status === 'renewing' && <span role="status" className="block text-xs text-stone-500">正在重新核实原录音…</span>}
    {status === 'renewed' && <span role="status" className="block text-xs text-stone-500">播放链接已刷新，请重新播放</span>}
    {status === 'failed' && <span role="alert" className="block text-xs text-stone-600">原录音暂不可用，请重新读取记录后再试。</span>}
  </span>;
}
