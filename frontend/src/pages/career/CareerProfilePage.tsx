import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Check,
  MapPin,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  Bot,
  FileText, Eye, X, Mail, Phone,
} from 'lucide-react';
import {
  getCareerProfile,
  listCareerProfileDrafts,
  removePersonalFact,
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
import { Avatar } from '@/components/ui/Avatar';
import { toast } from '@/store/uiStore';
import type {
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
import { createResumeFromFile, listResumes } from '@/api/resumes';
import { uploadAvatar } from '@/api/auth';
import { useAuthStore } from '@/store/authStore';

const PROFILE_KEY = ['career-profile'] as const;
const DRAFTS_KEY = ['career-profile-drafts'] as const;

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
  personal: '个人信息', summary: '个人优势', certificate: '资格证书',
  organization: '社团 / 组织经历', volunteer: '志愿者经历',
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
    case 'personal': return fact.name;
    case 'summary': return '个人优势';
    case 'certificate': return fact.title;
    case 'organization': case 'volunteer': return fact.organization;
  }
}

function factDetail(fact: PersonalFact): string {
  switch (fact.kind) {
    case 'education': return [fact.field_of_study, fact.description].filter(Boolean).join(' · ');
    case 'experience': return fact.description ?? '';
    case 'project': return [fact.role, fact.technologies.join('、'), fact.description].filter(Boolean).join(' · ');
    case 'skill': return [fact.category, fact.description].filter(Boolean).join('\n');
    case 'achievement': return fact.description ?? '';
    case 'contact': return { email: '邮箱', phone: '电话', website: '个人网站', other: '其他联系' }[fact.channel];
    case 'location': return '';
    case 'personal': return [fact.gender === 'male' ? '男' : fact.gender === 'female' ? '女' : '', fact.birth_date, fact.career_status, fact.availability].filter(Boolean).join(' · ');
    case 'summary': return fact.text;
    case 'certificate': return [fact.issuer, fact.description].filter(Boolean).join('\n');
    case 'organization': return [fact.role, fact.description].filter(Boolean).join('\n');
    case 'volunteer': return [fact.role, fact.hours != null ? `${fact.hours} 小时` : '', fact.description].filter(Boolean).join('\n');
  }
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
  const dates = { start_date: clean(form.start_date ?? ''), end_date: clean(form.end_date ?? ''), ongoing: form.ongoing === 'true' };
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
      return { kind: 'skill', name: form.name.trim(), category: clean(form.category ?? ''), description: clean(form.description ?? '') };
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
    case 'personal': return { kind: 'personal', name: form.name.trim(), gender: (form.gender || 'undisclosed') as 'male' | 'female' | 'undisclosed', birth_date: clean(form.birth_date ?? ''), career_status: clean(form.career_status ?? ''), availability: clean(form.availability ?? '') };
    case 'summary': return { kind: 'summary', text: form.text.trim() };
    case 'certificate': return { kind: 'certificate', title: form.title.trim(), issuer: clean(form.issuer ?? ''), occurred_on: clean(form.occurred_on ?? ''), description: clean(form.description ?? '') };
    case 'organization': return { kind: 'organization', organization: form.organization.trim(), role: clean(form.role ?? ''), description: clean(form.description ?? ''), ...dates };
    case 'volunteer': return { kind: 'volunteer', organization: form.organization.trim(), role: clean(form.role ?? ''), hours: form.hours ? Number(form.hours) : undefined, description: clean(form.description ?? ''), ...dates };
  }
}

