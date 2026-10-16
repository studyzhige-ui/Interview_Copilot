import { useEffect, useState } from 'react';
import { useLocation, Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Bot, CheckCircle2, Plus } from 'lucide-react';
import { getNextActionAgenda } from '@/api/careerInsights';
import { createNextAction, editNextAction, listJobOpportunities, listNextActions, transitionNextAction } from '@/api/careerProcess';
import { listCurrentOffers } from '@/api/offers';
import { listAllArtifacts } from '@/api/artifacts';
import { listAllInterviewRecords } from '@/api/interview';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { EmptyState } from '@/components/ui/EmptyState';
import { Modal } from '@/components/ui/Modal';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import type { NextAction, NextActionStatus, NextActionTimeKind, JobOpportunity, OfferListItem, Artifact } from '@/types/career';
import type { InterviewRecordListItem } from '@/types/api';
import { FormItem, SelectInput, TextArea, TextInput, displayDate, isoFromLocal, localDateTimeFromIso } from './CareerFields';
import { copilotObjectHandoffHref } from '@/lib/copilotObjectReference';
const actionStatusLabels: Record<NextActionStatus, string> = {
  suggested: '建议', planned: '已计划', done: '已完成', closed: '已关闭',
};

function actionTone(status: NextActionStatus): 'primary' | 'success' | 'warn' | 'neutral' {
  return status === 'done' ? 'success' : status === 'planned' ? 'primary' : status === 'suggested' ? 'warn' : 'neutral';
}

function ActionEditor({
  open, busy, opportunities, interviews, offers, artifacts, selectedOpportunityId, initial, onClose, onSave,
}: {
  open: boolean;
  busy: boolean;
  opportunities: JobOpportunity[];
  interviews: InterviewRecordListItem[];
  offers: OfferListItem[];
  artifacts: Artifact[];
  selectedOpportunityId: string | null;
  initial?: NextAction | null;
  onClose: () => void;
  onSave: (form: Record<string, string>) => void;
}) {
  const [form, setForm] = useState<Record<string, string>>(() => ({
    content: initial?.content ?? '', status: initial?.status === 'suggested' ? 'suggested' : 'planned', time_kind: initial?.time_kind ?? 'flexible', job_opportunity_id: initial?.job_opportunity_id ?? selectedOpportunityId ?? '',
    interview_record_id: initial?.interview_record_id ?? '', offer_id: initial?.offer_id ?? '', artifact_id: initial?.artifact_id ?? '',
    starts_at: initial?.starts_at ? localDateTimeFromIso(initial.starts_at) : '', ends_at: initial?.ends_at ? localDateTimeFromIso(initial.ends_at) : '', due_at: initial?.due_at ? localDateTimeFromIso(initial.due_at) : '',
    reminder_at: initial?.reminder_at ? localDateTimeFromIso(initial.reminder_at) : '',
  }));
  const update = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return <Modal open={open} onClose={onClose} title={initial ? '编辑下一步行动' : '添加下一步行动'} width={720} footer={<><Btn kind="ghost" onClick={onClose}>取消</Btn><Btn loading={busy} disabled={!form.content.trim()} onClick={() => onSave(form)}>保存行动</Btn></>}>
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="sm:col-span-2"><FormItem label="要做什么"><TextArea autoFocus rows={3} value={form.content} onChange={(e) => update('content', e.target.value)} /></FormItem></div>
      <FormItem label="关联机会"><SelectInput value={form.job_opportunity_id} onChange={(e) => update('job_opportunity_id', e.target.value)}><option value="">不关联具体机会</option>{opportunities.filter((job) => !job.outcome).map((job) => <option key={job.id} value={job.id}>{job.company_name} · {job.job_title}</option>)}</SelectInput></FormItem>
      <FormItem label="时间类型"><SelectInput value={form.time_kind} onChange={(e) => update('time_kind', e.target.value)}><option value="flexible">灵活安排</option><option value="deadline">截止时间</option><option value="fixed">固定时间</option></SelectInput></FormItem>
      {form.time_kind === 'deadline' && <FormItem label="截止时间"><TextInput type="datetime-local" value={form.due_at} onChange={(e) => update('due_at', e.target.value)} /></FormItem>}
      {form.time_kind === 'fixed' && <><FormItem label="开始时间"><TextInput type="datetime-local" value={form.starts_at} onChange={(e) => update('starts_at', e.target.value)} /></FormItem><FormItem label="结束时间"><TextInput type="datetime-local" value={form.ends_at} onChange={(e) => update('ends_at', e.target.value)} /></FormItem></>}


    </div>
    <details className="mt-4 border-t border-stone-100 pt-4"><summary className="cursor-pointer text-sm text-stone-600">更多关联与提醒</summary><div className="mt-4 grid gap-4 sm:grid-cols-2">
      <FormItem label="关联面试"><SelectInput value={form.interview_record_id} onChange={(e) => update('interview_record_id', e.target.value)}><option value="">不关联面试</option>{interviews.map((record) => <option key={record.id} value={record.id}>{record.title}</option>)}</SelectInput></FormItem>
      <FormItem label="关联 Offer"><SelectInput value={form.offer_id} onChange={(e) => update('offer_id', e.target.value)}><option value="">不关联 Offer</option>{offers.map((entry) => <option key={entry.offer.id} value={entry.offer.id}>{entry.company_name} · {entry.job_title}</option>)}</SelectInput></FormItem>
      <FormItem label="关联材料"><SelectInput value={form.artifact_id} onChange={(e) => update('artifact_id', e.target.value)}><option value="">不关联材料</option>{artifacts.map((artifact) => <option key={artifact.id} value={artifact.id}>{artifact.current_version.title}</option>)}</SelectInput></FormItem>
      {form.status === 'planned' && <FormItem label="应用内提醒时间" hint="留空则不通知；建议设置在行动时间之前"><TextInput type="datetime-local" value={form.reminder_at} onChange={(e) => update('reminder_at', e.target.value)} /></FormItem>}
    </div></details>
  </Modal>;
}

