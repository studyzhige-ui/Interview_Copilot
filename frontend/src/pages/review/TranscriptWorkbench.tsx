import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getTranscript, type TranscriptReceipt, type TranscriptWord, type TranscriptPage } from '@/api/transcripts';
import { PendingTranscriptReceipt, ROLE_LABELS, TranscriptEditor } from './TranscriptEditor';
import { TranscriptAudio } from './TranscriptAudio';
import { TranscriptHistory } from './TranscriptHistory';

interface Props { recordId: string; onCorrected?: (needsAnalysis: boolean) => void; onReanalyze?: () => void; reanalyzing?: boolean }
const pendingKey = (id: string) => `transcript-pending-receipt:${id}`;
function readPending(id: string): string | null {
  try { const value = sessionStorage.getItem(pendingKey(id)); return value && /^[0-9a-f-]{36}$/.test(value) ? value : null; }
  catch { return null; }
}

export function TranscriptWorkbench(props: Props) {
  return <Workbench key={props.recordId} {...props} />;
}
function Workbench({ recordId, onCorrected, onReanalyze, reanalyzing = false }: Props) {
  const cache = useQueryClient();
  const [view, setView] = useState<{ id?: string; offset: number }>({ offset: 0 });
  const [editor, setEditor] = useState<{ page: TranscriptPage; word?: TranscriptWord; speaker?: string } | null>(null);
  const [pending, setPending] = useState(() => readPending(recordId));
  const [notice, setNotice] = useState('');
  const query = useQuery({
    queryKey: ['transcript', recordId, view.id ?? 'current', view.offset],
    queryFn: ({ signal }) => getTranscript(recordId, { transcriptId: view.id, offset: view.offset, signal }),
    retry: false, refetchOnWindowFocus: false,
  });
  const page = query.data;
  const historical = page && page.transcript_id !== page.current_transcript_id;
  const markPending = (id: string | null) => {
    setPending(id);
    try { if (id) sessionStorage.setItem(pendingKey(recordId), id); else sessionStorage.removeItem(pendingKey(recordId)); }
    catch { setNotice('浏览器未允许保存请求编号；请在离开页面前核对收据。'); }
  };
  const saved = (receipt: TranscriptReceipt) => {
    markPending(null); setEditor(null); setView({ offset: 0 });
    setNotice(receipt.reanalysis_required
      ? '纠正已确认。旧问答、评分和报告已失效；重新分析需要你的明确操作。'
      : '纠正收据已确认，正在读取服务器当前转写版本。');
    void cache.invalidateQueries({ queryKey: ['transcript', recordId] });
    void cache.invalidateQueries({ queryKey: ['transcript-history', recordId] });
    onCorrected?.(receipt.reanalysis_required);
  };
  const changeVersion = (id?: string) => { setEditor(null); setView({ id, offset: 0 }); };

  return <section aria-label="词级转写工作区" className="space-y-5">
    <p className="text-sm text-stone-500">原词证据、人工纠正与模型建议分别展示。历史版本只读，不自动覆盖草稿或重新分析。</p>
    {notice && <p role="status" className="rounded bg-amber-50 p-3 text-sm">{notice}</p>}
    {pending && !editor && <PendingTranscriptReceipt recordId={recordId} requestId={pending} onSaved={saved} onDismiss={() => markPending(null)} />}
    {query.isPending && <p role="status">正在读取词级转写…</p>}
    {query.isError && <p role="alert">词级证据暂不可用。保留原始转录显示，不将读取失败当作空转写。<button onClick={() => void query.refetch()}>重读转写</button></p>}
    {page && <>
      <div className="break-all text-xs text-stone-500">
        <p>版本：{page.transcript_id} · 来源：{page.source} · 共 {page.word_count} 个词</p>
        <p>音频资产：{page.audio_file_asset_id} · 版本：{page.audio_file_asset_version}</p>
      </div>
      {historical && <p role="status">正在查看历史版本（只读）。<button disabled={!!editor} onClick={() => changeVersion()}>返回当前转写</button></p>}
      <div className="space-y-2 text-sm">
        {page.speakers.map((speaker) => <div key={speaker} className="flex flex-wrap gap-3">
          <strong>{speaker}</strong>
          <span>用户确认：{ROLE_LABELS[page.confirmed_roles[speaker] ?? 'unknown']}</span>
          {page.suggested_roles[speaker] && <span className="text-stone-500">模型建议：{ROLE_LABELS[page.suggested_roles[speaker]]}（未自动采纳）</span>}
          {!historical && <button disabled={!!editor || !!pending || reanalyzing} onClick={() => setEditor({ page, speaker })}>确认 {speaker} 角色</button>}
        </div>)}
      </div>
      {editor && <TranscriptEditor key={`${editor.page.transcript_id}:${editor.word?.word_id ?? editor.speaker}`}
        recordId={recordId} {...editor} onPending={markPending} onSaved={saved} onClose={() => setEditor(null)} />}
      <ol aria-label="原始词证据" className="space-y-2">
        {page.words.map((word) => <li key={word.word_id} className="flex flex-wrap items-baseline gap-2 rounded border border-stone-100 p-2 text-sm">
          <span className="text-xs text-stone-500">{word.word_id} · {word.speaker_id ?? '未知说话人'}</span>
          <span className="whitespace-pre-wrap">{word.text}</span>
          <span className="text-xs text-stone-500">{word.start === null ? '时间未知' : `${word.start.toFixed(2)}–${word.end?.toFixed(2)} 秒`}
            {word.alignment_status === 'estimated' && '（估计）'}{word.overlap && ' · 同时说话'}</span>
          {!historical && <button disabled={!!editor || !!pending || reanalyzing} onClick={() => setEditor({ page, word })} aria-label={`纠正 ${word.word_id}`}>纠正</button>}
        </li>)}
      </ol>
      <div className="flex gap-3 text-sm">
        <button disabled={!!editor || view.offset === 0} onClick={() => setView({ id: page.transcript_id, offset: Math.max(0, view.offset - 100) })}>上一页原词</button>
        <button disabled={!!editor || page.next_offset === null} onClick={() => setView({ id: page.transcript_id, offset: page.next_offset! })}>下一页原词</button>
      </div>
      {page.words.length > 0 && <TranscriptAudio key={`${page.transcript_id}:${view.offset}`} recordId={recordId} page={page} />}
      {onReanalyze && <button disabled={reanalyzing || !!pending || !!editor || !!historical} onClick={onReanalyze} className="rounded border px-3 py-2 text-sm">
        {reanalyzing ? '正在重新分析…' : '根据当前转写重新提取并分析'}
      </button>}
    </>}
    {!editor && <TranscriptHistory recordId={recordId} onVersion={changeVersion} />}
  </section>;
}
