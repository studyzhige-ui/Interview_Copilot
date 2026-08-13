import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  BriefcaseBusiness,
  CalendarClock,
  CheckCircle2,
  CircleDot,
  ExternalLink,
  FileText,
  History,
  Pencil,
  Plus,
  RefreshCw,
  Bot,
} from 'lucide-react';
import {
  appendProcessEvent,
  correctProcessEvent,
  createJobOpportunity,
  createNextAction,
  listJobOpportunities,
  listNextActions,
  listProcessEvents,
  replaceJobOpportunityDirections,
  transitionNextAction,
} from '@/api/careerProcess';
import { getCareerProfile } from '@/api/careerProfile';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { EmptyState } from '@/components/ui/EmptyState';
import { Modal } from '@/components/ui/Modal';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import type {
  CareerProfileDirection,
  JobOpportunity,
  NextAction,
  NextActionStatus,
  NextActionTimeKind,
  ProcessEvent,
  ProcessEventKind,
} from '@/types/career';
import {
  displayDate,
  FormItem,
  isoFromLocal,
  localDateTimeFromIso,
  localDateTimeNow,
  SelectInput,
  TextArea,
  TextInput,
} from './CareerFields';
import { copilotObjectHandoffHref } from '@/lib/copilotObjectReference';

const jobPhaseLabels: Record<JobOpportunity['phase'], string> = {
  pending_application: '待投递', applied: '已投递', in_process: '进行中', offer: 'Offer',
};
const outcomeLabels: Record<NonNullable<JobOpportunity['outcome']>, string> = {
  rejected: '未通过', withdrawn: '已退出', posting_closed: '岗位关闭', declined_offer: '拒绝 Offer', accepted: '已接受',
};
const eventLabels: Record<ProcessEventKind, string> = {
  tracking_started: '开始跟进', preparation_started: '开始准备', application_submitted: '已投递',
  application_acknowledged: '收到投递确认', recruiter_contact: '招聘方联系', assessment_invited: '收到测评邀请',
  assessment_completed: '完成测评', hiring_step: '招聘流程进展', interview_scheduled: '面试已安排',
  interview_completed: '面试已完成', background_check_started: '开始背调', offer_received: '收到 Offer',
  rejected: '未通过', withdrawn: '主动退出', posting_closed: '岗位关闭', offer_declined: '拒绝 Offer',
  offer_accepted: '接受 Offer',
};
const actionStatusLabels: Record<NextActionStatus, string> = {
  suggested: '建议', planned: '已计划', done: '已完成', closed: '已关闭',
};

function jobTone(job: JobOpportunity): 'primary' | 'success' | 'warn' | 'neutral' {
  if (job.outcome === 'accepted') return 'success';
  if (job.outcome) return 'neutral';
  if (job.phase === 'offer') return 'success';
  if (job.phase === 'in_process') return 'primary';
  return 'warn';
}

function actionTone(status: NextActionStatus): 'primary' | 'success' | 'warn' | 'neutral' {
  return status === 'done' ? 'success' : status === 'planned' ? 'primary' : status === 'suggested' ? 'warn' : 'neutral';
}

