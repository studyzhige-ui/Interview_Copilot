import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, Check, FileText, RefreshCw } from 'lucide-react';
import { createArtifact } from '@/api/artifacts';
import { extractErr } from '@/api/client';
import { listJobOpportunities } from '@/api/careerProcess';
import {
  confirmOfferTerms,
  getCurrentOffer,
  OfferConfirmationError,
  recordOffer,
} from '@/api/offers';
import { Btn } from '@/components/ui/Btn';
import { EmptyState } from '@/components/ui/EmptyState';
import { Modal } from '@/components/ui/Modal';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import type {
  OfferConfirmationRequired,
  OfferCurrent,
  OfferSourceInput,
  OfferTermsInput,
} from '@/types/career';
import { csv, displayDate, FormItem, SelectInput, TextArea, TextInput } from './CareerFields';

interface OfferForm {
  position_title: string;
  location: string;
  employment_type: string;
  base_salary_amount: string;
  currency: string;
  pay_period: string;
  tax_basis: string;
  bonus_text: string;
  equity_text: string;
  benefits: string;
  probation_text: string;
  start_date: string;
  response_deadline: string;
  formality: string;
  original_text: string;
}

function latestExcerpt(current: OfferCurrent | null): Record<string, unknown> {
  if (!current) return {};
  const excerpts = Object.values(current.offer.source_excerpts_json);
  return excerpts.find((entry) => {
    const source = entry.source;
    return source && typeof source === 'object'
      && (source as Record<string, unknown>).identity === current.offer.last_source_identity;
  }) ?? excerpts.at(-1) ?? {};
}

