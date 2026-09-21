import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import type { components } from '@/types/generated/realtime';
import { useRealtimeInterview, type LiveDraft } from '@/hooks/useRealtimeInterview';
import type { MockLiveMessage } from '@/types/api';

interface Props {
  recordId: string; disabled: boolean; onActive: (active: boolean) => void;
  onCommit: (draft: LiveDraft) => void;
  onResult: (message: MockLiveMessage, endSuggested: boolean) => void;
  onState: (messages: MockLiveMessage[]) => void;
  onUnconfirmed: () => void;
}
const labels: Record<string, string> = { connecting: '正在连接本地麦克风', listening: '正在聆听', finalizing: '正在确认完整转写', awaiting_commit: '请确认回答', answering: '面试官正在回应', blocked: '已暂停', disconnected: '未连接' };
export function RealtimeVoiceControl(props: Props) {
  const live = useRealtimeInterview(props.recordId, props);
  const [automatic, setAutomatic] = useState(false);
  const active = live.phase !== 'disconnected';
  const { onActive } = props;
  useEffect(() => { onActive(active); }, [active, onActive]);
  if (!live.enabled) return null;
  return <section aria-label="本地实时语音" className="border-b border-stone-200 bg-stone-50 px-6 py-3 text-sm">
    <div className="flex flex-wrap items-center gap-3">
      <strong>本地实时语音</strong><span role="status">{labels[live.phase] ?? live.phase}</span>
      {!active ? <>
        <label><input type="checkbox" checked={automatic} onChange={(e) => setAutomatic(e.target.checked)} /> 检测到说完后自动发送（会调用面试模型）</label>
        <button disabled={props.disabled} onClick={() => void live.connect(automatic)}>连接实时语音</button>
      </> : <>
        <button onClick={live.disconnect}>断开实时语音</button>
        <button onClick={() => live.control('interrupt')}>打断朗读</button>
        <button disabled={live.phase !== 'listening'} onClick={() => live.control('finish')}>我已说完</button>
        <button disabled={live.phase !== 'listening'} onClick={() => live.control('play_question')}>朗读当前问题</button>
      </>}
    </div>
    <p className="text-xs text-stone-500 mt-2">单次回答最多 {live.maxSeconds} 秒。临时转写不保存；断开不会自动重发回答。播放记录是浏览器报告，不代表已经听到。</p>
    {live.error && <p role="alert" className="text-amber-800 mt-2">{live.error}</p>}
    {live.partial && <p className="text-stone-500 mt-2">临时转写：{live.partial}</p>}
    {live.draft && <div className="mt-2"><p className="whitespace-pre-wrap">{live.draft.text}</p><button onClick={() => live.control('commit')}>确认并发送回答</button></div>}
    {(live.phase === 'blocked' || live.draft) && <button onClick={() => live.control('discard')}>丢弃当前语音并重新聆听</button>}
    <PlaybackHistory recordId={props.recordId} />
  </section>;
}

function PlaybackHistory({ recordId }: { recordId: string }) {
  const reports = useQuery({
    queryKey: ['mock', recordId, 'media-playback'],
    queryFn: async ({ signal }) => (await apiClient.get<components['schemas']['MediaPlaybackReport'][]>(`/mock-interviews/${encodeURIComponent(recordId)}/media/playback`, { signal })).data,
  });
  return (<details className="mt-2 text-xs"><summary>朗读播放记录（最近 50 条）</summary>
      <button onClick={() => void reports.refetch()}>刷新播放记录</button>
      {reports.isError && <p role="alert">播放记录加载失败，未自动重新生成音频。</p>}
      {reports.data?.map((item) => <p key={item.playback_id}>问题 #{item.message_id} · {item.status} · 生成 {(item.generated_samples / item.sample_rate).toFixed(1)} 秒 / 已发送 {(item.delivered_samples / item.sample_rate).toFixed(1)} 秒 / 浏览器报告 {(item.client_reported_samples / item.sample_rate).toFixed(1)} 秒</p>)}
    </details>);
}
