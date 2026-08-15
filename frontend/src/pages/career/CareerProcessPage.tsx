import { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  BriefcaseBusiness,
  CheckCircle2,
  CircleDot,
  ExternalLink,
  FileText,
  History,
  GitMerge,
  Pencil,
  Plus,
  RefreshCw,
  Bot,
} from 'lucide-react';
import {
  appendProcessEvent,
  correctProcessEvent,
  createJobOpportunity,
  createJobDescriptionSnapshot,
  createNextAction,
  editNextAction,
  listJobOpportunities,
  listJobDescriptionSnapshots,
  listJobOpportunityMergeCandidates,
  listJobOpportunityMerges,
  listNextActions,
  listProcessEvents,
  replaceJobOpportunityDirections,
  mergeJobOpportunities,
  retractJobOpportunityMerge,
  transitionNextAction,
} from '@/api/careerProcess';
import { listCurrentOffers } from '@/api/offers';
import { listArtifacts } from '@/api/artifacts';
import { listInterviewRecords } from '@/api/interview';
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
  JobOpportunityMergeCandidate,
  NextAction,
  NextActionStatus,
  NextActionTimeKind,
  Artifact,
  OfferListItem,
  ProcessEvent,
  ProcessEventKind,
  JobDescriptionSnapshot,
} from '@/types/career';
import type { InterviewRecordListItem } from '@/types/api';
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
    application_channel: initial?.kind === 'application_submitted'
      ? String(initial.analysis_context_json.channel ?? '')
      : '',
  }));
  const update = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return <Modal open={open} onClose={onClose} title={initial ? '更正流程事实' : '记录进展'} width={620} footer={<><Btn kind="ghost" onClick={onClose}>取消</Btn><Btn loading={busy} disabled={!form.description.trim()} onClick={() => onSave(form)}>{initial ? '追加更正记录' : '保存进展'}</Btn></>}>
    <div className="space-y-4">
      <FormItem label="进展类型"><SelectInput value={form.kind} onChange={(e) => update('kind', e.target.value)}>{Object.entries(eventLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</SelectInput></FormItem>
      <FormItem label="发生时间"><TextInput type="datetime-local" value={form.occurred_at} onChange={(e) => update('occurred_at', e.target.value)} /></FormItem>
      {form.kind === 'application_submitted' && <FormItem label="实际投递渠道" hint="例如官网、内推、招聘平台；用于历史漏斗，不等同于岗位发现来源"><TextInput value={form.application_channel} onChange={(e) => update('application_channel', e.target.value)} /></FormItem>}
      <FormItem label="简短阶段说明"><TextInput value={form.step_summary} onChange={(e) => update('step_summary', e.target.value)} placeholder="例如：一面结束，等待结果" /></FormItem>
      <FormItem label="真实情况"><TextArea rows={4} value={form.description} onChange={(e) => update('description', e.target.value)} placeholder="写下已发生的事实" /></FormItem>
    </div>
  </Modal>;
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
    starts_at: initial?.starts_at ? localDateTimeFromIso(initial.starts_at) : '', ends_at: initial?.ends_at ? localDateTimeFromIso(initial.ends_at) : '', due_at: initial?.due_at ? localDateTimeFromIso(initial.due_at) : '', original_time_text: initial?.original_time_text ?? '', source_timezone: initial?.source_timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
    reminder_at: initial?.reminder_at ? localDateTimeFromIso(initial.reminder_at) : '',
  }));
  const update = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return <Modal open={open} onClose={onClose} title={initial ? '编辑下一步行动' : '添加下一步行动'} width={720} footer={<><Btn kind="ghost" onClick={onClose}>取消</Btn><Btn loading={busy} disabled={!form.content.trim()} onClick={() => onSave(form)}>保存行动</Btn></>}>
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="sm:col-span-2"><FormItem label="要做什么"><TextArea autoFocus rows={3} value={form.content} onChange={(e) => update('content', e.target.value)} /></FormItem></div>
      <FormItem label="关联机会"><SelectInput value={form.job_opportunity_id} onChange={(e) => update('job_opportunity_id', e.target.value)}><option value="">不关联具体机会</option>{opportunities.filter((job) => !job.outcome).map((job) => <option key={job.id} value={job.id}>{job.company_name} · {job.job_title}</option>)}</SelectInput></FormItem>
      {!initial && <FormItem label="状态"><SelectInput value={form.status} disabled><option value="planned">已计划（用户直接创建）</option></SelectInput></FormItem>}
      <FormItem label="关联面试"><SelectInput value={form.interview_record_id} onChange={(e) => update('interview_record_id', e.target.value)}><option value="">不关联面试</option>{interviews.map((record) => <option key={record.id} value={record.id}>{record.title}</option>)}</SelectInput></FormItem>
      <FormItem label="关联 Offer"><SelectInput value={form.offer_id} onChange={(e) => update('offer_id', e.target.value)}><option value="">不关联 Offer</option>{offers.map((entry) => <option key={entry.offer.id} value={entry.offer.id}>{entry.company_name} · {entry.job_title}</option>)}</SelectInput></FormItem>
      <FormItem label="关联材料"><SelectInput value={form.artifact_id} onChange={(e) => update('artifact_id', e.target.value)}><option value="">不关联材料</option>{artifacts.map((artifact) => <option key={artifact.id} value={artifact.id}>{artifact.current_version.title}</option>)}</SelectInput></FormItem>
      <FormItem label="时间类型"><SelectInput value={form.time_kind} onChange={(e) => update('time_kind', e.target.value)}><option value="flexible">灵活安排</option><option value="deadline">截止时间</option><option value="fixed">固定时间</option></SelectInput></FormItem>
      {form.time_kind === 'deadline' && <FormItem label="截止时间"><TextInput type="datetime-local" value={form.due_at} onChange={(e) => update('due_at', e.target.value)} /></FormItem>}
      {form.time_kind === 'fixed' && <><FormItem label="开始时间"><TextInput type="datetime-local" value={form.starts_at} onChange={(e) => update('starts_at', e.target.value)} /></FormItem><FormItem label="结束时间"><TextInput type="datetime-local" value={form.ends_at} onChange={(e) => update('ends_at', e.target.value)} /></FormItem></>}
      {form.time_kind !== 'flexible' && <><FormItem label="原始时间表达"><TextInput value={form.original_time_text} onChange={(e) => update('original_time_text', e.target.value)} placeholder="例如：周五 18:00 前" /></FormItem><FormItem label="时区"><TextInput value={form.source_timezone} onChange={(e) => update('source_timezone', e.target.value)} /></FormItem></>}
      {form.status === 'planned' && <FormItem label="应用内提醒时间" hint="留空则不通知；建议设置在行动时间之前"><TextInput type="datetime-local" value={form.reminder_at} onChange={(e) => update('reminder_at', e.target.value)} /></FormItem>}
    </div>
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

