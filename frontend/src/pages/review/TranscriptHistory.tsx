import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getTranscriptHistory } from '@/api/transcripts';
import { ROLE_LABELS } from './TranscriptEditor';

// Database UTC timestamps may be serialized without an explicit offset.
const utcStamp = (value: string) => /[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;

export function TranscriptHistory({ recordId, onVersion }: { recordId: string; onVersion: (id: string) => void }) {
  const [cursors, setCursors] = useState<string[]>([]);
  const before = cursors.at(-1);
  const history = useQuery({
    queryKey: ['transcript-history', recordId, before],
    queryFn: ({ signal }) => getTranscriptHistory(recordId, before, signal), retry: false,
  });
  return <section aria-label="转写纠正历史" className="space-y-3">
    <h3 className="font-medium">转写纠正历史</h3>
    {history.isPending && <p role="status">正在读取纠正历史…</p>}
    {history.isError && <p role="alert">历史读取失败，并非没有记录。<button onClick={() => void history.refetch()}>重读历史</button></p>}
    {history.data?.items.length === 0 && <p>暂无转写纠正记录。</p>}
    {history.data?.items.map((item) => <article key={item.request_id} className="rounded border p-3 text-sm">
      <p>{item.reason}</p>
      <time dateTime={utcStamp(item.created_at)}>{new Date(utcStamp(item.created_at)).toLocaleString()}</time>
      <p>修改词：{item.word_ids.join('、') || '仅角色确认'}</p>
      <p>{Object.entries(item.confirmed_roles).map(([id, role]) => `${id}：${ROLE_LABELS[role]}`).join('；')}</p>
      <div className="mt-2 flex gap-3">
        <button onClick={() => onVersion(item.previous_transcript_id)}>查看修改前版本</button>
        <button onClick={() => onVersion(item.transcript_id)}>查看修改后版本</button>
      </div>
    </article>)}
    <div className="flex gap-3 text-sm">
      {cursors.length > 0 && <button onClick={() => setCursors((old) => old.slice(0, -1))}>较新历史</button>}
      {history.data?.next_cursor && <button onClick={() => setCursors((old) => [...old, history.data!.next_cursor!])}>更早历史</button>}
    </div>
  </section>;
}
