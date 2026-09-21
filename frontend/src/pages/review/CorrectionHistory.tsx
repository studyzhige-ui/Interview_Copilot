import { useEffect, useRef, useState } from 'react';
import { getQACorrections, type QACorrection } from '@/api/interview';

/** Owner-only, paginated evidence of explicit edits, not editable audit data. */
export function CorrectionHistory({ recordId }: { recordId: string }) {
  return <HistoryPage key={recordId} recordId={recordId} />;
}

function HistoryPage({ recordId }: { recordId: string }) {
  const alive = useRef(true);
  const [reload, setReload] = useState(0);
  const [items, setItems] = useState<QACorrection[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    alive.current = true;
    getQACorrections(recordId).then((result) => {
      if (!active) return;
      setItems(result.items); setCursor(result.next_cursor);
    }).catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; alive.current = false; };
  }, [recordId, reload]);
  const loadMore = async () => {
    if (!cursor || busy) return;
    setBusy(true); setError(false);
    try {
      const result = await getQACorrections(recordId, cursor);
      if (!alive.current) return;
      setItems((previous) => [...previous, ...result.items]); setCursor(result.next_cursor);
    } catch { if (alive.current) setError(true); } finally { if (alive.current) setBusy(false); }
  };
  return <section aria-label="问答修改历史" className="space-y-4">
    <p className="text-sm text-stone-500">保留修改前后文字与版本。旧评分仅作为历史依据，不再计入当前能力分析。</p>
    {error && <div role="alert">修改历史读取失败，并非没有历史。<button onClick={() => { setError(false); setBusy(true); setReload((value) => value + 1); }}>重试读取</button></div>}
    {!busy && !error && items.length === 0 && <p>暂无修改记录。</p>}
    {items.map((item) => <article key={item.id} className="rounded-lg border border-stone-200 p-4">
      <h3 className="text-sm font-semibold">{item.qa_id} · v{item.previous_version} → v{item.new_version}</h3>
      <time className="text-xs text-stone-500">{new Date(item.created_at).toLocaleString()}</time>
      {(['question', 'answer', 'critique', 'improved_answer'] as const).filter((field) => item.before[field] !== item.after[field]).map((field) =>
        <details key={field} className="mt-2"><summary>{({ question: '问题', answer: '回答', critique: '反馈', improved_answer: '改进回答' } as Record<string,string>)[field]}</summary>
          <p className="whitespace-pre-wrap text-sm">修改前：{item.before[field] ?? '未提供'}</p>
          <p className="whitespace-pre-wrap text-sm">修改后：{item.after[field] ?? '已失效'}</p>
        </details>)}
    </article>)}
    {busy && <p role="status">读取中…</p>}
    {cursor && <button onClick={() => { void loadMore(); }} disabled={busy}>加载更早记录</button>}
  </section>;
}
