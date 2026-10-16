import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { changeAbilitySignalStatus, listAbilitySignals, recomputeInterviewAbilitySignals } from '@/api/careerProfile';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { Modal } from '@/components/ui/Modal';
import { Pill } from '@/components/ui/Pill';
import { FormItem, TextArea, displayDate } from '@/pages/career/CareerFields';
import { toast } from '@/store/uiStore';
import type { AbilitySignal } from '@/types/career';

const statuses = { active: '有效', disputed: '有异议', invalidated: '已失效', superseded: '已更新' };

/** Evidence and corrections live with ability analysis, never personal facts. */
export function AbilityEvidence() {
  const client = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [history, setHistory] = useState(false);
  const [decision, setDecision] = useState<{ signal: AbilitySignal; action: 'dispute' | 'invalidate' } | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const query = useQuery({ queryKey: ['ability-signals'], queryFn: () => listAbilitySignals(true), enabled: expanded });
  const groups = new Map<string, AbilitySignal[]>();
  for (const signal of query.data ?? []) {
    if (history || signal.status === 'active' || signal.status === 'disputed') groups.set(signal.topic, [...(groups.get(signal.topic) ?? []), signal]);
  }
  const run = async (operation: () => Promise<unknown>) => {
    setBusy(true);
    try { await operation(); await Promise.all([client.invalidateQueries({ queryKey: ['ability-signals'] }), client.invalidateQueries({ queryKey: ['analytics-report'] })]); setDecision(null); toast.success('分析依据已更新'); }
    catch (error) { toast.error(extractErr(error)); await client.invalidateQueries({ queryKey: ['ability-signals'] }); }
    finally { setBusy(false); }
  };

  return <>
    <details className="mt-6 rounded-xl border border-stone-200 bg-white p-5" onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary className="cursor-pointer text-sm font-semibold text-stone-800">查看分析依据与纠错</summary>
      <p className="mt-3 text-xs text-stone-500">按主题查看来源。发现不准确的判断，可以提出异议或根据原面试重算。</p>
      <label className="my-4 flex items-center gap-2 text-xs text-stone-500"><input type="checkbox" checked={history} onChange={(event) => setHistory(event.target.checked)} />显示已失效和已更新的判断</label>
      {query.isPending ? <p role="status">正在读取分析依据…</p> : query.isError ? <div role="alert">分析依据暂时无法加载。<Btn kind="ghost" size="sm" onClick={() => query.refetch()}>重试</Btn></div>
        : !groups.size ? <p className="text-sm text-stone-500">暂无对应的分析依据。</p>
          : [...groups].map(([topic, signals]) => <details key={topic} className="border-t border-stone-100 py-3">
            <summary className="cursor-pointer text-sm font-medium">{topic}<span className="ml-2 text-xs font-normal text-stone-400">{signals.length} 条来源判断</span></summary>
            <ul className="mt-3 divide-y divide-stone-100">{signals.map((signal) => <li key={signal.id} className="py-3">
              <div className="flex items-center gap-2"><Pill tone={signal.status === 'active' ? 'success' : signal.status === 'disputed' ? 'warn' : 'neutral'}>{statuses[signal.status]}</Pill><span className="text-xs text-stone-400">{displayDate(signal.formed_at)}</span></div>
              <p className="mt-2 text-sm leading-6 text-stone-700">{signal.summary}</p>
              {signal.limitations && <p className="mt-1 text-xs text-stone-500">{signal.limitations}</p>}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {signal.scope_kind === 'interview_record' && signal.scope_ref_id && <Link className="mr-2 text-xs text-primary-700 underline" to={`/review?id=${encodeURIComponent(signal.scope_ref_id)}`}>查看来源面试</Link>}
                {(signal.status === 'active' || signal.status === 'disputed') && <>
                  {signal.status === 'active' && <Btn kind="outline" size="sm" disabled={busy} onClick={() => { setDecision({ signal, action: 'dispute' }); setReason(''); }}>提出异议</Btn>}
                  {signal.scope_kind === 'interview_record' && signal.scope_ref_id && <Btn kind="ghost" size="sm" disabled={busy} onClick={() => run(() => recomputeInterviewAbilitySignals(signal.scope_ref_id!))}>根据原记录重算</Btn>}
                  <Btn kind="ghost" size="sm" disabled={busy} onClick={() => { setDecision({ signal, action: 'invalidate' }); setReason(''); }}>标记失效</Btn>
                </>}
              </div>
            </li>)}</ul>
          </details>)}
    </details>
    <Modal open={!!decision} onClose={() => setDecision(null)} title={decision?.action === 'dispute' ? '对这条判断提出异议' : '让这条判断失效'} width={520}
      footer={<><Btn kind="ghost" disabled={busy} onClick={() => setDecision(null)}>取消</Btn><Btn loading={busy} disabled={!reason.trim()} onClick={() => decision && run(() => changeAbilitySignalStatus(decision.signal, decision.action, reason.trim()))}>确认</Btn></>}>
      <FormItem label="原因"><TextArea rows={4} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="说明哪里不准确或不再适用" /></FormItem>
    </Modal>
  </>;
}
