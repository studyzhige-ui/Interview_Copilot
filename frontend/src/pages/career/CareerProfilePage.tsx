import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  Award,
  BookOpen,
  BriefcaseBusiness,
  Check,
  CircleUserRound,
  Code2,
  FileQuestion,
  GraduationCap,
  MapPin,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  X,
  Bot,
} from 'lucide-react';
import {
  changeAbilitySignalStatus,
  getCareerProfile,
  listAbilitySignals,
  listCareerProfileDrafts,
  removePersonalFact,
  recomputeInterviewAbilitySignals,
  resolveCareerProfileDraft,
  resolveCareerProfileCandidates,
  saveCareerDirection,
  savePersonalFact,
  setCareerDirectionLifecycle,
} from '@/api/careerProfile';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { Modal } from '@/components/ui/Modal';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import type {
  AbilitySignal,
  CareerProfileDirection,
  ConfirmedPersonalFact,
  DirectionInput,
  DirectionLifecycle,
  PersonalFact,
  CareerProfileCandidateItem,
  FactDraftChange,
  DirectionDraftChange,
} from '@/types/career';
import { csv, displayDate, FormItem, SelectInput, TextArea, TextInput } from './CareerFields';
import { copilotObjectHandoffHref } from '@/lib/copilotObjectReference';

const PROFILE_KEY = ['career-profile'] as const;
const DRAFTS_KEY = ['career-profile-drafts'] as const;
const SIGNALS_KEY = ['ability-signals'] as const;

const lifecycleLabels: Record<DirectionLifecycle, string> = {
  exploring: '探索中',
  active: '当前目标',
  paused: '已暂停',
  archived: '已归档',
};

const lifecycleTone: Record<DirectionLifecycle, 'neutral' | 'primary' | 'success' | 'sand'> = {
  exploring: 'primary',
  active: 'success',
  paused: 'sand',
  archived: 'neutral',
};

const factLabels: Record<PersonalFact['kind'], string> = {
  education: '教育经历',
  experience: '工作 / 实习',
  project: '项目经历',
  skill: '技能',
  achievement: '成果',
  contact: '联系方式',
  location: '所在地',
};

function clean(value: string): string | undefined {
  return value.trim() || undefined;
}

function factTitle(fact: PersonalFact): string {
  switch (fact.kind) {
    case 'education': return `${fact.institution}${fact.degree ? ` · ${fact.degree}` : ''}`;
    case 'experience': return `${fact.organization} · ${fact.role}`;
    case 'project': return fact.name;
    case 'skill': return fact.name;
    case 'achievement': return fact.title;
    case 'contact': return fact.value;
    case 'location': return fact.value;
  }
}

function factDetail(fact: PersonalFact): string {
  switch (fact.kind) {
    case 'education': return [fact.field_of_study, fact.description].filter(Boolean).join(' · ');
    case 'experience': return fact.description ?? '';
    case 'project': return [fact.role, fact.technologies.join('、'), fact.description].filter(Boolean).join(' · ');
    case 'skill': return fact.category ?? '';
    case 'achievement': return fact.description ?? '';
    case 'contact': return fact.channel;
    case 'location': return '';
  }
}

function FactIcon({ kind }: { kind: PersonalFact['kind'] }) {
  const Icon = {
    education: GraduationCap,
    experience: BriefcaseBusiness,
    project: Code2,
    skill: Award,
    achievement: Award,
    contact: CircleUserRound,
    location: MapPin,
  }[kind];
  return <Icon size={17} />;
}

type FactForm = Record<string, string> & { kind: PersonalFact['kind'] };

function factToForm(fact?: PersonalFact, initialKind: PersonalFact['kind'] = 'education'): FactForm {
  if (!fact) return { kind: initialKind };
  const form: FactForm = { kind: fact.kind };
  for (const [key, value] of Object.entries(fact)) {
    form[key] = Array.isArray(value) ? value.join('，') : String(value ?? '');
  }
  return form;
}

function factFromForm(form: FactForm): PersonalFact {
  const dates = { start_date: clean(form.start_date ?? ''), end_date: clean(form.end_date ?? '') };
  switch (form.kind) {
    case 'education':
      return {
        kind: 'education', institution: form.institution.trim(), degree: clean(form.degree ?? ''),
        field_of_study: clean(form.field_of_study ?? ''), description: clean(form.description ?? ''), ...dates,
      };
    case 'experience':
      return {
        kind: 'experience', organization: form.organization.trim(), role: form.role.trim(),
        description: clean(form.description ?? ''), ...dates,
      };
    case 'project':
      return {
        kind: 'project', name: form.name.trim(), role: clean(form.role ?? ''),
        description: clean(form.description ?? ''), technologies: csv(form.technologies ?? ''), ...dates,
      };
    case 'skill':
      return { kind: 'skill', name: form.name.trim(), category: clean(form.category ?? '') };
    case 'achievement':
      return {
        kind: 'achievement', title: form.title.trim(), description: clean(form.description ?? ''),
        occurred_on: clean(form.occurred_on ?? ''),
      };
    case 'contact':
      return {
        kind: 'contact', channel: (form.channel || 'email') as 'email' | 'phone' | 'website' | 'other',
        value: form.value.trim(),
      };
    case 'location': return { kind: 'location', value: form.value.trim() };
  }
}