function OpportunityEditor({
  open,
  busy,
  directions,
  onClose,
  onSave,
}: {
  open: boolean;
  busy: boolean;
  directions: CareerProfileDirection[];
  onClose: () => void;
  onSave: (form: Record<string, string>, directionIds: string[]) => void;
}) {
  const [form, setForm] = useState<Record<string, string>>({
    company_name: '', job_title: '', location: '', team: '', source_url: '',
    entry_reason: 'explicit_tracking', occurred_at: localDateTimeNow(), source_description: '',
  });
  const [directionIds, setDirectionIds] = useState<string[]>([]);
  const update = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const toggleDirection = (directionId: string) => setDirectionIds((current) => (
    current.includes(directionId)
      ? current.filter((item) => item !== directionId)
      : [...current, directionId]
  ));
  return (
    <Modal open={open} onClose={onClose} title="添加求职机会" width={680} footer={<>
      <Btn kind="ghost" onClick={onClose} disabled={busy}>取消</Btn>
      <Btn loading={busy} disabled={!form.company_name.trim() || !form.job_title.trim() || !form.source_description.trim()} onClick={() => onSave(form, directionIds)}>开始跟进</Btn>
    </>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormItem label="公司"><TextInput autoFocus value={form.company_name} onChange={(e) => update('company_name', e.target.value)} /></FormItem>
        <FormItem label="岗位"><TextInput value={form.job_title} onChange={(e) => update('job_title', e.target.value)} /></FormItem>
        <FormItem label="地点"><TextInput value={form.location} onChange={(e) => update('location', e.target.value)} /></FormItem>
        <FormItem label="团队"><TextInput value={form.team} onChange={(e) => update('team', e.target.value)} /></FormItem>
        <FormItem label="为什么加入跟进">
          <SelectInput value={form.entry_reason} onChange={(e) => update('entry_reason', e.target.value)}>
            <option value="explicit_tracking">明确加入跟进</option>
            <option value="targeted_preparation">为该岗位准备</option>
            <option value="user_confirmed_application">我已确认投递</option>
          </SelectInput>
        </FormItem>
        <FormItem label="发生时间"><TextInput type="datetime-local" value={form.occurred_at} onChange={(e) => update('occurred_at', e.target.value)} /></FormItem>
        <div className="sm:col-span-2"><FormItem label="岗位链接"><TextInput type="url" value={form.source_url} onChange={(e) => update('source_url', e.target.value)} /></FormItem></div>
        <div className="sm:col-span-2"><FormItem label="记录说明" hint="这是你确认加入跟进的原始说明"><TextArea rows={3} value={form.source_description} onChange={(e) => update('source_description', e.target.value)} placeholder="例如：在公司官网看到岗位，准备本周申请" /></FormItem></div>
        {directions.length > 0 && <fieldset className="sm:col-span-2">
          <legend className="mb-2 text-sm font-medium text-stone-700">关联求职方向（可多选）</legend>
          <div className="grid gap-2 sm:grid-cols-2">{directions.filter((direction) => direction.lifecycle !== 'archived').map((direction) => <label key={direction.id} className="flex items-center gap-2 rounded-lg border border-stone-200 px-3 py-2 text-sm text-stone-700"><input type="checkbox" checked={directionIds.includes(direction.id)} onChange={() => toggleDirection(direction.id)} />{direction.label}</label>)}</div>
        </fieldset>}
      </div>
    </Modal>
  );
}

function DirectionEditor({
  open, busy, opportunity, directions, onClose, onSave,
}: {
  open: boolean;
  busy: boolean;
  opportunity: JobOpportunity;
  directions: CareerProfileDirection[];
  onClose: () => void;
  onSave: (directionIds: string[]) => void;
}) {
  const currentIds = opportunity.direction_links.map((link) => link.career_profile_direction_id);
  const [directionIds, setDirectionIds] = useState<string[]>(currentIds);
  const toggleDirection = (directionId: string) => setDirectionIds((current) => (
    current.includes(directionId)
      ? current.filter((item) => item !== directionId)
      : [...current, directionId]
  ));
  const choices = directions.filter((direction) => (
    direction.lifecycle !== 'archived' || currentIds.includes(direction.id)
  ));
  return <Modal open={open} onClose={onClose} title="关联求职方向" width={560} footer={<><Btn kind="ghost" onClick={onClose} disabled={busy}>取消</Btn><Btn loading={busy} onClick={() => onSave(directionIds)}>保存关联</Btn></>}>
    {choices.length === 0 ? <p className="text-sm text-stone-500">请先在个人详情中创建求职方向。</p> : <div className="space-y-2">{choices.map((direction) => <label key={direction.id} className="flex items-center justify-between gap-3 rounded-lg border border-stone-200 px-3 py-2 text-sm text-stone-700"><span className="flex items-center gap-2"><input type="checkbox" checked={directionIds.includes(direction.id)} onChange={() => toggleDirection(direction.id)} />{direction.label}</span>{direction.lifecycle === 'archived' && <span className="text-xs text-stone-400">已归档</span>}</label>)}</div>}
  </Modal>;
}

function EventEditor({
  open, busy, initial, onClose, onSave,
}: { open: boolean; busy: boolean; initial?: ProcessEvent | null; onClose: () => void; onSave: (form: Record<string, string>) => void }) {
  const [form, setForm] = useState<Record<string, string>>(() => ({
    kind: initial && initial.kind !== 'retraction' ? initial.kind : 'recruiter_contact',
    occurred_at: initial ? localDateTimeFromIso(initial.occurred_at) : localDateTimeNow(),
    description: initial?.description ?? '',
    step_summary: initial?.step_summary ?? '',
  }));
  const update = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return <Modal open={open} onClose={onClose} title={initial ? '更正流程事实' : '记录进展'} width={620} footer={<><Btn kind="ghost" onClick={onClose}>取消</Btn><Btn loading={busy} disabled={!form.description.trim()} onClick={() => onSave(form)}>{initial ? '追加更正记录' : '保存进展'}</Btn></>}>
    <div className="space-y-4">
      <FormItem label="进展类型"><SelectInput value={form.kind} onChange={(e) => update('kind', e.target.value)}>{Object.entries(eventLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</SelectInput></FormItem>
      <FormItem label="发生时间"><TextInput type="datetime-local" value={form.occurred_at} onChange={(e) => update('occurred_at', e.target.value)} /></FormItem>
      <FormItem label="简短阶段说明"><TextInput value={form.step_summary} onChange={(e) => update('step_summary', e.target.value)} placeholder="例如：一面结束，等待结果" /></FormItem>
      <FormItem label="真实情况"><TextArea rows={4} value={form.description} onChange={(e) => update('description', e.target.value)} placeholder="写下已发生的事实" /></FormItem>
    </div>
  </Modal>;
}

function ActionEditor({
  open, busy, opportunities, selectedOpportunityId, onClose, onSave,
}: {
  open: boolean;
  busy: boolean;
  opportunities: JobOpportunity[];
  selectedOpportunityId: string | null;
  onClose: () => void;
  onSave: (form: Record<string, string>) => void;
}) {
  const [form, setForm] = useState<Record<string, string>>({
    content: '', status: 'planned', time_kind: 'flexible', job_opportunity_id: selectedOpportunityId ?? '',
    starts_at: '', ends_at: '', due_at: '', original_time_text: '', source_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  });
  const update = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return <Modal open={open} onClose={onClose} title="添加下一步行动" width={650} footer={<><Btn kind="ghost" onClick={onClose}>取消</Btn><Btn loading={busy} disabled={!form.content.trim()} onClick={() => onSave(form)}>保存行动</Btn></>}>
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="sm:col-span-2"><FormItem label="要做什么"><TextArea autoFocus rows={3} value={form.content} onChange={(e) => update('content', e.target.value)} /></FormItem></div>
      <FormItem label="关联机会"><SelectInput value={form.job_opportunity_id} onChange={(e) => update('job_opportunity_id', e.target.value)}><option value="">不关联具体机会</option>{opportunities.filter((job) => !job.outcome).map((job) => <option key={job.id} value={job.id}>{job.company_name} · {job.job_title}</option>)}</SelectInput></FormItem>
      <FormItem label="状态"><SelectInput value={form.status} onChange={(e) => update('status', e.target.value)}><option value="planned">已计划</option><option value="suggested">暂存为建议</option></SelectInput></FormItem>
      <FormItem label="时间类型"><SelectInput value={form.time_kind} onChange={(e) => update('time_kind', e.target.value)}><option value="flexible">灵活安排</option><option value="deadline">截止时间</option><option value="fixed">固定时间</option></SelectInput></FormItem>
      {form.time_kind === 'deadline' && <FormItem label="截止时间"><TextInput type="datetime-local" value={form.due_at} onChange={(e) => update('due_at', e.target.value)} /></FormItem>}
      {form.time_kind === 'fixed' && <><FormItem label="开始时间"><TextInput type="datetime-local" value={form.starts_at} onChange={(e) => update('starts_at', e.target.value)} /></FormItem><FormItem label="结束时间"><TextInput type="datetime-local" value={form.ends_at} onChange={(e) => update('ends_at', e.target.value)} /></FormItem></>}
      {form.time_kind !== 'flexible' && <><FormItem label="原始时间表达"><TextInput value={form.original_time_text} onChange={(e) => update('original_time_text', e.target.value)} placeholder="例如：周五 18:00 前" /></FormItem><FormItem label="时区"><TextInput value={form.source_timezone} onChange={(e) => update('source_timezone', e.target.value)} /></FormItem></>}
    </div>
  </Modal>;
}

function ActionCard({ action, job, busy, onTransition }: { action: NextAction; job?: JobOpportunity; busy: boolean; onTransition: (transition: 'plan' | 'complete' | 'close') => void }) {
  const time = action.time_kind === 'deadline' ? `截止 ${displayDate(action.due_at)}` : action.time_kind === 'fixed' ? displayDate(action.starts_at) : '灵活安排';
  return <article className="rounded-lg border border-stone-200 bg-white p-4">
    <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="font-medium text-stone-800">{action.content}</p><p className="mt-1 text-xs text-stone-500">{time}{job ? ` · ${job.company_name}` : ''}</p></div><Pill tone={actionTone(action.status)}>{actionStatusLabels[action.status]}</Pill></div>
    <div className="mt-3 flex flex-wrap gap-2"><Link to={copilotObjectHandoffHref('next_action', action.id, action.content)}><Btn kind="ghost" size="sm" icon={<Bot size={13} />}>询问 Copilot</Btn></Link>{(action.status === 'suggested' || action.status === 'planned') && <>{action.status === 'suggested' && <Btn kind="outline" size="sm" disabled={busy} onClick={() => onTransition('plan')}>加入计划</Btn>}<Btn size="sm" disabled={busy} icon={<CheckCircle2 size={14} />} onClick={() => onTransition('complete')}>完成</Btn><Btn kind="ghost" size="sm" disabled={busy} onClick={() => onTransition('close')}>关闭</Btn></>}</div>
  </article>;
}

export function CareerProcessPage() {
  const queryClient = useQueryClient();
  const jobsQuery = useQuery({ queryKey: ['job-opportunities'], queryFn: () => listJobOpportunities(true) });
  const actionsQuery = useQuery({ queryKey: ['next-actions'], queryFn: () => listNextActions() });
  const profileQuery = useQuery({ queryKey: ['career-profile'], queryFn: getCareerProfile, retry: false });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [opportunityEditor, setOpportunityEditor] = useState(false);
  const [directionEditor, setDirectionEditor] = useState(false);
  const [eventEditor, setEventEditor] = useState(false);
  const [correctingEvent, setCorrectingEvent] = useState<ProcessEvent | null>(null);
  const [actionEditor, setActionEditor] = useState(false);
  const [busy, setBusy] = useState(false);
  const jobs = jobsQuery.data ?? [];
  const effectiveSelectedId = selectedId ?? jobs[0]?.id ?? null;
  const selected = jobs.find((job) => job.id === effectiveSelectedId) ?? null;
  const directions = useMemo(
    () => profileQuery.data?.directions ?? [],
    [profileQuery.data?.directions],
  );
  const directionsById = useMemo(
    () => new Map(directions.map((direction) => [direction.id, direction])),
    [directions],
  );
  const eventsQuery = useQuery({
    queryKey: ['process-events', effectiveSelectedId],
    queryFn: () => listProcessEvents(effectiveSelectedId!),
    enabled: Boolean(effectiveSelectedId),
  });

  const activeActions = useMemo(() => (actionsQuery.data ?? []).filter((action) => action.status === 'suggested' || action.status === 'planned'), [actionsQuery.data]);

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['job-opportunities'] }),
      queryClient.invalidateQueries({ queryKey: ['next-actions'] }),
      queryClient.invalidateQueries({ queryKey: ['process-events'] }),
    ]);
  };
  const run = async (operation: () => Promise<unknown>, success: string): Promise<boolean> => {
    setBusy(true);
    try { await operation(); await refresh(); toast.success(success); return true; }
    catch (error) { toast.error(extractErr(error)); return false; }
    finally { setBusy(false); }
  };

  if (jobsQuery.isLoading || actionsQuery.isLoading) return <div className="flex items-center gap-2 p-6 text-sm text-stone-500"><Spinner size={15} />正在加载求职进程…</div>;

  return <div className="mx-auto max-w-7xl p-4 md:p-6">
    <header className="mb-5 flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-xl font-semibold text-stone-800">求职进程</h1><p className="mt-1 text-sm text-stone-500">岗位机会、已发生的流程事实与下一步行动各自保持清晰。</p></div><div className="flex gap-2"><Btn kind="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={refresh}>刷新</Btn><Btn size="sm" icon={<Plus size={14} />} onClick={() => setOpportunityEditor(true)}>添加机会</Btn></div></header>
    <div className="grid min-h-[520px] gap-5 lg:grid-cols-[330px_minmax(0,1fr)]">
      <aside className="rounded-xl border border-stone-200 bg-white shadow-xs">
        <div className="border-b border-stone-100 px-4 py-3 text-sm font-semibold text-stone-800">岗位机会 · {jobs.length}</div>
        {jobs.length === 0 ? <EmptyState icon={<BriefcaseBusiness size={30} />} title="还没有跟进的岗位" action={<Btn size="sm" onClick={() => setOpportunityEditor(true)}>添加第一个机会</Btn>} /> : <div className="divide-y divide-stone-100">{jobs.map((job) => <button key={job.id} onClick={() => setSelectedId(job.id)} className={`w-full px-4 py-3 text-left transition ${effectiveSelectedId === job.id ? 'bg-primary-50' : 'hover:bg-stone-50'}`}><div className="flex items-start justify-between gap-2"><div className="min-w-0"><div className="truncate text-sm font-medium text-stone-800">{job.company_name}</div><div className="mt-0.5 truncate text-xs text-stone-600">{job.job_title}</div></div><Pill tone={jobTone(job)}>{job.outcome ? outcomeLabels[job.outcome] : jobPhaseLabels[job.phase]}</Pill></div><div className="mt-2 flex items-center justify-between text-[11px] text-stone-400"><span className="truncate">{job.current_step}</span><ArrowRight size={12} /></div></button>)}</div>}
      </aside>
      <main className="min-w-0 space-y-5">
        {!selected ? <div className="rounded-xl border border-stone-200 bg-white"><EmptyState icon={<CircleDot size={30} />} title="选择一个岗位查看进程" /></div> : <>
          <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold text-stone-800">{selected.company_name} · {selected.job_title}</h2><Pill tone={jobTone(selected)}>{selected.outcome ? outcomeLabels[selected.outcome] : jobPhaseLabels[selected.phase]}</Pill></div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-stone-500">{selected.location && <span>{selected.location}</span>}{selected.team && <span>{selected.team}</span>}<span>当前：{selected.current_step}</span>{selected.source_url && <a className="inline-flex items-center gap-1 text-primary-700 hover:underline" href={selected.source_url} target="_blank" rel="noreferrer">岗位原页 <ExternalLink size={11} /></a>}</div>
                <div className="mt-3 flex flex-wrap items-center gap-2" aria-label="关联求职方向">
                  <span className="text-xs text-stone-500">求职方向：</span>
                  {selected.direction_links.length === 0
                    ? <span className="text-xs text-stone-400">未关联</span>
                    : selected.direction_links.map((link) => <Pill key={link.career_profile_direction_id} tone="neutral">{directionsById.get(link.career_profile_direction_id)?.label ?? '已归档方向'}</Pill>)}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Link to={copilotObjectHandoffHref('job_opportunity', selected.id, `${selected.company_name} · ${selected.job_title}`)}><Btn kind="outline" size="sm" icon={<Bot size={14} />}>询问 Copilot</Btn></Link>
                {!selected.outcome && <Btn kind="outline" size="sm" onClick={() => setDirectionEditor(true)}>关联求职方向</Btn>}
                {!selected.outcome && <Btn size="sm" icon={<Plus size={14} />} onClick={() => setEventEditor(true)}>记录进展</Btn>}
                <Link to={`/career-process/${encodeURIComponent(selected.id)}/offer`}><Btn kind="outline" size="sm" icon={<FileText size={14} />}>Offer 条款</Btn></Link>
              </div>
            </div>
          </section>
          <section className="rounded-xl border border-stone-200 bg-white shadow-xs"><div className="flex items-center gap-2 border-b border-stone-100 px-5 py-4"><History size={16} className="text-stone-500" /><h2 className="font-semibold text-stone-800">流程时间线</h2>{eventsQuery.isFetching && <Spinner size={13} className="text-stone-400" />}</div>{eventsQuery.data?.length ? <div className="divide-y divide-stone-100">{eventsQuery.data.map((event) => <article key={event.id} className="flex gap-3 px-5 py-4"><div className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${event.operation === 'retract' ? 'bg-stone-300' : 'bg-primary-500'}`} /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="text-sm font-medium text-stone-800">{event.kind === 'retraction' ? '更正旧记录' : eventLabels[event.kind]}</span><span className="text-[11px] text-stone-400">#{event.sequence} · {displayDate(event.occurred_at)}</span></div><p className="mt-1 text-sm leading-relaxed text-stone-600">{event.description}</p>{event.step_summary && <p className="mt-1 text-xs text-primary-700">阶段：{event.step_summary}</p>}</div>{event.operation === 'assert' && !selected.outcome && <button className="rounded p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700" onClick={() => { setCorrectingEvent(event); setEventEditor(true); }} aria-label={`更正第 ${event.sequence} 条流程记录`}><Pencil size={14} /></button>}</article>)}</div> : <EmptyState icon={<History size={28} />} title="暂无流程记录" description="新机会的第一条跟进记录会显示在这里。" />}</section>
        </>}
      </main>
    </div>
    <section className="mt-6"><div className="mb-3 flex items-center justify-between"><div><h2 className="font-semibold text-stone-800">下一步行动</h2><p className="mt-0.5 text-xs text-stone-500">跨岗位统一查看，但每条行动仍可明确关联岗位。</p></div><Btn size="sm" icon={<Plus size={14} />} onClick={() => setActionEditor(true)}>添加行动</Btn></div>{activeActions.length ? <div className="grid gap-3 md:grid-cols-2">{activeActions.map((action) => <ActionCard key={action.id} action={action} job={jobs.find((job) => job.id === action.job_opportunity_id)} busy={busy} onTransition={(transition) => run(() => transitionNextAction(action, transition), transition === 'complete' ? '行动已完成' : '行动状态已更新')} />)}</div> : <div className="rounded-xl border border-stone-200 bg-white"><EmptyState icon={<CalendarClock size={30} />} title="当前没有待办行动" /></div>}</section>

    {opportunityEditor && <OpportunityEditor open busy={busy} directions={directions} onClose={() => setOpportunityEditor(false)} onSave={async (form, directionIds) => { if (!form.occurred_at) { toast.warn('请填写发生时间'); return; } const sourceIdentity = `ui:${crypto.randomUUID()}`; const ok = await run(() => createJobOpportunity({ company_name: form.company_name.trim(), job_title: form.job_title.trim(), entry_reason: form.entry_reason as 'explicit_tracking' | 'targeted_preparation' | 'user_confirmed_application', occurred_at: isoFromLocal(form.occurred_at), source_kind: 'user_assertion', source_identity: sourceIdentity, source_description: form.source_description.trim(), location: form.location.trim() || undefined, team: form.team.trim() || undefined, source_url: form.source_url.trim() || undefined, idempotency_key: sourceIdentity, directions: directionIds.map((directionId) => ({ direction_id: directionId, match_reason: `用户在创建岗位时明确关联到“${directionsById.get(directionId)?.label ?? directionId}”方向` })) }), '求职机会已加入跟进'); if (ok) setOpportunityEditor(false); }} />}
    {directionEditor && selected && <DirectionEditor key={`${selected.id}:${selected.direction_version}`} open busy={busy} opportunity={selected} directions={directions} onClose={() => setDirectionEditor(false)} onSave={async (directionIds) => { const existingById = new Map(selected.direction_links.map((link) => [link.career_profile_direction_id, link])); const ok = await run(() => replaceJobOpportunityDirections({ opportunityId: selected.id, expectedVersion: selected.direction_version, sourceIdentity: `ui:${crypto.randomUUID()}`, directions: directionIds.map((directionId) => ({ direction_id: directionId, match_reason: existingById.get(directionId)?.match_reason ?? `用户明确关联到“${directionsById.get(directionId)?.label ?? directionId}”方向` })) }), '求职方向关联已更新'); if (ok) setDirectionEditor(false); }} />}
    {eventEditor && selected && <EventEditor key={correctingEvent?.id ?? 'append'} open busy={busy} initial={correctingEvent} onClose={() => { setEventEditor(false); setCorrectingEvent(null); }} onSave={async (form) => { if (!form.occurred_at) { toast.warn('请填写发生时间'); return; } const key = crypto.randomUUID(); const common = { opportunityId: selected.id, kind: form.kind as ProcessEventKind, occurredAt: isoFromLocal(form.occurred_at), description: form.description.trim(), stepSummary: form.step_summary.trim() || undefined, sourceIdentity: `ui:${key}`, idempotencyKey: key }; const command = correctingEvent ? correctProcessEvent({ ...common, eventId: correctingEvent.id }) : appendProcessEvent(common); const ok = await run(() => command, correctingEvent ? '流程更正已追加' : '流程进展已记录'); if (ok) { setEventEditor(false); setCorrectingEvent(null); } }} />}
    {actionEditor && <ActionEditor open busy={busy} opportunities={jobs} selectedOpportunityId={effectiveSelectedId} onClose={() => setActionEditor(false)} onSave={async (form) => { const key = crypto.randomUUID(); const timeKind = form.time_kind as NextActionTimeKind; if (timeKind === 'deadline' && !form.due_at) { toast.warn('请填写截止时间'); return; } if (timeKind === 'fixed' && !form.starts_at) { toast.warn('请填写开始时间'); return; } if (timeKind !== 'flexible' && (!form.original_time_text.trim() || !form.source_timezone.trim())) { toast.warn('请保留原始时间表达和时区'); return; } if (timeKind === 'fixed' && form.ends_at && new Date(form.ends_at) < new Date(form.starts_at)) { toast.warn('结束时间不能早于开始时间'); return; } const ok = await run(() => createNextAction({ content: form.content.trim(), status: form.status as 'suggested' | 'planned', time_kind: timeKind, source_kind: 'user_request', source_identity: `ui:${key}`, job_opportunity_id: form.job_opportunity_id || undefined, starts_at: form.starts_at ? isoFromLocal(form.starts_at) : undefined, ends_at: form.ends_at ? isoFromLocal(form.ends_at) : undefined, due_at: form.due_at ? isoFromLocal(form.due_at) : undefined, original_time_text: timeKind === 'flexible' ? undefined : form.original_time_text.trim(), source_timezone: timeKind === 'flexible' ? undefined : form.source_timezone.trim(), idempotency_key: key }), '下一步行动已保存'); if (ok) setActionEditor(false); }} />}
  </div>;
}