function ActionCard({ action, job, busy, onEdit, onTransition }: { action: NextAction; job?: JobOpportunity; busy: boolean; onEdit: () => void; onTransition: (transition: 'plan' | 'complete' | 'close') => void }) {
  const time = action.time_kind === 'deadline' ? `截止 ${displayDate(action.due_at)}` : action.time_kind === 'fixed' ? displayDate(action.starts_at) : '灵活安排';
  return <article className="rounded-lg border border-stone-200 bg-white p-4">
    <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="font-medium text-stone-800">{action.content}</p><p className="mt-1 text-xs text-stone-500">{time}{job ? ` · ${job.company_name}` : ''}</p></div><Pill tone={actionTone(action.status)}>{actionStatusLabels[action.status]}</Pill></div>
    <div className="mt-2 flex flex-wrap gap-1">{action.interview_record_id && <Pill>面试</Pill>}{action.offer_id && <Pill>Offer</Pill>}{action.artifact_id && <Pill>材料</Pill>}{action.reminder_at && <Pill tone="primary">提醒 {displayDate(action.reminder_at)}</Pill>}</div>
    <div className="mt-3 flex flex-wrap gap-2"><Link to={copilotObjectHandoffHref('next_action', action.id, action.content)}><Btn kind="ghost" size="sm" icon={<Bot size={13} />}>询问 Copilot</Btn></Link>{(action.status === 'suggested' || action.status === 'planned') && <><Btn kind="ghost" size="sm" disabled={busy} onClick={onEdit}>编辑</Btn>{action.status === 'suggested' && <Btn kind="outline" size="sm" disabled={busy} onClick={() => onTransition('plan')}>加入计划</Btn>}<Btn size="sm" disabled={busy} icon={<CheckCircle2 size={14} />} onClick={() => onTransition('complete')}>完成</Btn><Btn kind="ghost" size="sm" disabled={busy} onClick={() => onTransition('close')}>关闭</Btn></>}</div>
  </article>;
}