function FactEditor({
  open,
  initial,
  initialKind,
  busy,
  onClose,
  onSave,
}: {
  open: boolean;
  initial?: ConfirmedPersonalFact;
  initialKind?: PersonalFact['kind'];
  busy: boolean;
  onClose: () => void;
  onSave: (fact: PersonalFact) => void;
}) {
  const [form, setForm] = useState<FactForm>(() => factToForm(initial?.value, initialKind));
  const update = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const required =
    form.kind === 'education' ? form.institution :
    form.kind === 'experience' ? form.organization && form.role :
    form.kind === 'project' || form.kind === 'skill' ? form.name :
    form.kind === 'achievement' ? form.title : form.value;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={initial ? `编辑${factLabels[initial.value.kind]}` : `填写${factLabels[form.kind]}`}
      width={680}
      footer={
        <>
          <Btn kind="ghost" onClick={onClose} disabled={busy}>取消</Btn>
          <Btn onClick={() => onSave(factFromForm(form))} disabled={!required} loading={busy}>保存</Btn>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormItem label="类型">
          <SelectInput
            value={form.kind}
            onChange={(event) => setForm({ kind: event.target.value as PersonalFact['kind'] })}
            disabled={Boolean(initial)}
          >
            {Object.entries(factLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </SelectInput>
        </FormItem>
        {form.kind === 'education' && <>
          <FormItem label="学校 / 机构"><TextInput value={form.institution ?? ''} onChange={(e) => update('institution', e.target.value)} /></FormItem>
          <FormItem label="学历">
            <SelectInput value={form.degree ?? ''} onChange={(e) => update('degree', e.target.value)}>
              <option value="">请选择</option>
              {['高中', '中专', '大专', '本科', '硕士', '博士', '其他'].map((value) => <option key={value} value={value}>{value}</option>)}
            </SelectInput>
          </FormItem>
          <FormItem label="专业"><TextInput value={form.field_of_study ?? ''} onChange={(e) => update('field_of_study', e.target.value)} /></FormItem>
        </>}
        {form.kind === 'experience' && <>
          <FormItem label="组织"><TextInput value={form.organization ?? ''} onChange={(e) => update('organization', e.target.value)} /></FormItem>
          <FormItem label="岗位"><TextInput value={form.role ?? ''} onChange={(e) => update('role', e.target.value)} /></FormItem>
        </>}
        {form.kind === 'project' && <>
          <FormItem label="项目名称"><TextInput value={form.name ?? ''} onChange={(e) => update('name', e.target.value)} /></FormItem>
          <FormItem label="承担角色"><TextInput value={form.role ?? ''} onChange={(e) => update('role', e.target.value)} /></FormItem>
          <FormItem label="技术栈" hint="用逗号分隔"><TextInput value={form.technologies ?? ''} onChange={(e) => update('technologies', e.target.value)} /></FormItem>
        </>}
        {form.kind === 'skill' && <>
          <FormItem label="技能"><TextInput value={form.name ?? ''} onChange={(e) => update('name', e.target.value)} /></FormItem>
          <FormItem label="类别">
            <SelectInput value={form.category ?? ''} onChange={(e) => update('category', e.target.value)}>
              <option value="">请选择</option>
              {['编程语言', 'AI / 数据', '框架与工具', '数据库', '云与 DevOps', '产品与协作', '外语', '其他'].map((value) => <option key={value} value={value}>{value}</option>)}
            </SelectInput>
          </FormItem>
        </>}
        {form.kind === 'achievement' && <>
          <FormItem label="成果名称"><TextInput value={form.title ?? ''} onChange={(e) => update('title', e.target.value)} /></FormItem>
          <FormItem label="发生日期"><TextInput type="date" value={form.occurred_on ?? ''} onChange={(e) => update('occurred_on', e.target.value)} /></FormItem>
        </>}
        {form.kind === 'contact' && <>
          <FormItem label="渠道">
            <SelectInput value={form.channel || 'email'} onChange={(e) => update('channel', e.target.value)}>
              <option value="email">邮箱</option><option value="phone">电话</option>
              <option value="website">网站</option><option value="other">其他</option>
            </SelectInput>
          </FormItem>
          <FormItem label="内容"><TextInput value={form.value ?? ''} onChange={(e) => update('value', e.target.value)} /></FormItem>
        </>}
        {form.kind === 'location' && <FormItem label="所在地"><TextInput value={form.value ?? ''} onChange={(e) => update('value', e.target.value)} /></FormItem>}
        {['education', 'experience', 'project'].includes(form.kind) && <>
          <FormItem label="开始日期"><TextInput type="date" value={form.start_date ?? ''} onChange={(e) => update('start_date', e.target.value)} /></FormItem>
          <FormItem label="结束日期"><TextInput type="date" value={form.end_date ?? ''} onChange={(e) => update('end_date', e.target.value)} /></FormItem>
        </>}
        {['education', 'experience', 'project', 'achievement'].includes(form.kind) && (
          <div className="sm:col-span-2">
            <FormItem label="说明"><TextArea rows={4} value={form.description ?? ''} onChange={(e) => update('description', e.target.value)} /></FormItem>
          </div>
        )}
      </div>
    </Modal>
  );
}

type DirectionForm = Record<string, string>;

function directionToForm(direction?: CareerProfileDirection): DirectionForm {
  return {
    label: direction?.label ?? '',
    role_keywords: direction?.criteria.role_keywords.join('，') ?? '',
    seniority: direction?.criteria.seniority.join('，') ?? '',
    locations: direction?.criteria.locations.join('，') ?? '',
    work_modes: direction?.criteria.work_modes.join('，') ?? '',
    salary_min: direction?.criteria.salary_min?.toString() ?? '',
    salary_max: direction?.criteria.salary_max?.toString() ?? '',
    salary_currency: direction?.criteria.salary_currency ?? '',
    industries: direction?.criteria.industries.join('，') ?? '',
    technologies: direction?.criteria.technologies.join('，') ?? '',
    exclusions: direction?.criteria.exclusions.join('，') ?? '',
    lifecycle: direction?.lifecycle ?? 'exploring',
    priority: direction?.priority.toString() ?? '0',
  };
}

function directionFromForm(form: DirectionForm): DirectionInput {
  const modes = csv(form.work_modes).filter((item) => ['onsite', 'hybrid', 'remote'].includes(item));
  return {
    label: form.label.trim(),
    lifecycle: form.lifecycle as DirectionLifecycle,
    priority: Number(form.priority || 0),
    criteria: {
      role_keywords: csv(form.role_keywords), seniority: csv(form.seniority), locations: csv(form.locations),
      work_modes: modes as DirectionInput['criteria']['work_modes'],
      salary_min: form.salary_min ? Number(form.salary_min) : null,
      salary_max: form.salary_max ? Number(form.salary_max) : null,
      salary_currency: clean(form.salary_currency)?.toUpperCase() ?? null,
      industries: csv(form.industries), technologies: csv(form.technologies), exclusions: csv(form.exclusions),
    },
  };
}

function DirectionEditor({
  open, initial, busy, onClose, onSave,
}: {
  open: boolean;
  initial?: CareerProfileDirection;
  busy: boolean;
  onClose: () => void;
  onSave: (value: DirectionInput) => void;
}) {
  const [form, setForm] = useState(() => directionToForm(initial));
  const update = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return (
    <Modal open={open} onClose={onClose} title={initial ? '编辑求职方向' : '新增求职方向'} width={720} footer={<>
      <Btn kind="ghost" onClick={onClose} disabled={busy}>取消</Btn>
      <Btn onClick={() => onSave(directionFromForm(form))} disabled={!form.label.trim()} loading={busy}>保存</Btn>
    </>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2"><FormItem label="方向名称"><TextInput value={form.label} onChange={(e) => update('label', e.target.value)} /></FormItem></div>
        <FormItem label="岗位关键词" hint="用逗号分隔"><TextInput value={form.role_keywords} onChange={(e) => update('role_keywords', e.target.value)} /></FormItem>
        <FormItem label="职级">
          <SelectInput value={csv(form.seniority)[0] ?? ''} onChange={(e) => update('seniority', e.target.value)}>
            <option value="">不限</option>
            {['实习', '应届', '初级', '中级', '高级', '专家', '管理'].map((value) => <option key={value} value={value}>{value}</option>)}
          </SelectInput>
        </FormItem>
        <FormItem label="地点"><TextInput value={form.locations} onChange={(e) => update('locations', e.target.value)} /></FormItem>
        <FormItem label="办公方式">
          <div className="flex flex-wrap gap-2">
            {([['onsite', '现场'], ['hybrid', '混合'], ['remote', '远程']] as const).map(([value, label]) => {
              const active = csv(form.work_modes).includes(value);
              return <button key={value} type="button" onClick={() => update('work_modes', active ? csv(form.work_modes).filter((item) => item !== value).join('，') : [...csv(form.work_modes), value].join('，'))} className={`rounded-md border px-3 py-2 text-sm ${active ? 'border-primary-300 bg-primary-50 text-primary-800' : 'border-stone-200 bg-stone-50 text-stone-600'}`}>{label}</button>;
            })}
          </div>
        </FormItem>
        <FormItem label="行业"><TextInput value={form.industries} onChange={(e) => update('industries', e.target.value)} /></FormItem>
        <FormItem label="技术方向"><TextInput value={form.technologies} onChange={(e) => update('technologies', e.target.value)} /></FormItem>
        <FormItem label="最低薪资"><TextInput type="number" min="0" value={form.salary_min} onChange={(e) => update('salary_min', e.target.value)} /></FormItem>
        <FormItem label="最高薪资"><TextInput type="number" min="0" value={form.salary_max} onChange={(e) => update('salary_max', e.target.value)} /></FormItem>
        <FormItem label="币种"><SelectInput value={form.salary_currency} onChange={(e) => update('salary_currency', e.target.value)}><option value="">未设置</option>{['CNY', 'USD', 'HKD', 'SGD', 'EUR', 'GBP', 'JPY'].map((value) => <option key={value} value={value}>{value}</option>)}</SelectInput></FormItem>
        <FormItem label="优先级"><SelectInput value={form.priority} onChange={(e) => update('priority', e.target.value)}><option value="0">普通</option><option value="1">较高</option><option value="2">最高</option></SelectInput></FormItem>
        <FormItem label="状态"><SelectInput value={form.lifecycle} onChange={(e) => update('lifecycle', e.target.value)}>{Object.entries(lifecycleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</SelectInput></FormItem>
        <div className="sm:col-span-2"><FormItem label="明确排除"><TextArea rows={2} value={form.exclusions} onChange={(e) => update('exclusions', e.target.value)} /></FormItem></div>
      </div>
    </Modal>
  );
}

function candidateLabel(item: CareerProfileCandidateItem): string {
  if (item.item_kind === 'fact') {
    const change = item.payload as FactDraftChange;
    return change.operation === 'remove'
      ? `删除个人事实 ${change.target_fact_id}`
      : `新增或更新：${change.fact ? factTitle(change.fact) : ''}`;
  }
  const change = item.payload as DirectionDraftChange;
  return change.operation === 'archive'
    ? `归档求职方向 ${change.target_direction_id}`
    : `新增或更新方向：${change.direction?.label ?? ''}`;
}

function DraftSummary({
  draft, busy, onDecision,
}: {
  draft: Awaited<ReturnType<typeof listCareerProfileDrafts>>[number];
  busy: boolean;
  onDecision: (item: CareerProfileCandidateItem, decision: 'accept' | 'reject') => void;
}) {
  if (draft.candidates?.length) {
    return <div className="space-y-2 text-sm text-stone-700">
      {draft.candidates.map((item) => (
        <div key={item.id} className={`rounded-md border px-3 py-2 ${item.conflict_kind === 'none' ? 'border-stone-100 bg-stone-50' : 'border-warning-200 bg-warning-50/50'}`}>
          <div className="flex flex-wrap items-start gap-2">
            <span className="min-w-0 flex-1">{candidateLabel(item)}</span>
            {item.conflict_kind !== 'none' && <Pill tone="warn">
              {item.conflict_kind === 'duplicate' ? '与当前内容重复' : item.conflict_kind === 'missing_target' ? '原内容已不存在' : '与当前档案冲突'}
            </Pill>}
          </div>
          {item.current_value && item.conflict_kind !== 'none' && (
            <details className="mt-2 text-xs text-stone-500">
              <summary className="cursor-pointer">查看当前档案值</summary>
              <pre className="mt-1 overflow-auto whitespace-pre-wrap rounded bg-white/70 p-2">{JSON.stringify(item.current_value, null, 2)}</pre>
            </details>
          )}
          {item.status === 'pending' && <div className="mt-2 flex gap-2">
            <Btn size="sm" disabled={busy} onClick={() => onDecision(item, 'accept')}>接受此项</Btn>
            <Btn kind="ghost" size="sm" disabled={busy} onClick={() => onDecision(item, 'reject')}>拒绝此项</Btn>
          </div>}
        </div>
      ))}
    </div>;
  }
  return (
    <div className="space-y-2 text-sm text-stone-700">
      {draft.proposed_facts.map((item, index) => (
        <div key={`fact-${index}`} className="rounded-md bg-stone-50 px-3 py-2">
          {item.operation === 'remove' ? `删除个人事实 ${item.target_fact_id}` : `新增或更新：${item.fact ? factTitle(item.fact) : ''}`}
        </div>
      ))}
      {draft.proposed_directions.map((item, index) => (
        <div key={`direction-${index}`} className="rounded-md bg-stone-50 px-3 py-2">
          {item.operation === 'archive' ? `归档求职方向 ${item.target_direction_id}` : `新增或更新方向：${item.direction?.label ?? ''}`}
        </div>
      ))}
    </div>
  );
}

function AbilityCard({ signal, onAction, onRecompute }: { signal: AbilitySignal; onAction: (action: 'dispute' | 'invalidate') => void; onRecompute: () => void }) {
  const tone = signal.status === 'active' ? 'success' : signal.status === 'disputed' ? 'warn' : 'neutral';
  const canChallenge = signal.status === 'active' || signal.status === 'disputed';
  return (
    <article className="rounded-xl border border-stone-200 bg-white p-4 shadow-xs">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-medium text-stone-800">{signal.topic}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-stone-500">
            <span>{signal.signal_type}</span>{signal.level && <span>· {signal.level}</span>}
            {signal.score !== null && <span>· {signal.score}</span>}
          </div>
        </div>
        <Pill tone={tone}>{signal.status}</Pill>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-stone-700">{signal.summary}</p>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-stone-100" title={`置信度 ${Math.round((signal.confidence ?? 0) * 100)}%`}>
        <div className="h-full bg-primary-500" style={{ width: `${Math.round((signal.confidence ?? 0) * 100)}%` }} />
      </div>
      <div className="mt-2 text-[11px] text-stone-500">置信度 {Math.round((signal.confidence ?? 0) * 100)}% · {signal.sources.length} 个真实来源</div>
      {signal.limitations && <p className="mt-2 text-xs text-stone-500">局限：{signal.limitations}</p>}
      {canChallenge && <div className="mt-3 flex gap-2">
        {signal.status === 'active' && <Btn kind="outline" size="sm" onClick={() => onAction('dispute')}>提出异议</Btn>}
        {signal.scope_kind === 'interview_record' && <Btn kind="ghost" size="sm" onClick={onRecompute}>根据原记录重算</Btn>}
        <Btn kind="ghost" size="sm" onClick={() => onAction('invalidate')}>标记失效</Btn>
      </div>}
    </article>
  );
}

function ResumeFactSection({
  id,
  title,
  description,
  items,
  actions,
  onAdd,
  onEdit,
  onDelete,
}: {
  id: string;
  title: string;
  description: string;
  items: ConfirmedPersonalFact[];
  actions: Array<{ label: string; kind: PersonalFact['kind'] }>;
  onAdd: (kind: PersonalFact['kind']) => void;
  onEdit: (item: ConfirmedPersonalFact) => void;
  onDelete: (item: ConfirmedPersonalFact) => void;
}) {
  return (
    <section id={id} className="scroll-mt-24 border-b border-stone-100 px-5 py-6 last:border-b-0 md:px-7">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-stone-800">{title}</h2>
          <p className="mt-1 text-xs text-stone-500">{description}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => (
            <Btn key={action.kind} kind="ghost" size="sm" icon={<Plus size={13} />} onClick={() => onAdd(action.kind)}>{action.label}</Btn>
          ))}
        </div>
      </div>
      {items.length === 0 ? (
        <button
          type="button"
          onClick={() => onAdd(actions[0].kind)}
          className="w-full rounded-lg border border-dashed border-stone-200 bg-stone-50/60 px-4 py-5 text-left text-sm text-stone-500 transition hover:border-primary-200 hover:bg-primary-50/40 hover:text-primary-700"
        >
          尚未填写。{actions[0].label}
        </button>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <article key={item.id} className="group flex items-start gap-3 rounded-lg border border-transparent px-1 py-2 hover:border-stone-100 hover:bg-stone-50/60">
              <div className="mt-0.5 rounded-md bg-stone-100 p-2 text-stone-600"><FactIcon kind={item.value.kind} /></div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2"><span className="font-medium text-stone-800">{factTitle(item.value)}</span><Pill>{factLabels[item.value.kind]}</Pill></div>
                {factDetail(item.value) && <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-stone-600">{factDetail(item.value)}</p>}
                <p className="mt-1 text-[11px] text-stone-400">确认于 {displayDate(item.confirmed_at)}</p>
              </div>
              <button className="rounded p-1.5 text-stone-400 hover:bg-white hover:text-stone-700" onClick={() => onEdit(item)} aria-label={`编辑 ${factTitle(item.value)}`}><Pencil size={15} /></button>
              <button className="rounded p-1.5 text-stone-400 hover:bg-danger-50 hover:text-danger-500" onClick={() => onDelete(item)} aria-label={`删除 ${factTitle(item.value)}`}><Trash2 size={15} /></button>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

export function CareerProfilePage() {
  const queryClient = useQueryClient();
  const profileQuery = useQuery({ queryKey: PROFILE_KEY, queryFn: getCareerProfile });
  const draftsQuery = useQuery({ queryKey: DRAFTS_KEY, queryFn: listCareerProfileDrafts });
  const signalsQuery = useQuery({ queryKey: SIGNALS_KEY, queryFn: () => listAbilitySignals(true) });
  const [factEditor, setFactEditor] = useState<{
    key: string;
    fact?: ConfirmedPersonalFact;
    kind?: PersonalFact['kind'];
  } | null>(null);
  const [directionEditor, setDirectionEditor] = useState<{ key: string; direction?: CareerProfileDirection } | null>(null);
  const [deleteFact, setDeleteFact] = useState<ConfirmedPersonalFact | null>(null);
  const [signalAction, setSignalAction] = useState<{ signal: AbilitySignal; action: 'dispute' | 'invalidate' } | null>(null);
  const [signalReason, setSignalReason] = useState('');
  const [busy, setBusy] = useState(false);

  const pendingDrafts = useMemo(() => draftsQuery.data?.filter((draft) => draft.status === 'pending') ?? [], [draftsQuery.data]);
  const profile = profileQuery.data;
  const groupedFacts = useMemo(() => {
    const groups = new Map<PersonalFact['kind'], ConfirmedPersonalFact[]>();
    for (const fact of profile?.personal_facts ?? []) {
      const current = groups.get(fact.value.kind) ?? [];
      current.push(fact);
      groups.set(fact.value.kind, current);
    }
    return groups;
  }, [profile?.personal_facts]);
  const profileChecks = useMemo(() => [
    { label: '联系方式与所在地', complete: Boolean(groupedFacts.get('contact')?.length && groupedFacts.get('location')?.length), href: '#personal' },
    { label: '求职方向', complete: Boolean(profile?.directions.length), href: '#directions' },
    { label: '工作 / 实习经历', complete: Boolean(groupedFacts.get('experience')?.length), href: '#experience' },
    { label: '项目经历', complete: Boolean(groupedFacts.get('project')?.length), href: '#projects' },
    { label: '教育经历', complete: Boolean(groupedFacts.get('education')?.length), href: '#education' },
    { label: '专业技能', complete: Boolean(groupedFacts.get('skill')?.length), href: '#skills' },
  ], [groupedFacts, profile?.directions.length]);
  const completeness = Math.round((profileChecks.filter((item) => item.complete).length / profileChecks.length) * 100);

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: PROFILE_KEY }),
      queryClient.invalidateQueries({ queryKey: DRAFTS_KEY }),
      queryClient.invalidateQueries({ queryKey: SIGNALS_KEY }),
    ]);
  };

  const run = async (operation: () => Promise<unknown>, success: string): Promise<boolean> => {
    setBusy(true);
    try {
      await operation();
      await refresh();
      toast.success(success);
      return true;
    } catch (error) {
      toast.error(extractErr(error));
      if ((error as { response?: { status?: number } }).response?.status === 409) await refresh();
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (profileQuery.isLoading) return <div className="flex items-center gap-2 p-6 text-sm text-stone-500"><Spinner size={15} />正在加载求职档案…</div>;
  if (!profile) return <div className="p-6"><EmptyState icon={<FileQuestion size={32} />} title="求职档案暂时无法加载" description={extractErr(profileQuery.error)} action={<Btn onClick={() => profileQuery.refetch()}>重试</Btn>} /></div>;

  return (
    <div className="mx-auto max-w-[1480px] space-y-5 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-stone-800">在线求职档案</h1>
          <p className="mt-1 text-sm text-stone-500">一页维护所有已确认信息；导入简历产生的候选仍需你逐项确认。</p>
        </div>
        <div className="flex gap-2">
          <Link to={copilotObjectHandoffHref('career_profile', profile.id, '在线求职档案')}>
            <Btn kind="outline" size="sm" icon={<Bot size={14} />}>询问 Copilot 完善档案</Btn>
          </Link>
          <Btn kind="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={refresh}>刷新</Btn>
        </div>
      </header>

      {pendingDrafts.length > 0 && <section className="rounded-xl border border-primary-200 bg-primary-50/60 p-4">
        <div className="mb-3 flex items-center gap-2"><FileQuestion size={17} className="text-primary-700" /><h2 className="font-semibold text-stone-800">待你确认的档案更新</h2><Pill tone="primary">{pendingDrafts.length}</Pill></div>
        <div className="space-y-3">
          {pendingDrafts.map((draft) => <div key={draft.id} className="rounded-lg border border-primary-100 bg-white p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><span className="text-xs text-stone-500">来源：{draft.source_kind} · {displayDate(draft.created_at)}</span><span className="text-[11px] text-stone-400">基于档案 v{draft.base_profile_version}</span></div>
            <DraftSummary draft={draft} busy={busy} onDecision={(item, decision) => void run(() => resolveCareerProfileCandidates({ draft, profileVersion: profile.version, decisions: [{ item, decision, note: decision === 'reject' ? '用户在档案页逐项拒绝' : undefined }] }), decision === 'accept' ? '候选已加入档案' : '候选已拒绝')} />
            <div className="mt-4 flex flex-wrap gap-2">
              {draft.candidates?.length ? <>
                {draft.candidates.some((item) => item.status === 'pending' && item.conflict_kind === 'none') && <Btn size="sm" icon={<Check size={14} />} disabled={busy} onClick={() => run(() => resolveCareerProfileCandidates({ draft, profileVersion: profile.version, decisions: (draft.candidates ?? []).filter((item) => item.status === 'pending' && item.conflict_kind === 'none').map((item) => ({ item, decision: 'accept' as const })) }), '已批量接受无冲突候选')}>批量接受无冲突项</Btn>}
                <Btn kind="ghost" size="sm" icon={<X size={14} />} disabled={busy} onClick={() => run(() => resolveCareerProfileDraft({ draft, profileVersion: profile.version, decision: 'reject', note: '用户在档案页拒绝剩余候选' }), '已拒绝剩余候选')}>拒绝剩余项</Btn>
              </> : <>
                <Btn size="sm" icon={<Check size={14} />} disabled={busy} onClick={() => run(() => resolveCareerProfileDraft({ draft, profileVersion: profile.version, decision: 'accept' }), '已合并档案更新')}>确认合并</Btn>
                <Btn kind="ghost" size="sm" icon={<X size={14} />} disabled={busy} onClick={() => run(() => resolveCareerProfileDraft({ draft, profileVersion: profile.version, decision: 'reject', note: '用户在档案页拒绝' }), '已拒绝这次更新')}>拒绝</Btn>
              </>}
            </div>
          </div>)}
        </div>
      </section>}

      <div className="grid items-start gap-5 xl:grid-cols-[190px_minmax(0,1fr)_280px]">
        <nav className="sticky top-4 hidden rounded-xl border border-stone-200 bg-white p-3 shadow-xs xl:block" aria-label="求职档案目录">
          <div className="px-2 pb-2 text-xs font-semibold text-stone-800">档案目录</div>
          {[
            ['personal', '个人信息'], ['directions', '期望职位'], ['experience', '工作 / 实习'],
            ['projects', '项目经历'], ['education', '教育经历'], ['skills', '专业技能'], ['abilities', '能力判断'],
          ].map(([id, label]) => <a key={id} href={`#${id}`} className="flex items-center justify-between rounded-md px-2 py-2 text-sm text-stone-600 hover:bg-primary-50 hover:text-primary-700"><span>{label}</span><span className="text-stone-300">›</span></a>)}
        </nav>

        <main className="overflow-hidden rounded-xl border border-stone-200 bg-white shadow-xs">
          <section className="border-b border-stone-100 bg-gradient-to-r from-white to-primary-50/40 px-5 py-6 md:px-7">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-3">
                  <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary-100 text-primary-700"><CircleUserRound size={28} /></div>
                  <div><h2 className="text-xl font-semibold text-stone-900">我的职业档案</h2><p className="mt-1 text-xs text-stone-500">{profile.personal_facts.length} 条已确认信息 · v{profile.version}</p></div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2 text-xs text-stone-600">
                  {(groupedFacts.get('location') ?? []).map((item) => <span key={item.id} className="rounded-full bg-white px-2.5 py-1 shadow-xs">{factTitle(item.value)}</span>)}
                  {(groupedFacts.get('contact') ?? []).map((item) => <span key={item.id} className="rounded-full bg-white px-2.5 py-1 shadow-xs">{factTitle(item.value)}</span>)}
                  {profile.directions.filter((item) => item.lifecycle === 'active').map((item) => <span key={item.id} className="rounded-full bg-primary-100 px-2.5 py-1 text-primary-800">目标：{item.label}</span>)}
                </div>
              </div>
              <Link to="/artifacts"><Btn kind="ghost" size="sm" icon={<BookOpen size={14} />}>简历与附件</Btn></Link>
            </div>
          </section>

          <ResumeFactSection id="personal" title="个人信息" description="联系方式和当前所在地；敏感信息只在你确认后保存。" items={[...(groupedFacts.get('contact') ?? []), ...(groupedFacts.get('location') ?? [])]} actions={[{ label: '填写联系方式', kind: 'contact' }, { label: '填写所在地', kind: 'location' }]} onAdd={(kind) => setFactEditor({ key: crypto.randomUUID(), kind })} onEdit={(fact) => setFactEditor({ key: crypto.randomUUID(), fact })} onDelete={setDeleteFact} />

          <section id="directions" className="scroll-mt-24 border-b border-stone-100 px-5 py-6 md:px-7">
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold text-stone-800">期望职位</h2><p className="mt-1 text-xs text-stone-500">岗位、地点、办公方式与薪资偏好集中在这里。</p></div><Btn kind="ghost" size="sm" icon={<Plus size={13} />} onClick={() => setDirectionEditor({ key: crypto.randomUUID() })}>填写期望职位</Btn></div>
            {profile.directions.length === 0 ? <button type="button" onClick={() => setDirectionEditor({ key: crypto.randomUUID() })} className="w-full rounded-lg border border-dashed border-stone-200 bg-stone-50/60 px-4 py-5 text-left text-sm text-stone-500 hover:border-primary-200 hover:bg-primary-50/40">尚未填写。设置期望岗位、地点和办公方式</button> : <div className="space-y-3">{profile.directions.map((direction) => <article key={direction.id} className="rounded-lg border border-stone-200 p-4">
              <div className="flex items-start justify-between gap-3"><div><h3 className="font-medium text-stone-800">{direction.label}</h3><div className="mt-2 flex flex-wrap gap-1.5"><Pill tone={lifecycleTone[direction.lifecycle]}>{lifecycleLabels[direction.lifecycle]}</Pill>{direction.criteria.role_keywords.map((item) => <Pill key={item}>{item}</Pill>)}</div></div><button className="rounded p-1.5 text-stone-400 hover:bg-stone-100" onClick={() => setDirectionEditor({ key: crypto.randomUUID(), direction })} aria-label={`编辑 ${direction.label}`}><Pencil size={15} /></button></div>
              <div className="mt-3 grid gap-1 text-xs text-stone-600 sm:grid-cols-2">{direction.criteria.locations.length > 0 && <p>地点：{direction.criteria.locations.join('、')}</p>}{direction.criteria.work_modes.length > 0 && <p>办公：{direction.criteria.work_modes.map((mode) => ({ onsite: '现场', hybrid: '混合', remote: '远程' }[mode])).join('、')}</p>}{direction.criteria.technologies.length > 0 && <p>技术：{direction.criteria.technologies.join('、')}</p>}{direction.criteria.salary_min !== null && <p>薪资：{direction.criteria.salary_currency} {direction.criteria.salary_min} – {direction.criteria.salary_max ?? '不限'}</p>}</div>
              <div className="mt-4 flex flex-wrap gap-2"><Link to={copilotObjectHandoffHref('career_profile_direction', direction.id, direction.label)}><Btn kind="ghost" size="sm" icon={<Bot size={13} />}>询问 Copilot</Btn></Link>{direction.lifecycle !== 'active' && direction.lifecycle !== 'archived' && <Btn kind="outline" size="sm" onClick={() => run(() => setCareerDirectionLifecycle(direction.id, profile.version, 'active'), '已设为当前目标')}>设为当前目标</Btn>}{direction.lifecycle === 'active' && <Btn kind="ghost" size="sm" onClick={() => run(() => setCareerDirectionLifecycle(direction.id, profile.version, 'paused'), '方向已暂停')}>暂停</Btn>}{direction.lifecycle !== 'archived' && <Btn kind="ghost" size="sm" onClick={() => run(() => setCareerDirectionLifecycle(direction.id, profile.version, 'archived'), '方向已归档')}>归档</Btn>}</div>
            </article>)}</div>}
          </section>

          <ResumeFactSection id="experience" title="工作 / 实习经历" description="按时间维护真实任职、实习与职责成果。" items={groupedFacts.get('experience') ?? []} actions={[{ label: '填写工作经历', kind: 'experience' }]} onAdd={(kind) => setFactEditor({ key: crypto.randomUUID(), kind })} onEdit={(fact) => setFactEditor({ key: crypto.randomUUID(), fact })} onDelete={setDeleteFact} />
          <ResumeFactSection id="projects" title="项目经历" description="写清项目背景、你的角色、行动和可核验结果。" items={groupedFacts.get('project') ?? []} actions={[{ label: '填写项目经历', kind: 'project' }]} onAdd={(kind) => setFactEditor({ key: crypto.randomUUID(), kind })} onEdit={(fact) => setFactEditor({ key: crypto.randomUUID(), fact })} onDelete={setDeleteFact} />
          <ResumeFactSection id="education" title="教育经历" description="学校、学历、专业与在校经历。" items={groupedFacts.get('education') ?? []} actions={[{ label: '填写教育经历', kind: 'education' }]} onAdd={(kind) => setFactEditor({ key: crypto.randomUUID(), kind })} onEdit={(fact) => setFactEditor({ key: crypto.randomUUID(), fact })} onDelete={setDeleteFact} />
          <ResumeFactSection id="skills" title="专业技能与成果" description="技能类别使用固定选项；证书、奖项和成果可单独补充。" items={[...(groupedFacts.get('skill') ?? []), ...(groupedFacts.get('achievement') ?? [])]} actions={[{ label: '填写技能', kind: 'skill' }, { label: '填写成果', kind: 'achievement' }]} onAdd={(kind) => setFactEditor({ key: crypto.randomUUID(), kind })} onEdit={(fact) => setFactEditor({ key: crypto.randomUUID(), fact })} onDelete={setDeleteFact} />

          <section id="abilities" className="scroll-mt-24 px-5 py-6 md:px-7">
            <div className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-semibold text-stone-800">能力判断</h2><p className="mt-1 text-xs text-stone-500">这些是带真实来源的模型推断，不会混入你确认的个人事实。</p></div>{signalsQuery.isFetching && <Spinner size={14} className="text-stone-400" />}</div>
            {signalsQuery.data?.length ? <div className="grid gap-4 md:grid-cols-2">{signalsQuery.data.map((signal) => <AbilityCard key={signal.id} signal={signal} onAction={(action) => { setSignalAction({ signal, action }); setSignalReason(''); }} onRecompute={() => { if (signal.scope_ref_id) void run(() => recomputeInterviewAbilitySignals(signal.scope_ref_id as string), '已根据原面试记录重算能力判断'); }} />)}</div> : <div className="rounded-lg border border-dashed border-stone-200 bg-stone-50/60 p-5 text-sm text-stone-500">完成一次真实面试复盘后，这里会形成带来源的能力判断。</div>}
          </section>
        </main>

        <aside className="sticky top-4 space-y-4">
          <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
            <div className="flex items-center justify-between"><h2 className="font-semibold text-stone-800">档案完整度</h2><span className="text-2xl font-semibold text-primary-700">{completeness}%</span></div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-stone-100"><div className="h-full rounded-full bg-primary-500 transition-all" style={{ width: `${completeness}%` }} /></div>
            <div className="mt-4 space-y-2">
              {profileChecks.map((item) => <a key={item.href} href={item.href} className="flex items-center gap-2 text-xs"><span className={`flex h-4 w-4 items-center justify-center rounded-full ${item.complete ? 'bg-accent-100 text-accent-700' : 'bg-warning-100 text-warning-700'}`}>{item.complete ? '✓' : '!'}</span><span className={item.complete ? 'text-stone-500' : 'text-stone-700'}>{item.label}</span></a>)}
            </div>
          </section>
          <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
            <h2 className="font-semibold text-stone-800">档案诊断</h2>
            <div className="mt-3 space-y-3 text-xs leading-relaxed text-stone-600">
              {profileChecks.filter((item) => !item.complete).slice(0, 3).map((item) => <a key={item.href} href={item.href} className="block rounded-lg bg-warning-50 p-3 text-warning-800">建议完善：{item.label}</a>)}
              {profileChecks.every((item) => item.complete) && <div className="rounded-lg bg-accent-50 p-3 text-accent-800">核心档案已经完整，可以继续优化成果描述和证据。</div>}
              <div className="rounded-lg bg-stone-50 p-3">{signalsQuery.data?.length ?? 0} 条能力判断 · {pendingDrafts.length} 组待确认更新</div>
            </div>
          </section>
        </aside>
      </div>

      {factEditor && <FactEditor key={factEditor.key} open initial={factEditor.fact} initialKind={factEditor.kind} busy={busy} onClose={() => setFactEditor(null)} onSave={async (fact) => { if (await run(() => savePersonalFact({ profileVersion: profile.version, fact, factId: factEditor.fact?.id }), '个人事实已保存')) setFactEditor(null); }} />}
      {directionEditor && <DirectionEditor key={directionEditor.key} open initial={directionEditor.direction} busy={busy} onClose={() => setDirectionEditor(null)} onSave={async (direction) => { if (await run(() => saveCareerDirection({ profileVersion: profile.version, direction, directionId: directionEditor.direction?.id }), '求职方向已保存')) setDirectionEditor(null); }} />}
      <ConfirmDialog open={Boolean(deleteFact)} title="删除这条个人事实？" description={deleteFact ? factTitle(deleteFact.value) : ''} confirmText="删除" danger loading={busy} onCancel={() => setDeleteFact(null)} onConfirm={async () => { if (deleteFact && await run(() => removePersonalFact(deleteFact.id, profile.version), '个人事实已删除')) setDeleteFact(null); }} />
      <Modal open={Boolean(signalAction)} onClose={() => setSignalAction(null)} title={signalAction?.action === 'dispute' ? '对能力判断提出异议' : '标记能力判断失效'} width={520} footer={<><Btn kind="ghost" onClick={() => setSignalAction(null)}>取消</Btn><Btn kind={signalAction?.action === 'invalidate' ? 'danger' : 'primary'} disabled={!signalReason.trim()} loading={busy} onClick={async () => { if (signalAction && await run(() => changeAbilitySignalStatus(signalAction.signal, signalAction.action, signalReason.trim()), '能力判断状态已更新')) setSignalAction(null); }}>确认</Btn></>}>
        <div className="mb-3 flex items-start gap-2 rounded-md bg-warning-50 p-3 text-xs text-warning-700"><AlertTriangle size={15} className="mt-0.5 shrink-0" />状态变化会被保留，历史来源不会被删除。</div>
        <FormItem label="原因"><TextArea rows={4} value={signalReason} onChange={(e) => setSignalReason(e.target.value)} placeholder="说明哪里不准确，或为什么已经不再适用" /></FormItem>
      </Modal>
    </div>
  );
}