function FactEditor({
  initial,
  initialKind,
  busy,
  onClose,
  onSave,
}: {
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
    ['project', 'skill', 'personal'].includes(form.kind) ? form.name :
    ['achievement', 'certificate'].includes(form.kind) ? form.title :
    ['organization', 'volunteer'].includes(form.kind) ? form.organization :
    form.kind === 'summary' ? form.text : form.value;

  return (
    <form className="online-resume-editor" aria-label={`编辑${factLabels[form.kind]}`} onSubmit={(event) => { event.preventDefault(); if (required?.trim() && !busy) onSave(factFromForm(form)); }}>
      <h3>编辑{factLabels[form.kind]}</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        {form.kind === 'personal' && <>
          <FormItem label="姓名"><TextInput autoFocus required maxLength={160} value={form.name ?? ''} onChange={(e) => update('name', e.target.value)} /></FormItem>
          <FormItem label="性别（选填）"><SelectInput value={form.gender || 'undisclosed'} onChange={(e) => update('gender', e.target.value)}><option value="undisclosed">不填写</option><option value="male">男</option><option value="female">女</option></SelectInput></FormItem>
          <FormItem label="出生日期（选填）"><TextInput type="date" value={form.birth_date ?? ''} onChange={(e) => update('birth_date', e.target.value)} /></FormItem>
          <FormItem label="当前状态"><TextInput value={form.career_status ?? ''} onChange={(e) => update('career_status', e.target.value)} placeholder="例如：2027 届毕业生 / 在职" /></FormItem>
          <FormItem label="到岗时间"><TextInput value={form.availability ?? ''} onChange={(e) => update('availability', e.target.value)} placeholder="例如：一个月内到岗" /></FormItem>
        </>}
        {form.kind === 'summary' && <div className="sm:col-span-2"><FormItem label="个人优势"><TextArea autoFocus required rows={8} maxLength={8000} value={form.text ?? ''} onChange={(e) => update('text', e.target.value)} placeholder="介绍你的专业背景、核心能力和代表成果。" /></FormItem></div>}
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
        {['organization', 'volunteer'].includes(form.kind) && <>
          <FormItem label="组织 / 活动名称"><TextInput required value={form.organization ?? ''} onChange={(e) => update('organization', e.target.value)} /></FormItem>
          <FormItem label="承担角色"><TextInput value={form.role ?? ''} onChange={(e) => update('role', e.target.value)} /></FormItem>
          {form.kind === 'volunteer' && <FormItem label="服务时长（小时）"><TextInput type="number" min="0" max="100000" step="0.5" value={form.hours ?? ''} onChange={(e) => update('hours', e.target.value)} /></FormItem>}
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
        {['achievement', 'certificate'].includes(form.kind) && <>
          <FormItem label={form.kind === 'certificate' ? '证书名称' : '成果名称'}><TextInput required value={form.title ?? ''} onChange={(e) => update('title', e.target.value)} /></FormItem>
          <FormItem label="发生日期"><TextInput type="date" value={form.occurred_on ?? ''} onChange={(e) => update('occurred_on', e.target.value)} /></FormItem>
          {form.kind === 'certificate' && <FormItem label="颁发机构"><TextInput value={form.issuer ?? ''} onChange={(e) => update('issuer', e.target.value)} /></FormItem>}
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
        {['education', 'experience', 'project', 'organization', 'volunteer'].includes(form.kind) && <>
          <FormItem label="开始日期" hint="按实际精度填写年、年月或完整日期"><TextInput placeholder="2024 / 2024-09 / 2024-09-01" pattern="[0-9]{4}(-[0-9]{2}){0,2}" maxLength={10} value={form.start_date ?? ''} onChange={(e) => update('start_date', e.target.value)} /></FormItem>
          <FormItem label="结束日期" hint="未注明结束时间可留空"><TextInput disabled={form.ongoing === 'true'} placeholder="2027 / 2027-06 / 2027-06-30" pattern="[0-9]{4}(-[0-9]{2}){0,2}" maxLength={10} value={form.end_date ?? ''} onChange={(e) => update('end_date', e.target.value)} /></FormItem>
          <label className="flex items-center gap-2 text-sm text-stone-600"><input type="checkbox" checked={form.ongoing === 'true'} onChange={(event) => setForm((current) => ({ ...current, ongoing: event.target.checked ? 'true' : 'false', end_date: event.target.checked ? '' : current.end_date }))} />仍在进行（至今）</label>
        </>}
        {['education', 'experience', 'project', 'achievement', 'certificate', 'organization', 'volunteer', 'skill'].includes(form.kind) && (
          <div className="sm:col-span-2">
            <FormItem label="详细描述"><TextArea rows={6} maxLength={form.kind === 'education' || form.kind === 'certificate' || form.kind === 'achievement' ? 2000 : 4000} value={form.description ?? ''} onChange={(e) => update('description', e.target.value)} /></FormItem>
          </div>
        )}
      </div>
      <div className="mt-4 flex justify-end gap-2"><Btn kind="ghost" disabled={busy} onClick={onClose}>取消</Btn><Btn type="submit" disabled={!required?.trim()} loading={busy}>保存</Btn></div>
    </form>
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
  initial, busy, onClose, onSave,
}: {
  initial?: CareerProfileDirection;
  busy: boolean;
  onClose: () => void;
  onSave: (value: DirectionInput) => void;
}) {
  const [form, setForm] = useState(() => directionToForm(initial));
  const update = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return (
    <form className="online-resume-editor" aria-label="编辑期望职位" onSubmit={(event) => { event.preventDefault(); if (form.label.trim() && !busy) onSave(directionFromForm(form)); }}>
      <h3>编辑期望职位</h3>
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
      <div className="mt-4 flex justify-end gap-2"><Btn kind="ghost" disabled={busy} onClick={onClose}>取消</Btn><Btn type="submit" loading={busy} disabled={!form.label.trim()}>保存</Btn></div>
    </form>
  );
}

function candidateLabel(item: CareerProfileCandidateItem): string {
  if (item.item_kind === 'fact') {
    const change = item.payload as FactDraftChange;
    return change.operation === 'remove'
      ? `删除：${item.current_value?.value ? factTitle(item.current_value.value as PersonalFact) : '这条个人信息'}`
      : `新增或更新：${change.fact ? factTitle(change.fact) : ''}`;
  }
  const change = item.payload as DirectionDraftChange;
  return change.operation === 'archive'
    ? `归档：${item.current_value?.label ?? '这个求职方向'}`
    : `新增或更新方向：${change.direction?.label ?? ''}`;
}

function DraftSummary({
  draft, busy, onDecision,
}: {
  draft: Awaited<ReturnType<typeof listCareerProfileDrafts>>[number];
  busy: boolean;
  onDecision: (item: CareerProfileCandidateItem, decision: 'accept' | 'reject') => void;
}) {
  return <div className="space-y-2 text-sm text-stone-700">
    {draft.candidates.filter((item) => item.status === 'pending').map((item) => (
      <div key={item.id} className={`rounded-md border px-3 py-2 ${item.conflict_kind === 'none' ? 'border-stone-100 bg-stone-50' : 'border-warning-200 bg-warning-50/50'}`}>
        <div className="flex flex-wrap items-start gap-2">
          <span className="min-w-0 flex-1">{candidateLabel(item)}</span>
          {item.conflict_kind !== 'none' && <Pill tone="warn">
            {item.conflict_kind === 'duplicate' ? '与当前内容重复' : item.conflict_kind === 'missing_target' ? '原内容已不存在' : '与当前档案冲突'}
          </Pill>}
        </div>
        {item.item_kind === 'fact' && (item.payload as FactDraftChange).fact && <p className="mt-2 whitespace-pre-wrap text-xs leading-6 text-stone-600">{[factPeriod((item.payload as FactDraftChange).fact!), factDetail((item.payload as FactDraftChange).fact!)].filter(Boolean).join(' · ')}</p>}
        {item.item_kind === 'direction' && (item.payload as DirectionDraftChange).direction && <p className="mt-2 text-xs text-stone-600">{(item.payload as DirectionDraftChange).direction!.criteria.role_keywords.join('、')} · {(item.payload as DirectionDraftChange).direction!.criteria.locations.join('、')}</p>}
        {item.current_value && item.conflict_kind !== 'none' && (
          <details className="mt-2 text-xs text-stone-500">
            <summary className="cursor-pointer">查看当前档案值</summary>
            {item.item_kind === 'fact' && item.current_value.value ? <div className="mt-2 rounded bg-stone-50 p-3"><p className="font-medium">{factTitle(item.current_value.value as PersonalFact)}</p><p className="mt-1 whitespace-pre-wrap leading-6">{[factPeriod(item.current_value.value as PersonalFact), factDetail(item.current_value.value as PersonalFact)].filter(Boolean).join(' · ')}</p></div>
              : <p className="mt-2">{String(item.current_value.label ?? '求职方向')}</p>}
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

const resumeSections = [
  { id: 'personal', label: '个人信息' }, { id: 'summary', label: '个人优势' },
  { id: 'directions', label: '期望职位' }, { id: 'experience', label: '工作 / 实习' },
  { id: 'project', label: '项目经历' }, { id: 'education', label: '教育经历' },
  { id: 'certificate', label: '资格证书' }, { id: 'organization', label: '社团 / 组织' },
  { id: 'volunteer', label: '志愿者经历' }, { id: 'skill', label: '专业技能' },
  { id: 'achievement', label: '奖项与成果' },
] as const;
const draftSources = { artifact_version: '简历导入', resume: '简历导入', conversation_message: '协作建议', model_inference: '协作建议' };

function factPeriod(fact: PersonalFact) {
  if ('start_date' in fact && fact.start_date) return fact.start_date.replaceAll('-', '.') + (fact.end_date ? ` — ${fact.end_date.replaceAll('-', '.')}` : fact.ongoing ? ' — 至今' : '');
  if ('occurred_on' in fact && fact.occurred_on) return fact.occurred_on.slice(0, 7).replace('-', '.');
  return '';
}

function ResumeSection({ id, title, empty, children, action }: { id: string; title: string; empty: boolean; children: ReactNode; action?: ReactNode }) {
  return <section id={'resume-' + id} className={`online-resume-section${empty ? ' online-resume-empty-section' : ''}`}>
    <div className="online-resume-section-heading"><h2>{title}</h2><div className="online-resume-controls">{action}</div></div>{children}
  </section>;
}

export function CareerProfilePage() {
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const profileQuery = useQuery({ queryKey: PROFILE_KEY, queryFn: getCareerProfile });
  const draftsQuery = useQuery({ queryKey: DRAFTS_KEY, queryFn: listCareerProfileDrafts });
  const resumesQuery = useQuery({ queryKey: ['resumes'], queryFn: () => listResumes(), refetchInterval: ({ state }) => state.data?.some((resume) => resume.parse_status === 'pending' || resume.parse_status === 'processing') ? 2500 : false });
  const fileRef = useRef<HTMLInputElement>(null);
  const avatarRef = useRef<HTMLInputElement>(null);
  const me = useAuthStore((state) => state.me);
  const [uploading, setUploading] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [factEditor, setFactEditor] = useState<{ key: string; fact?: ConfirmedPersonalFact; kind: PersonalFact['kind'] } | null>(null);
  const [directionEditor, setDirectionEditor] = useState<{ key: string; direction?: CareerProfileDirection } | null>(null);
  const [deleteFact, setDeleteFact] = useState<ConfirmedPersonalFact | null>(null);
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null);
  const [preview, setPreview] = useState(false);
  const [showPastDirections, setShowPastDirections] = useState(false);
  const [activeSection, setActiveSection] = useState('personal');
  const [busy, setBusy] = useState(false);
  const reviewOpen = params.get('tab') === 'updates';
  const profile = profileQuery.data;
  const pendingDrafts = draftsQuery.data?.filter((draft) => draft.status === 'pending') ?? [];
  const selectedDraft = pendingDrafts.find((draft) => draft.id === selectedDraftId) ?? pendingDrafts[0];
  const grouped = useMemo(() => {
    const groups = new Map<PersonalFact['kind'], ConfirmedPersonalFact[]>();
    for (const fact of profile?.personal_facts ?? []) groups.set(fact.value.kind, [...(groups.get(fact.value.kind) ?? []), fact]);
    return groups;
  }, [profile?.personal_facts]);
  const importedDraftIds = resumesQuery.data?.map((resume) => resume.pending_profile_draft_id ?? '').join('|');
  useEffect(() => { if (importedDraftIds) void client.invalidateQueries({ queryKey: DRAFTS_KEY }); }, [importedDraftIds, client]);
  useEffect(() => {
    if (!profile) return;
    const root = document.getElementById('workspace-content');
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible[0]) setActiveSection(visible[0].target.id.replace('resume-', ''));
    }, { root, rootMargin: '0px 0px -65% 0px', threshold: 0 });
    for (const section of document.querySelectorAll('.online-resume-section')) observer.observe(section);
    return () => observer.disconnect();
  }, [profile, preview]);
  useEffect(() => { if (factEditor || directionEditor) document.querySelector('.online-resume-editor')?.scrollIntoView({ block: 'center', behavior: 'smooth' }); }, [factEditor, directionEditor]);
  const review = (open: boolean) => setParams((current) => { const next = new URLSearchParams(current); if (open) next.set('tab', 'updates'); else next.delete('tab'); return next; }, { replace: true });
  const refresh = async () => { await Promise.all([client.invalidateQueries({ queryKey: PROFILE_KEY }), client.invalidateQueries({ queryKey: DRAFTS_KEY }), client.invalidateQueries({ queryKey: ['resumes'] })]); };
  const run = async (operation: () => Promise<unknown>, success: string) => {
    setBusy(true);
    try { await operation(); await refresh(); toast.success(success); return true; }
    catch (error) { toast.error(extractErr(error)); if ((error as { response?: { status?: number } }).response?.status === 409) await refresh(); return false; }
    finally { setBusy(false); }
  };
  const editFact = (kind: PersonalFact['kind'], fact?: ConfirmedPersonalFact) => { setDirectionEditor(null); setFactEditor({ key: crypto.randomUUID(), kind, fact }); };
  const editDirection = (direction?: CareerProfileDirection) => { setFactEditor(null); setDirectionEditor({ key: crypto.randomUUID(), direction }); };
  const add = (kind: PersonalFact['kind'], label = '添加') => <button type="button" onClick={() => editFact(kind)} aria-label={`添加${factLabels[kind]}`}><Plus size={14} />{label}</button>;
  const upload = async (file: File) => {
    setUploading(true);
    try { await createResumeFromFile(file, { make_default: !resumesQuery.data?.length }); await Promise.all([client.invalidateQueries({ queryKey: ['resumes'] }), client.invalidateQueries({ queryKey: ['artifacts'] })]); toast.success('简历已上传，解析完成后可核对导入内容'); }
    catch (error) { toast.error(extractErr(error, '简历导入失败')); }
    finally { setUploading(false); }
  };
  if (profileQuery.isPending) return <div className="workspace-page flex items-center gap-2" role="status"><Spinner size={15} />正在加载个人档案…</div>;
  if (!profile) return <div className="workspace-page"><EmptyState title="个人档案暂时无法加载" description={extractErr(profileQuery.error)} action={<Btn onClick={() => profileQuery.refetch()}>重试</Btn>} /></div>;
  const person = grouped.get('personal')?.[0];
  const identity = person?.value.kind === 'personal' ? person.value : null;
  const contacts = [...(grouped.get('contact') ?? []), ...(grouped.get('location') ?? [])];
  const editor = (kind: PersonalFact['kind']) => factEditor?.kind === kind ? <FactEditor key={factEditor.key} initial={factEditor.fact} initialKind={kind} busy={busy} onClose={() => setFactEditor(null)} onSave={async (fact) => { if (await run(() => savePersonalFact({ profileVersion: profile.version, fact, factId: factEditor.fact?.id }), '档案已保存')) setFactEditor(null); }} /> : null;
  const factSection = (kind: Exclude<PersonalFact['kind'], 'personal' | 'contact' | 'location'>, title: string, hint: string) => {
    const items = grouped.get(kind) ?? [];
    const singleton = kind === 'summary';
    const sectionAction = singleton && items[0] ? <button onClick={() => editFact(kind, items[0])}><Pencil size={14} />编辑</button> : add(kind);
    return <ResumeSection key={kind} id={kind} title={title} empty={!items.length} action={sectionAction}>
      {!items.length && factEditor?.kind !== kind && <p className="online-resume-empty online-resume-controls">{hint}</p>}
      <div className="online-resume-entries">{items.map((item) => <article key={item.id} className="online-resume-entry">
        {!singleton && <div className="online-resume-entry-heading"><h3>{factTitle(item.value)}</h3><span>{factPeriod(item.value)}</span></div>}
        {!!factDetail(item.value) && <p className="online-resume-description">{factDetail(item.value)}</p>}
        {!preview && <div className="online-resume-entry-actions online-resume-controls">{!singleton && <button onClick={() => editFact(kind, item)} aria-label={`编辑 ${factTitle(item.value)}`}><Pencil size={14} />编辑</button>}<button onClick={() => setDeleteFact(item)} aria-label={`删除 ${factTitle(item.value)}`}><Trash2 size={13} /></button></div>}
      </article>)}</div>
      {editor(kind)}
    </ResumeSection>;
  };
  const directions = profile.directions.filter((entry) => (!preview && showPastDirections) || entry.lifecycle === 'active' || entry.lifecycle === 'exploring');
  return <div className={`online-resume-layout${preview ? ' is-preview' : ''}`}>
    <input ref={fileRef} type="file" accept=".pdf,.doc,.docx,.txt,.md" hidden aria-label="选择导入的简历" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void upload(file); }} />
    <input ref={avatarRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden aria-label="选择简历头像" onChange={async (event) => { const file = event.target.files?.[0]; event.target.value = ''; if (!file) return; setAvatarUploading(true); try { useAuthStore.getState().setMe(await uploadAvatar(file)); toast.success('头像已更新'); } catch (error) { toast.error(extractErr(error, '头像上传失败')); } finally { setAvatarUploading(false); } }} />
    <nav className="online-resume-directory" aria-label="档案目录"><h2>档案目录</h2>{resumeSections.map((section) => <a key={section.id} href={'#resume-' + section.id} aria-current={activeSection === section.id ? 'location' : undefined} onClick={() => setActiveSection(section.id)}>{section.label}</a>)}</nav>
    <article className="online-resume-paper" aria-label="个人经历档案">
      <header className="online-resume-toolbar"><h1>{preview ? '档案预览' : '个人经历档案'}</h1><div><button onClick={() => { setPreview(!preview); setFactEditor(null); setDirectionEditor(null); }}>{preview ? <X size={14} /> : <Eye size={14} />}{preview ? '返回编辑' : '预览'}</button><button className="online-resume-controls" disabled={uploading} onClick={() => fileRef.current?.click()}>{uploading ? '正在上传…' : '导入已有简历'}</button><Link to="/artifacts">打开简历与材料 ↗</Link></div></header>
      <ResumeSection id="personal" title="个人信息" empty={!identity && !contacts.length} action={<button onClick={() => editFact('personal', person)}><Pencil size={14} />编辑个人信息</button>}>
        <div className="online-resume-person"><div><h2 className={!identity ? 'online-resume-placeholder' : undefined}>{identity?.name || '填写你的姓名'}</h2><p className={!identity ? 'online-resume-placeholder' : undefined}>{[identity?.gender === 'male' ? '男' : identity?.gender === 'female' ? '女' : '', identity?.birth_date ? `${identity.birth_date.slice(0, 7)} 出生` : '', identity?.career_status, identity?.availability].filter(Boolean).join(' · ') || '补充个人信息，让简历有一个清晰的开始。'}</p></div><button type="button" disabled={avatarUploading || preview} onClick={() => avatarRef.current?.click()} aria-label="更换简历头像" title="更换头像"><Avatar src={me?.avatar_url} name={identity?.name ?? ''} alt="简历头像" className="online-resume-avatar" /></button></div>
        <div className="online-resume-contacts">{contacts.map((item) => <div key={item.id}>{item.value.kind === 'location' ? <MapPin size={13} /> : item.value.kind === 'contact' && item.value.channel === 'phone' ? <Phone size={13} /> : <Mail size={13} />}<span>{factTitle(item.value)}</span><button className="online-resume-controls" onClick={() => editFact(item.value.kind, item)} aria-label={`编辑 ${factTitle(item.value)}`}><Pencil size={12} /></button><button className="online-resume-controls" onClick={() => setDeleteFact(item)} aria-label={`删除 ${factTitle(item.value)}`}><Trash2 size={12} /></button></div>)}</div>
        {!preview && <div className="online-resume-contact-add online-resume-controls">{add('contact', '添加联系方式')}{add('location', '添加所在地')}</div>}
        {editor('personal')}{editor('contact')}{editor('location')}
      </ResumeSection>
      {factSection('summary', '个人优势', '概括你的专业背景、优势与代表成果')}
      <ResumeSection id="directions" title="期望职位" empty={!directions.length} action={<button onClick={() => editDirection()}><Plus size={14} />添加</button>}>
        {!directions.length && !directionEditor && <button className="online-resume-empty online-resume-controls" onClick={() => editDirection()}>填写期望岗位、城市与薪资<Plus size={14} /></button>}
        {!preview && profile.directions.some((entry) => entry.lifecycle === 'paused' || entry.lifecycle === 'archived') && <label className="online-resume-history-toggle online-resume-controls"><input type="checkbox" checked={showPastDirections} onChange={(event) => setShowPastDirections(event.target.checked)} />查看已暂停和归档的目标</label>}
        {directions.map((direction) => <article key={direction.id} className={`online-resume-entry${direction.lifecycle === 'paused' || direction.lifecycle === 'archived' ? ' online-resume-direction-inactive' : ''}`}><div className="online-resume-entry-heading"><h3>{direction.label}</h3>{!preview && <span className="online-resume-controls"><Pill tone={lifecycleTone[direction.lifecycle]}>{lifecycleLabels[direction.lifecycle]}</Pill></span>}</div><p className="online-resume-direction-meta">{[direction.criteria.locations.join(' / '), direction.criteria.industries.join(' / '), direction.criteria.seniority.join(' / '), direction.criteria.salary_min !== null ? `${direction.criteria.salary_currency ?? ''} ${direction.criteria.salary_min} — ${direction.criteria.salary_max ?? '不限'}` : '薪资面议'].filter(Boolean).join(' · ')}</p>
          {direction.criteria.role_keywords.some((keyword) => keyword !== direction.label) && <p className="online-resume-description">{direction.criteria.role_keywords.filter((keyword) => keyword !== direction.label).join(' / ')}</p>}
          {!!direction.criteria.technologies.length && <p className="online-resume-direction-meta">技术：{direction.criteria.technologies.join('、')}</p>}
          {!!direction.criteria.work_modes.length && <p className="online-resume-direction-meta">{direction.criteria.work_modes.map((mode) => ({ onsite: '现场办公', hybrid: '混合办公', remote: '远程办公' }[mode])).join(' · ')}</p>}
          {!!direction.criteria.exclusions.length && <p className="online-resume-direction-meta">不考虑：{direction.criteria.exclusions.join('、')}</p>}
          {!preview && <div className="online-resume-entry-actions online-resume-controls"><button onClick={() => editDirection(direction)} aria-label={`编辑 ${direction.label}`}><Pencil size={14} />编辑</button><details><summary>更多</summary><div className="flex flex-wrap gap-3 py-2">{direction.lifecycle !== 'active' && <button onClick={() => run(() => setCareerDirectionLifecycle(direction.id, profile.version, 'active'), '已设为当前目标')}>设为当前目标</button>}{direction.lifecycle === 'active' && <button onClick={() => run(() => setCareerDirectionLifecycle(direction.id, profile.version, 'paused'), '已暂停')}>暂停</button>}{direction.lifecycle !== 'archived' && <button onClick={() => run(() => setCareerDirectionLifecycle(direction.id, profile.version, 'archived'), '已归档')}>归档</button>}</div></details></div>}
        </article>)}
        {directionEditor && <DirectionEditor key={directionEditor.key} initial={directionEditor.direction} busy={busy} onClose={() => setDirectionEditor(null)} onSave={async (direction) => { if (await run(() => saveCareerDirection({ profileVersion: profile.version, direction, directionId: directionEditor.direction?.id }), '期望职位已保存')) setDirectionEditor(null); }} />}
      </ResumeSection>
      {factSection('experience', '工作 / 实习经历', '添加公司、岗位及你的职责与成果')}
      {factSection('project', '项目经历', '添加项目背景、承担角色和实际成果')}
      {factSection('education', '教育经历', '添加学校、学历、专业与在校经历')}
      {factSection('certificate', '资格证书', '添加证书名称、颁发机构与取得时间')}
      {factSection('organization', '社团 / 组织经历', '添加参加的组织与承担的工作')}
      {factSection('volunteer', '志愿者经历', '添加志愿活动、服务时长与经历')}
      {factSection('skill', '专业技能', '描述你的专业技能及应用经验')}
      {factSection('achievement', '奖项与成果', '添加奖项、论文与其他成果')}
      {preview && <p className="online-resume-preview-note">预览仅展示已确认内容；导出时隐藏操作、空区块与侧栏。</p>}
    </article>
    <aside className="online-resume-aside">
      <section><div className="online-resume-aside-heading"><h2>附件简历</h2><Link to="/artifacts" aria-label="管理附件简历"><Plus size={16} /></Link></div>
        {resumesQuery.isPending ? <p role="status">正在读取附件…</p> : resumesQuery.isError ? <button onClick={() => resumesQuery.refetch()}>读取失败，重试</button> : !resumesQuery.data?.length ? <p>上传已有简历，可以导入内容并逐项确认。</p> : <ul>{resumesQuery.data.map((resume) => <li key={resume.id}><FileText size={20} /><div><Link to={`/artifacts/${encodeURIComponent(resume.id)}`}>{resume.title}</Link><small>{resume.is_default ? '默认简历 · ' : ''}{new Date(resume.updated_at).toLocaleDateString('zh-CN')}</small></div></li>)}</ul>}
        <Link className="online-resume-aside-link" to="/artifacts">上传与管理附件 →</Link>
      </section>
      <section><h2>导入与更新</h2>{draftsQuery.isError ? <button onClick={() => draftsQuery.refetch()}>更新读取失败，重试</button> : <><p>{pendingDrafts.length ? `${pendingDrafts.length} 份导入或协作建议等待确认。确认前不会修改个人档案。` : '导入简历和协作产生的修改建议，会在这里等待你确认。'}</p><button className="online-resume-aside-link" onClick={() => review(true)}>核对更新{pendingDrafts.length > 0 && `（${pendingDrafts.length}）`} →</button></>}
      </section>
      <section className="online-resume-copilot"><Bot size={20} /><h2>一起梳理经历</h2><p>让 Copilot 帮你梳理经历、打磨表达。</p><Link to={copilotObjectHandoffHref('career_profile', profile.id, '个人经历档案')}>与 Copilot 协作 →</Link></section>
      <button className="online-resume-refresh" onClick={refresh}><RefreshCw size={13} />刷新档案</button>
    </aside>
    <Modal open={reviewOpen} onClose={() => review(false)} title="核对档案更新" width={920}>
      {draftsQuery.isPending ? <Spinner /> : draftsQuery.isError ? <div role="alert">更新暂时无法读取。<Btn onClick={() => draftsQuery.refetch()}>重试</Btn></div> : !selectedDraft ? <EmptyState icon={<Check size={28} />} title="没有待确认更新" description="正式内容已在个人档案中展示。" /> : <div className="profile-drafts">
        <nav aria-label="待确认来源">{pendingDrafts.map((draft) => <button key={draft.id} aria-pressed={selectedDraft.id === draft.id} onClick={() => setSelectedDraftId(draft.id)}><strong>{draftSources[draft.source_kind]}</strong><small>{displayDate(draft.created_at)}</small><small>{draft.candidates.filter((item) => item.status === 'pending').length} 项待确认</small></button>)}</nav>
        <section aria-label="核对档案更新"><p className="mb-4 text-xs text-stone-500">逐项确认；重复或冲突内容会单独标记。</p><DraftSummary draft={selectedDraft} busy={busy} onDecision={(item, decision) => void run(() => resolveCareerProfileCandidates({ draft: selectedDraft, profileVersion: profile.version, decisions: [{ item, decision }] }), decision === 'accept' ? '已加入档案' : '已拒绝')} /><div className="mt-5 flex flex-wrap gap-2">
          {selectedDraft.candidates.some((item) => item.status === 'pending' && item.conflict_kind === 'none') && <Btn size="sm" disabled={busy} onClick={() => run(() => resolveCareerProfileCandidates({ draft: selectedDraft, profileVersion: profile.version, decisions: selectedDraft.candidates.filter((item) => item.status === 'pending' && item.conflict_kind === 'none').map((item) => ({ item, decision: 'accept' as const })) }), '已接受无冲突更新')}>接受无冲突项</Btn>}
          <Btn kind="ghost" size="sm" disabled={busy} onClick={() => run(() => resolveCareerProfileCandidates({ draft: selectedDraft, profileVersion: profile.version, decisions: selectedDraft.candidates.filter((item) => item.status === 'pending').map((item) => ({ item, decision: 'reject' as const })) }), '已拒绝剩余更新')}>拒绝剩余项</Btn>
        </div></section>
      </div>}
    </Modal>
    <ConfirmDialog open={!!deleteFact} title="删除这项档案内容？" description={deleteFact ? factTitle(deleteFact.value) : ''} confirmText="删除" danger loading={busy} onCancel={() => setDeleteFact(null)} onConfirm={async () => { if (deleteFact && await run(() => removePersonalFact(deleteFact.id, profile.version), '档案内容已删除')) setDeleteFact(null); }} />
  </div>;
}