function JobDescriptionPanel({ opportunityId, sourceUrl }: { opportunityId: string; sourceUrl: string | null }) {
  const [url, setUrl] = useState(sourceUrl ?? '');
  const [content, setContent] = useState('');
  const [snapshots, setSnapshots] = useState<JobDescriptionSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void listJobDescriptionSnapshots(opportunityId).then(setSnapshots).catch((reason: unknown) => {
      setSnapshots([]);
      setError(extractErr(reason, '读取 JD 快照失败'));
    });
  }, [opportunityId]);

  const latest = snapshots.at(-1) ?? null;
  const save = async () => {
    if (!url.trim() || !content.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const operationKey = crypto.randomUUID();
      const snapshot = await createJobDescriptionSnapshot(opportunityId, {
        source_kind: 'typed_product_ui',
        source_identity: `product-ui:${operationKey}`,
        source_version: '1',
        original_url: url.trim(),
        observed_at: new Date().toISOString(),
        provider: 'product_ui',
        canonical_content: content.trim(),
        idempotency_key: operationKey,
      });
      setSnapshots((current) => [...current, snapshot]);
      setContent('');
      toast.success('JD 快照已保存');
    } catch (reason) {
      setError(extractErr(reason, '保存 JD 快照失败'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section aria-label="岗位 JD 快照" className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
      <div className="flex items-start justify-between gap-3">
        <div><h2 className="font-semibold text-stone-800">岗位 JD 快照</h2><p className="mt-1 text-xs text-stone-500">追加保存观察时点，已投递事件会冻结当时版本。</p></div>
        <Pill tone="neutral">{snapshots.length} 个版本</Pill>
      </div>
      <div className="mt-4 grid gap-3">
        <FormItem label="原始岗位链接"><TextInput value={url} onChange={(event) => setUrl(event.target.value)} /></FormItem>
        <FormItem label="JD 正文"><TextArea value={content} onChange={(event) => setContent(event.target.value)} rows={6} /></FormItem>
        <div><Btn size="sm" loading={saving} disabled={!url.trim() || !content.trim()} onClick={() => { void save(); }}>保存新快照</Btn></div>
      </div>
      {error && <p role="alert" className="mt-3 text-xs text-danger-600">{error}</p>}
      {latest && <article className="mt-4 rounded-lg bg-stone-50 p-3"><div className="text-xs font-medium text-stone-700">当前版本 v{latest.version} · {displayDate(latest.observed_at)}</div><p className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-stone-600">{latest.canonical_content}</p></article>}
    </section>
  );
}

export function CareerProcessPage() {
  const queryClient = useQueryClient();
  const jobsQuery = useQuery({ queryKey: ['job-opportunities'], queryFn: () => listJobOpportunities(true) });
  const mergeCandidatesQuery = useQuery({ queryKey: ['job-opportunity-merge-candidates'], queryFn: listJobOpportunityMergeCandidates });
  const mergesQuery = useQuery({ queryKey: ['job-opportunity-merges'], queryFn: () => listJobOpportunityMerges(false) });
  const actionsQuery = useQuery({ queryKey: ['next-actions'], queryFn: () => listNextActions() });
  const profileQuery = useQuery({ queryKey: ['career-profile'], queryFn: getCareerProfile, retry: false });
  const interviewsQuery = useQuery({ queryKey: ['interview-records', 'action-link'], queryFn: () => listInterviewRecords(0, 100) });
  const offersQuery = useQuery({ queryKey: ['current-offers', 'action-link'], queryFn: listCurrentOffers });
  const artifactsQuery = useQuery({ queryKey: ['artifacts', 'action-link'], queryFn: () => listArtifacts(false, 100) });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [opportunityEditor, setOpportunityEditor] = useState(false);
  const [directionEditor, setDirectionEditor] = useState(false);
  const [mergeReviewOpen, setMergeReviewOpen] = useState(false);
  const [eventEditor, setEventEditor] = useState(false);
  const [correctingEvent, setCorrectingEvent] = useState<ProcessEvent | null>(null);
  const [actionEditor, setActionEditor] = useState(false);
  const [editingAction, setEditingAction] = useState<NextAction | null>(null);
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
      queryClient.invalidateQueries({ queryKey: ['job-opportunity-merge-candidates'] }),
      queryClient.invalidateQueries({ queryKey: ['job-opportunity-merges'] }),
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

  if (jobsQuery.isLoading || actionsQuery.isLoading) {
    return (
      <div className="flex items-center justify-center h-64 gap-2 text-sm text-slate-400">
        <Spinner size={18} />
        <span>正在载入求职进程看板…</span>
      </div>
    );
  }

  const inProcessCount = jobs.filter((j) => j.phase === 'in_process').length;
  const offerCount = jobs.filter((j) => j.phase === 'offer' || j.outcome === 'accepted').length;

  return (
    <div className="mx-auto max-w-7xl p-4 md:p-8 space-y-6 animate-in fade-in duration-200">
      {/* Header with Stage Metrics and Action Buttons */}
      <header className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-200/80">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold text-slate-900 tracking-tight">求职进程看板</h1>
            <div className="flex items-center gap-1.5">
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-600 font-semibold">
                全部 {jobs.length}
              </span>
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-blue-50 text-blue-700 font-semibold border border-blue-100">
                推进中 {inProcessCount}
              </span>
              {offerCount > 0 && (
                <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 font-semibold border border-emerald-100">
                  Offer {offerCount}
                </span>
              )}
            </div>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            全生命周期跟踪投递机会、流程事实记录与下一步待办行动。
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Btn kind="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={refresh}>
            刷新
          </Btn>
          <Btn kind="outline" size="sm" icon={<GitMerge size={14} />} onClick={() => setMergeReviewOpen(true)}>
            检查重复{mergeCandidatesQuery.data?.length ? ` · ${mergeCandidatesQuery.data.length}` : ''}
          </Btn>
          <Btn size="sm" icon={<Plus size={14} />} onClick={() => setOpportunityEditor(true)}>
            添加机会
          </Btn>
        </div>
      </header>

      {/* Main Content Area */}
      {jobs.length === 0 ? (
        <div className="p-12 text-center bg-white/90 backdrop-blur-md rounded-3xl border border-slate-200/90 shadow-sm max-w-2xl mx-auto space-y-4 my-8">
          <div className="w-12 h-12 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center mx-auto shadow-xs">
            <BriefcaseBusiness size={24} />
          </div>
          <div>
            <h3 className="text-lg font-bold text-slate-800">还没有跟进的求职机会</h3>
            <p className="text-xs text-slate-500 max-w-md mx-auto mt-1 leading-relaxed">
              记录你正在投递或面试的目标岗位，Copilot 将自动串联 JD 分析、面试复盘与下一步待办行动。
            </p>
          </div>
          <Btn kind="primary" size="md" icon={<Plus size={15} />} onClick={() => setOpportunityEditor(true)} className="rounded-full shadow-xs">
            添加第一个机会
          </Btn>
        </div>
      ) : (
        <div className="grid min-h-[520px] gap-6 lg:grid-cols-[330px_minmax(0,1fr)]">
          {/* Left Opportunity Column */}
          <aside className="rounded-3xl border border-slate-200/90 bg-white/90 backdrop-blur-md shadow-2xs overflow-hidden flex flex-col">
            <div className="border-b border-slate-100 px-4 py-3 text-xs font-bold text-slate-500 uppercase tracking-wider">
              岗位机会清单 ({jobs.length})
            </div>
            <div className="divide-y divide-slate-100 flex-1 overflow-y-auto">
              {jobs.map((job) => (
                <button
                  key={job.id}
                  onClick={() => setSelectedId(job.id)}
                  className={`w-full px-4 py-3.5 text-left transition-all cursor-pointer ${
                    effectiveSelectedId === job.id
                      ? 'bg-blue-50/80 border-l-4 border-blue-600 shadow-2xs'
                      : 'hover:bg-slate-50/70 border-l-4 border-transparent'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-bold text-slate-800">{job.company_name}</div>
                      <div className="mt-0.5 truncate text-xs text-slate-500">{job.job_title}</div>
                    </div>
                    <Pill tone={jobTone(job)}>
                      {job.outcome ? outcomeLabels[job.outcome] : jobPhaseLabels[job.phase]}
                    </Pill>
                  </div>
                  <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400">
                    <span className="truncate">{job.current_step}</span>
                    <ArrowRight size={12} className="text-slate-400" />
                  </div>
                </button>
              ))}
            </div>
          </aside>

          {/* Right Detail Pane */}
          <main className="min-w-0 space-y-5">
            {!selected ? (
              <div className="rounded-3xl border border-slate-200/90 bg-white/80 p-8 text-center text-slate-400">
                <CircleDot size={28} className="mx-auto mb-2 text-slate-300" />
                <div className="text-xs font-semibold text-slate-600">选择左侧岗位查看详细进程与时间线</div>
              </div>
            ) : (
              <>
                <section className="rounded-3xl border border-slate-200/90 bg-white p-5 shadow-2xs">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-lg font-bold text-slate-900 tracking-tight">
                          {selected.company_name} · {selected.job_title}
                        </h2>
                        <Pill tone={jobTone(selected)}>
                          {selected.outcome ? outcomeLabels[selected.outcome] : jobPhaseLabels[selected.phase]}
                        </Pill>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                        {selected.location && <span>{selected.location}</span>}
                        {selected.team && <span>{selected.team}</span>}
                        <span>当前阶段：{selected.current_step}</span>
                        {selected.source_url && (
                          <a
                            className="inline-flex items-center gap-1 text-blue-600 hover:underline"
                            href={selected.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            岗位原页 <ExternalLink size={11} />
                          </a>
                        )}
                      </div>
                      <div className="mt-3 flex flex-wrap items-center gap-2" aria-label="关联求职方向">
                        <span className="text-xs text-slate-500">求职方向：</span>
                        {selected.direction_links.length === 0 ? (
                          <span className="text-xs text-slate-400">未关联</span>
                        ) : (
                          selected.direction_links.map((link) => (
                            <Pill key={link.career_profile_direction_id} tone="neutral">
                              {directionsById.get(link.career_profile_direction_id)?.label ?? '已归档方向'}
                            </Pill>
                          ))
                        )}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Link
                        to={copilotObjectHandoffHref(
                          'job_opportunity',
                          selected.id,
                          `${selected.company_name} · ${selected.job_title}`,
                        )}
                      >
                        <Btn kind="outline" size="sm" icon={<Bot size={14} />}>
                          询问 Copilot
                        </Btn>
                      </Link>
                      {!selected.outcome && (
                        <Btn kind="outline" size="sm" onClick={() => setDirectionEditor(true)}>
                          关联求职方向
                        </Btn>
                      )}
                      {!selected.outcome && (
                        <Btn size="sm" icon={<Plus size={14} />} onClick={() => setEventEditor(true)}>
                          记录进展
                        </Btn>
                      )}
                      <Link to={`/career-process/${encodeURIComponent(selected.id)}/offer`}>
                        <Btn kind="outline" size="sm" icon={<FileText size={14} />}>
                          Offer 条款
                        </Btn>
                      </Link>
                    </div>
                  </div>
                </section>

                <JobDescriptionPanel
                  key={selected.id}
                  opportunityId={selected.id}
                  sourceUrl={selected.source_url}
                />

                <section className="rounded-3xl border border-slate-200/90 bg-white shadow-2xs overflow-hidden">
                  <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-4">
                    <History size={16} className="text-slate-500" />
                    <h2 className="font-bold text-slate-800 text-sm">流程时间线</h2>
                    {eventsQuery.isFetching && <Spinner size={13} className="text-slate-400" />}
                  </div>
                  {eventsQuery.data?.length ? (
                    <div className="divide-y divide-slate-100">
                      {eventsQuery.data.map((event) => (
                        <article key={event.id} className="flex gap-3.5 px-5 py-4 hover:bg-slate-50/50 transition-colors">
                          <div
                            className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${
                              event.operation === 'retract' ? 'bg-slate-300' : 'bg-blue-600'
                            }`}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-semibold text-slate-800">
                                {event.kind === 'retraction' ? '更正旧记录' : eventLabels[event.kind]}
                              </span>
                              <span className="text-[11px] text-slate-400">
                                #{event.sequence} · {displayDate(event.occurred_at)}
                              </span>
                            </div>
                            <p className="mt-1 text-xs leading-relaxed text-slate-600">
                              {event.description}
                            </p>
                            {event.step_summary && (
                              <p className="mt-1 text-xs font-medium text-blue-700">
                                阶段：{event.step_summary}
                              </p>
                            )}
                          </div>
                          {event.operation === 'assert' && !selected.outcome && (
                            <button
                              className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
                              onClick={() => {
                                setCorrectingEvent(event);
                                setEventEditor(true);
                              }}
                              aria-label={`更正第 ${event.sequence} 条流程记录`}
                            >
                              <Pencil size={14} />
                            </button>
                          )}
                        </article>
                      ))}
                    </div>
                  ) : (
                    <EmptyState
                      icon={<History size={28} />}
                      title="暂无流程记录"
                      description="新机会的第一条跟进记录会显示在这里。"
                    />
                  )}
                </section>
              </>
            )}
          </main>
        </div>
      )}

      {/* Next Actions Section */}
      <section className="pt-2">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-bold text-slate-800">下一步待办行动</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              跨岗位统一跟进，支持关联特定岗位、面试复盘或 Offer 沟通。
            </p>
          </div>
          <Btn
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => {
              setEditingAction(null);
              setActionEditor(true);
            }}
          >
            添加行动
          </Btn>
        </div>
        {activeActions.length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {activeActions.map((action) => (
              <ActionCard
                key={action.id}
                action={action}
                job={jobs.find((job) => job.id === action.job_opportunity_id)}
                busy={busy}
                onEdit={() => {
                  setEditingAction(action);
                  setActionEditor(true);
                }}
                onTransition={(transition) =>
                  run(
                    () => transitionNextAction(action, transition),
                    transition === 'complete' ? '行动已完成' : '行动状态已更新',
                  )
                }
              />
            ))}
          </div>
        ) : (
          <div className="rounded-2xl border border-slate-200/80 bg-white/60 p-4 text-center text-xs text-slate-400">
            当前没有待办行动，点击右上角「添加行动」即可新建计划。
          </div>
        )}
      </section>

      {opportunityEditor && (
        <OpportunityEditor
          open
          busy={busy}
          directions={directions}
          onClose={() => setOpportunityEditor(false)}
          onSave={async (form, directionIds) => {
            if (!form.occurred_at) {
              toast.warn('请填写发生时间');
              return;
            }
            const sourceIdentity = `ui:${crypto.randomUUID()}`;
            const ok = await run(
              () =>
                createJobOpportunity({
                  company_name: form.company_name.trim(),
                  job_title: form.job_title.trim(),
                  entry_reason: form.entry_reason as
                    | 'explicit_tracking'
                    | 'targeted_preparation'
                    | 'user_confirmed_application',
                  occurred_at: isoFromLocal(form.occurred_at),
                  source_kind: 'user_assertion',
                  source_identity: sourceIdentity,
                  source_description: form.source_description.trim(),
                  location: form.location.trim() || undefined,
                  team: form.team.trim() || undefined,
                  source_url: form.source_url.trim() || undefined,
                  idempotency_key: sourceIdentity,
                  directions: directionIds.map((directionId) => ({
                    direction_id: directionId,
                    match_reason: `用户在创建岗位时明确关联到“${
                      directionsById.get(directionId)?.label ?? directionId
                    }”方向`,
                  })),
                }),
              '求职机会已加入跟进',
            );
            if (ok) setOpportunityEditor(false);
          }}
        />
      )}

      <Modal
        open={mergeReviewOpen}
        onClose={() => setMergeReviewOpen(false)}
        title="核对疑似重复岗位"
        width={760}
        footer={
          <Btn kind="ghost" onClick={() => setMergeReviewOpen(false)}>
            关闭
          </Btn>
        }
      >
        <div className="space-y-5">
          <p className="text-sm leading-relaxed text-slate-600">
            系统只提示候选，不会自动合并。确认后双方外部标识和流程历史仍分别保留；误合并可随时撤销。
          </p>
          {(mergesQuery.data ?? []).length > 0 && (
            <section>
              <h3 className="text-sm font-semibold text-slate-800">当前合并关系</h3>
              <div className="mt-2 space-y-2">
                {(mergesQuery.data ?? []).map((merge) => {
                  const duplicate = jobs.find((job) => job.id === merge.duplicate_opportunity_id);
                  const canonical = jobs.find((job) => job.id === merge.canonical_opportunity_id);
                  return (
                    <div
                      key={merge.id}
                      className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 p-3"
                    >
                      <div className="text-sm text-slate-700">
                        <span className="font-medium">
                          {duplicate
                            ? `${duplicate.company_name} · ${duplicate.job_title}`
                            : merge.duplicate_opportunity_id}
                        </span>
                        <span className="mx-2 text-slate-400">→</span>
                        <span>
                          {canonical
                            ? `${canonical.company_name} · ${canonical.job_title}`
                            : merge.canonical_opportunity_id}
                        </span>
                        <p className="mt-1 text-xs text-slate-500">{merge.reason}</p>
                      </div>
                      <Btn
                        kind="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                          run(
                            () =>
                              retractJobOpportunityMerge({
                                merge,
                                reason: '用户撤销岗位合并关系',
                                operationKey: crypto.randomUUID(),
                              }),
                            '岗位合并已撤销',
                          )
                        }
                      >
                        撤销合并
                      </Btn>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          <section>
            <h3 className="text-sm font-semibold text-slate-800">待核对候选</h3>
            {mergeCandidatesQuery.isLoading ? (
              <div className="mt-3 flex items-center gap-2 text-sm text-slate-500">
                <Spinner size={14} />正在检查…
              </div>
            ) : (mergeCandidatesQuery.data ?? []).length ? (
              <div className="mt-2 space-y-3">
                {(mergeCandidatesQuery.data ?? []).map((candidate: JobOpportunityMergeCandidate) => {
                  const duplicate = jobs.find(
                    (job) => job.id === candidate.duplicate_opportunity_id,
                  );
                  const canonical = jobs.find(
                    (job) => job.id === candidate.canonical_opportunity_id,
                  );
                  return (
                    <div
                      key={`${candidate.duplicate_opportunity_id}:${candidate.canonical_opportunity_id}`}
                      className="rounded-2xl border border-amber-200 bg-amber-50/50 p-3"
                    >
                      <div className="text-sm font-medium text-slate-800">
                        {duplicate?.company_name} · {duplicate?.job_title}
                        <span className="mx-2 text-slate-400">与</span>
                        {canonical?.company_name} · {canonical?.job_title}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {candidate.reasons.map((reason) => (
                          <Pill key={reason} tone="warn">
                            {reason}
                          </Pill>
                        ))}
                      </div>
                      <div className="mt-3">
                        <Btn
                          size="sm"
                          disabled={busy}
                          onClick={() =>
                            run(
                              () =>
                                mergeJobOpportunities({
                                  duplicateOpportunityId: candidate.duplicate_opportunity_id,
                                  canonicalOpportunityId: candidate.canonical_opportunity_id,
                                  reason: `用户核对候选后确认重复：${candidate.reasons.join(', ')}`,
                                  operationKey: crypto.randomUUID(),
                                }),
                              '重复岗位已建立可撤销合并关系',
                            )
                          }
                        >
                          确认合并
                        </Btn>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="mt-2 text-sm text-slate-500">没有待核对的重复候选。</p>
            )}
          </section>
        </div>
      </Modal>

      {directionEditor && selected && (
        <DirectionEditor
          key={`${selected.id}:${selected.direction_version}`}
          open
          busy={busy}
          opportunity={selected}
          directions={directions}
          onClose={() => setDirectionEditor(false)}
          onSave={async (directionIds) => {
            const existingById = new Map(
              selected.direction_links.map((link) => [link.career_profile_direction_id, link]),
            );
            const ok = await run(
              () =>
                replaceJobOpportunityDirections({
                  opportunityId: selected.id,
                  expectedVersion: selected.direction_version,
                  sourceIdentity: `ui:${crypto.randomUUID()}`,
                  directions: directionIds.map((directionId) => ({
                    direction_id: directionId,
                    match_reason:
                      existingById.get(directionId)?.match_reason ??
                      `用户明确关联到“${directionsById.get(directionId)?.label ?? directionId}”方向`,
                  })),
                }),
              '求职方向关联已更新',
            );
            if (ok) setDirectionEditor(false);
          }}
        />
      )}

      {eventEditor && selected && (
        <EventEditor
          key={correctingEvent?.id ?? 'append'}
          open
          busy={busy}
          initial={correctingEvent}
          onClose={() => {
            setEventEditor(false);
            setCorrectingEvent(null);
          }}
          onSave={async (form) => {
            if (!form.occurred_at) {
              toast.warn('请填写发生时间');
              return;
            }
            const key = crypto.randomUUID();
            const common = {
              opportunityId: selected.id,
              kind: form.kind as ProcessEventKind,
              occurredAt: isoFromLocal(form.occurred_at),
              description: form.description.trim(),
              stepSummary: form.step_summary.trim() || undefined,
              applicationChannel:
                form.kind === 'application_submitted'
                  ? form.application_channel.trim() || undefined
                  : undefined,
              sourceIdentity: `ui:${key}`,
              idempotencyKey: key,
            };
            const command = correctingEvent
              ? correctProcessEvent({ ...common, eventId: correctingEvent.id })
              : appendProcessEvent(common);
            const ok = await run(
              () => command,
              correctingEvent ? '流程更正已追加' : '流程进展已记录',
            );
            if (ok) {
              setEventEditor(false);
              setCorrectingEvent(null);
            }
          }}
        />
      )}

      {actionEditor && (
        <ActionEditor
          key={editingAction?.id ?? 'new'}
          open
          busy={busy}
          opportunities={jobs}
          interviews={interviewsQuery.data ?? []}
          offers={offersQuery.data ?? []}
          artifacts={artifactsQuery.data ?? []}
          selectedOpportunityId={effectiveSelectedId}
          initial={editingAction}
          onClose={() => {
            setActionEditor(false);
            setEditingAction(null);
          }}
          onSave={async (form) => {
            const key = crypto.randomUUID();
            const timeKind = form.time_kind as NextActionTimeKind;
            if (timeKind === 'deadline' && !form.due_at) {
              toast.warn('请填写截止时间');
              return;
            }
            if (timeKind === 'fixed' && !form.starts_at) {
              toast.warn('请填写开始时间');
              return;
            }
            if (
              timeKind !== 'flexible' &&
              (!form.original_time_text.trim() || !form.source_timezone.trim())
            ) {
              toast.warn('请保留原始时间表达和时区');
              return;
            }
            if (
              timeKind === 'fixed' &&
              form.ends_at &&
              new Date(form.ends_at) < new Date(form.starts_at)
            ) {
              toast.warn('结束时间不能早于开始时间');
              return;
            }
            const common = {
              content: form.content.trim(),
              time_kind: timeKind,
              job_opportunity_id: form.job_opportunity_id || undefined,
              interview_record_id: form.interview_record_id || undefined,
              offer_id: form.offer_id || undefined,
              artifact_id: form.artifact_id || undefined,
              starts_at: form.starts_at ? isoFromLocal(form.starts_at) : undefined,
              ends_at: form.ends_at ? isoFromLocal(form.ends_at) : undefined,
              due_at: form.due_at ? isoFromLocal(form.due_at) : undefined,
              original_time_text:
                timeKind === 'flexible' ? undefined : form.original_time_text.trim(),
              source_timezone: timeKind === 'flexible' ? undefined : form.source_timezone.trim(),
              reminder_at: form.reminder_at ? isoFromLocal(form.reminder_at) : undefined,
              reminder_channel: form.reminder_at ? ('in_app' as const) : undefined,
            };
            const ok = editingAction
              ? await run(() => editNextAction({ action: editingAction, ...common }), '行动已更新')
              : await run(
                  () =>
                    createNextAction({
                      ...common,
                      status: form.status as 'suggested' | 'planned',
                      source_kind: 'user_request',
                      source_identity: `ui:${key}`,
                      idempotency_key: key,
                    }),
                  '下一步行动已保存',
                );
            if (ok) {
              setActionEditor(false);
              setEditingAction(null);
            }
          }}
        />
      )}
    </div>
  );
}