function localDateTimeInput(value: unknown): string {
  if (!value) return '';
  const parsed = new Date(String(value));
  if (Number.isNaN(parsed.getTime())) return '';
  const local = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function offerForm(current: OfferCurrent | null): OfferForm {
  const terms = current?.offer.terms_json ?? {};
  const excerpt = latestExcerpt(current);
  return {
    position_title: String(terms.position_title ?? ''), location: String(terms.location ?? ''),
    employment_type: String(terms.employment_type ?? ''), base_salary_amount: String(terms.base_salary_amount ?? ''),
    currency: String(terms.currency ?? ''), pay_period: String(terms.pay_period ?? ''), tax_basis: String(terms.tax_basis ?? ''),
    bonus_text: String(terms.bonus_text ?? ''), equity_text: String(terms.equity_text ?? ''),
    benefits: Array.isArray(terms.benefits) ? terms.benefits.join('，') : '', probation_text: String(terms.probation_text ?? ''),
    start_date: String(terms.start_date ?? ''), response_deadline: localDateTimeInput(terms.response_deadline),
    formality: String(excerpt.formality ?? 'written'), original_text: String(excerpt.original_text ?? ''),
  };
}

function optional(value: string): string | undefined { return value.trim() || undefined; }

function termsFromForm(form: OfferForm): OfferTermsInput {
  const salaryStarted = Boolean(form.base_salary_amount || form.currency || form.pay_period || form.tax_basis);
  return {
    position_title: optional(form.position_title), location: optional(form.location), employment_type: optional(form.employment_type),
    ...(salaryStarted ? {
      base_salary_amount: form.base_salary_amount,
      currency: form.currency.trim().toUpperCase(),
      pay_period: form.pay_period as NonNullable<OfferTermsInput['pay_period']>,
      tax_basis: form.tax_basis as NonNullable<OfferTermsInput['tax_basis']>,
    } : {}),
    bonus_text: optional(form.bonus_text), equity_text: optional(form.equity_text),
    benefits: form.benefits.trim() ? csv(form.benefits) : undefined,
    probation_text: optional(form.probation_text), start_date: optional(form.start_date),
    response_deadline: form.response_deadline ? new Date(form.response_deadline).toISOString() : undefined,
    response_deadline_text: form.response_deadline || undefined,
    response_deadline_timezone: form.response_deadline
      ? Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
      : undefined,
    formality: form.formality as OfferTermsInput['formality'], original_text: form.original_text.trim(),
  };
}

function OfferEditor({
  initial,
  busy,
  onSave,
}: { initial: OfferCurrent | null; busy: boolean; onSave: (terms: OfferTermsInput) => void }) {
  const [form, setForm] = useState<OfferForm>(() => offerForm(initial));
  const update = (key: keyof OfferForm, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const salaryValid = !form.base_salary_amount && !form.currency && !form.pay_period && !form.tax_basis
    || Boolean(form.base_salary_amount && form.currency.length === 3 && form.pay_period && form.tax_basis);
  return <section className="rounded-xl border border-stone-200 bg-white shadow-xs">
    <div className="border-b border-stone-100 px-5 py-4"><h2 className="font-semibold text-stone-800">{initial ? '补充或更新条款' : '记录 Offer'}</h2><p className="mt-1 text-xs text-stone-500">新原文会显式保存为 Offer 来源材料；若与当前条款不同，会先展示差异并等待确认。</p></div>
    <div className="grid gap-4 p-5 sm:grid-cols-2">
      <FormItem label="职位名称"><TextInput value={form.position_title} onChange={(e) => update('position_title', e.target.value)} /></FormItem>
      <FormItem label="工作地点"><TextInput value={form.location} onChange={(e) => update('location', e.target.value)} /></FormItem>
      <FormItem label="雇佣类型"><TextInput value={form.employment_type} onChange={(e) => update('employment_type', e.target.value)} placeholder="全职 / 合同 / 实习" /></FormItem>
      <FormItem label="Offer 形式"><SelectInput value={form.formality} onChange={(e) => update('formality', e.target.value)}><option value="written">书面</option><option value="verbal_confirmed">口头已确认</option><option value="verbal_pending_written">口头，等待书面</option></SelectInput></FormItem>
      <FormItem label="基本薪资金额"><TextInput type="number" min="0" value={form.base_salary_amount} onChange={(e) => update('base_salary_amount', e.target.value)} /></FormItem>
      <FormItem label="币种"><TextInput maxLength={3} placeholder="CNY" value={form.currency} onChange={(e) => update('currency', e.target.value)} /></FormItem>
      <FormItem label="薪资周期"><SelectInput value={form.pay_period} onChange={(e) => update('pay_period', e.target.value)}><option value="">未填写</option><option value="hourly">时薪</option><option value="monthly">月薪</option><option value="annual">年薪</option><option value="total">总额</option></SelectInput></FormItem>
      <FormItem label="税前 / 税后"><SelectInput value={form.tax_basis} onChange={(e) => update('tax_basis', e.target.value)}><option value="">未填写</option><option value="gross">税前</option><option value="net">税后</option><option value="unspecified">未说明</option></SelectInput></FormItem>
      {!salaryValid && <div className="sm:col-span-2 rounded-md bg-warning-50 px-3 py-2 text-xs text-warning-700">薪资一旦填写，需要同时提供金额、币种、周期和税制口径。</div>}
      <FormItem label="奖金"><TextArea rows={2} value={form.bonus_text} onChange={(e) => update('bonus_text', e.target.value)} /></FormItem>
      <FormItem label="股权"><TextArea rows={2} value={form.equity_text} onChange={(e) => update('equity_text', e.target.value)} /></FormItem>
      <FormItem label="福利" hint="用逗号分隔"><TextArea rows={2} value={form.benefits} onChange={(e) => update('benefits', e.target.value)} /></FormItem>
      <FormItem label="试用期"><TextArea rows={2} value={form.probation_text} onChange={(e) => update('probation_text', e.target.value)} /></FormItem>
      <FormItem label="入职日期"><TextInput type="date" value={form.start_date} onChange={(e) => update('start_date', e.target.value)} /></FormItem>
      <FormItem label="回复截止"><TextInput type="datetime-local" value={form.response_deadline} onChange={(e) => update('response_deadline', e.target.value)} /></FormItem>
      <div className="sm:col-span-2"><FormItem label="Offer 原文" hint="结构化条款不会替代原文"><TextArea rows={10} value={form.original_text} onChange={(e) => update('original_text', e.target.value)} /></FormItem></div>
      <div className="sm:col-span-2 flex justify-end"><Btn loading={busy} disabled={!form.original_text.trim() || !salaryValid} onClick={() => onSave(termsFromForm(form))}>{initial ? '检查并提交更新' : '保存 Offer'}</Btn></div>
    </div>
  </section>;
}

function DiffBlock({ confirmation }: { confirmation: OfferConfirmationRequired }) {
  const rows = [
    ...Object.entries(confirmation.diff.added).map(([key, value]) => ({ key, before: undefined, after: value, kind: '新增' })),
    ...Object.entries(confirmation.diff.changed).map(([key, value]) => ({ key, before: value.current, after: value.proposed, kind: '变化' })),
    ...Object.entries(confirmation.diff.removed).map(([key, value]) => ({ key, before: value, after: undefined, kind: '移除' })),
  ];
  return <div className="space-y-2">{rows.map((row) => <div key={row.key} className="rounded-md border border-stone-200 p-3 text-xs"><div className="mb-2 flex items-center justify-between"><span className="font-medium text-stone-700">{termLabels[row.key] ?? row.key}</span><Pill tone={row.kind === '移除' ? 'danger' : row.kind === '新增' ? 'success' : 'warn'}>{row.kind}</Pill></div>{row.before !== undefined && <div className="text-stone-500">原值：{JSON.stringify(row.before)}</div>}{row.after !== undefined && <div className="mt-1 text-stone-800">新值：{JSON.stringify(row.after)}</div>}</div>)}</div>;
}

interface PendingConfirmation {
  confirmation: OfferConfirmationRequired;
  terms: OfferTermsInput;
  source: OfferSourceInput;
}

const termLabels: Record<string, string> = {
  position_title: '职位', location: '地点', employment_type: '雇佣类型',
  base_salary_amount: '基本薪资', currency: '币种', pay_period: '薪资周期', tax_basis: '税制口径',
  bonus_text: '奖金', equity_text: '股权', benefits: '福利', probation_text: '试用期',
  start_date: '入职日期', response_deadline: '回复截止', response_deadline_text: '回复截止原始时间',
  response_deadline_timezone: '回复截止来源时区', additional_terms: '其他条款',
};

export function OfferPage() {
  const { opportunityId } = useParams<{ opportunityId: string }>();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<PendingConfirmation | null>(null);
  const offerQuery = useQuery({ queryKey: ['offer', opportunityId], queryFn: () => getCurrentOffer(opportunityId!), enabled: Boolean(opportunityId), retry: false });
  const jobsQuery = useQuery({ queryKey: ['job-opportunities'], queryFn: () => listJobOpportunities(true) });
  const job = jobsQuery.data?.find((item) => item.id === opportunityId);

  if (!opportunityId) return <div className="p-6"><EmptyState title="缺少岗位标识" /></div>;
  if (offerQuery.isLoading) return <div className="flex items-center gap-2 p-6 text-sm text-stone-500"><Spinner size={15} />正在加载 Offer…</div>;

  const refresh = async () => queryClient.invalidateQueries({ queryKey: ['offer', opportunityId] });
  const save = async (terms: OfferTermsInput) => {
    setBusy(true);
    try {
      const sourceArtifact = await createArtifact({
        operationKey: crypto.randomUUID(), kind: 'offer_source',
        version: { title: `${job?.company_name ?? '岗位'} Offer 原文`, content_text: terms.original_text, content_format: 'plain_text', provenance: { source_owner_type: 'job_opportunity', source_owner_id: opportunityId } },
      });
      const source: OfferSourceInput = {
        kind: 'artifact', identity: sourceArtifact.current_version.id,
        version: String(sourceArtifact.current_version.version_no), observed_at: new Date().toISOString(),
      };
      try {
        await recordOffer({ opportunityId, operationKey: crypto.randomUUID(), terms, source });
        await refresh(); toast.success('Offer 条款已保存');
      } catch (error) {
        if (error instanceof OfferConfirmationError) {
          setPending({ confirmation: error.confirmation, terms, source });
          return;
        }
        throw error;
      }
    } catch (error) { toast.error(extractErr(error)); }
    finally { setBusy(false); }
  };

  const confirm = async (resolution: 'supplement' | 'replace') => {
    if (!pending) return;
    setBusy(true);
    try {
      await confirmOfferTerms({
        opportunityId, offerId: pending.confirmation.offer_id, operationKey: crypto.randomUUID(),
        expectedCurrentToken: pending.confirmation.current_token, resolution, terms: pending.terms,
        candidateSource: pending.source,
      });
      setPending(null); await refresh(); toast.success('Offer 条款已按你的选择更新');
    } catch (error) { toast.error(extractErr(error)); await refresh(); }
    finally { setBusy(false); }
  };

  const current = offerQuery.data ?? null;
  const excerpt = latestExcerpt(current);
  return <div className="mx-auto max-w-5xl space-y-5 p-4 md:p-6">
    <header className="flex flex-wrap items-start justify-between gap-4"><div><Link to="/career-process" className="mb-2 inline-flex items-center gap-1 text-xs text-stone-500 hover:text-primary-700"><ArrowLeft size={13} />返回求职进程</Link><h1 className="text-xl font-semibold text-stone-800">{job ? `${job.company_name} · ${job.job_title}` : 'Offer 条款'}</h1><p className="mt-1 text-sm text-stone-500">保存原文、结构化条款与每次变化的确认依据。</p></div><Btn kind="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={refresh}>刷新</Btn></header>
    {current && <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs"><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><FileText size={17} className="text-primary-700" /><h2 className="font-semibold text-stone-800">当前 Offer</h2><Pill tone="success">{String(excerpt.formality ?? '已记录')}</Pill></div><span className="text-xs text-stone-400">更新于 {displayDate(current.offer.updated_at)}</span></div><div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">{Object.entries(current.offer.terms_json).map(([key, value]) => <div key={key} className="rounded-md bg-stone-50 px-3 py-2"><div className="text-[11px] text-stone-400">{termLabels[key] ?? key}</div><div className="mt-1 break-words text-sm text-stone-700">{Array.isArray(value) ? value.join('、') : String(value ?? '—')}</div></div>)}</div>{typeof excerpt.original_text === 'string' && excerpt.original_text && <details className="mt-4 rounded-md border border-stone-100 bg-stone-50 px-3 py-2"><summary className="cursor-pointer text-xs font-medium text-stone-600">查看当前来源原文</summary><pre className="mt-3 whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-stone-600">{excerpt.original_text}</pre></details>}</section>}
    <OfferEditor key={current?.offer.updated_at ?? 'new'} initial={current} busy={busy} onSave={save} />
    <Modal open={Boolean(pending)} onClose={() => setPending(null)} title="确认 Offer 条款变化" width={700} footer={<><Btn kind="ghost" onClick={() => setPending(null)} disabled={busy}>暂不更新</Btn><Btn kind="outline" loading={busy} onClick={() => confirm('supplement')}>补充现有条款</Btn><Btn loading={busy} onClick={() => confirm('replace')} icon={<Check size={14} />}>替换为新条款</Btn></>}>
      {pending && <><div className="mb-4 flex items-start gap-2 rounded-md bg-warning-50 p-3 text-xs leading-relaxed text-warning-700"><AlertTriangle size={15} className="mt-0.5 shrink-0" />系统检测到当前 Offer 与新材料存在差异。请先核对，再明确选择补充或替换；本次点击会作为已登录用户在产品内的确认记录。</div><DiffBlock confirmation={pending.confirmation} /></>}
    </Modal>
  </div>;
}