export function ActionAgenda() {
  const client = useQueryClient();
  const { hash } = useLocation();
  const [params] = useSearchParams();
  const [past, setPast] = useState(false);
  const [actionEditor, setActionEditor] = useState(false);
  const [editingAction, setEditingAction] = useState<NextAction | null>(null);
  const [busy, setBusy] = useState(false);
  const agenda = useQuery({ queryKey: ['next-action-agenda'], queryFn: getNextActionAgenda, refetchInterval: 30000 });
  const completed = useQuery({ queryKey: ['next-actions', 'completed'], queryFn: () => listNextActions(['done', 'closed']), enabled: past });
  const jobsQuery = useQuery({ queryKey: ['job-opportunities', 'active'], queryFn: () => listJobOpportunities() });
  const interviewsQuery = useQuery({ queryKey: ['interview-records', 'action-link'], queryFn: () => listAllInterviewRecords(), enabled: actionEditor });
  const offersQuery = useQuery({ queryKey: ['current-offers', 'action-link'], queryFn: listCurrentOffers, enabled: actionEditor });
  const artifactsQuery = useQuery({ queryKey: ['artifacts', 'action-link'], queryFn: () => listAllArtifacts(), enabled: actionEditor });
  const jobs = jobsQuery.data ?? [];
  const effectiveSelectedId = params.get('opportunity');
  const items = agenda.data?.items ?? [];
  const actions = (past ? completed.data ?? [] : items.map((item) => item.action)).filter(action => !effectiveSelectedId || action.job_opportunity_id === effectiveSelectedId);
  const run = async (operation: () => Promise<unknown>, success: string) => {
    setBusy(true);
    try { await operation(); await Promise.all([
      client.invalidateQueries({ queryKey: ['next-action-agenda'] }), client.invalidateQueries({ queryKey: ['next-actions'] }),
      client.invalidateQueries({ queryKey: ['workspace'] }),
      client.invalidateQueries({ queryKey: ['career-workspace'] }),
    ]); toast.success(success); return true; }
    catch (error) { toast.error(extractErr(error)); await client.invalidateQueries({ queryKey: ['next-action-agenda'] }); return false; }
    finally { setBusy(false); }
  };
  useEffect(() => { if (hash && agenda.isSuccess) document.getElementById(hash.slice(1))?.scrollIntoView({ block: 'center' }); }, [hash, agenda.isSuccess]);
  const query = past ? completed : agenda;
  return <section className="rounded-xl border border-stone-200 bg-white p-5">
    <div className="flex items-center justify-between gap-3"><h2 className="font-semibold text-stone-800">行动安排</h2><Btn size="sm" icon={<Plus size={14} />} onClick={() => { setEditingAction(null); setActionEditor(true); }}>添加行动</Btn></div>
    <div className="profile-tabs mt-2" role="group" aria-label="筛选行动"><button aria-pressed={!past} onClick={() => setPast(false)}>待处理</button><button aria-pressed={past} onClick={() => setPast(true)}>已完成与关闭</button></div>
    {query.isPending ? <Spinner /> : query.isError ? <div role="alert">行动安排暂时无法加载。<Btn kind="ghost" onClick={() => query.refetch()}>重试</Btn></div>
      : !actions.length ? <EmptyState title={past ? '暂无完成记录' : '没有待处理的行动'} description={past ? '完成或关闭的行动会保留在这里。' : '记录一件具体的事，并选择是否需要安排时间。'} />
        : <div className="space-y-3">{actions.map((action) => <div key={action.id} id={'action-' + encodeURIComponent(action.id)} tabIndex={-1}>
          {items.find((item) => item.action.id === action.id)?.overdue && <p className="mb-1 text-xs text-danger-700">已逾期</p>}
          {!!items.find((item) => item.action.id === action.id)?.conflict_action_ids.length && <p className="mb-1 text-xs text-warning-700">与其他安排时间冲突</p>}
          <ActionCard action={action} job={jobs.find((job) => job.id === action.job_opportunity_id)} busy={busy} onEdit={() => { setEditingAction(action); setActionEditor(true); }} onTransition={(transition) => { void run(() => transitionNextAction(action, transition), transition === 'complete' ? '行动已完成' : '行动状态已更新'); }} />
        </div>)}</div>}
    {actionEditor && <ActionEditor key={editingAction?.id ?? 'new'} open busy={busy} opportunities={jobs} interviews={interviewsQuery.data ?? []} offers={offersQuery.data ?? []} artifacts={artifactsQuery.data ?? []} selectedOpportunityId={effectiveSelectedId} initial={editingAction} onClose={() => { setActionEditor(false); setEditingAction(null); }} onSave={async (form) => { const key = crypto.randomUUID(); const timeKind = form.time_kind as NextActionTimeKind; if (timeKind === 'deadline' && !form.due_at) { toast.warn('请填写截止时间'); return; } if (timeKind === 'fixed' && !form.starts_at) { toast.warn('请填写开始时间'); return; } if (timeKind === 'fixed' && form.ends_at && new Date(form.ends_at) < new Date(form.starts_at)) { toast.warn('结束时间不能早于开始时间'); return; } const common = { content: form.content.trim(), time_kind: timeKind, job_opportunity_id: form.job_opportunity_id || undefined, interview_record_id: form.interview_record_id || undefined, offer_id: form.offer_id || undefined, artifact_id: form.artifact_id || undefined, starts_at: timeKind === 'fixed' && form.starts_at ? isoFromLocal(form.starts_at) : undefined, ends_at: timeKind === 'fixed' && form.ends_at ? isoFromLocal(form.ends_at) : undefined, due_at: timeKind === 'deadline' && form.due_at ? isoFromLocal(form.due_at) : undefined, original_time_text: timeKind === 'flexible' ? undefined : timeKind === 'fixed' ? form.starts_at : form.due_at, source_timezone: timeKind === 'flexible' ? undefined : Intl.DateTimeFormat().resolvedOptions().timeZone, reminder_at: form.reminder_at ? isoFromLocal(form.reminder_at) : undefined, reminder_channel: form.reminder_at ? 'in_app' as const : undefined }; const ok = editingAction ? await run(() => editNextAction({ action: editingAction, ...common }), '行动已更新') : await run(() => createNextAction({ ...common, status: form.status as 'suggested' | 'planned', source_kind: 'user_request', source_identity: `ui:${key}`, idempotency_key: key }), '下一步行动已保存'); if (ok) { setActionEditor(false); setEditingAction(null); } }} />}
  </section>;
}
