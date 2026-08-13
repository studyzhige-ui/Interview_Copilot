import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, BarChart3, Bell, FileCheck2, Scale, X } from 'lucide-react';
import {
  compareOffers,
  createNegotiationDraft,
  dismissReminder,
  getFunnelAnalysis,
  getNextActionAgenda,
  getNotificationPreference,
  listReminderInbox,
  updateNotificationPreference,
  type OfferComparisonInput,
} from '@/api/careerInsights';
import { extractErr } from '@/api/client';
import { listCurrentOffers } from '@/api/offers';
import { Btn } from '@/components/ui/Btn';
import { EmptyState } from '@/components/ui/EmptyState';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import type { NextActionAgendaItem, NotificationPreference, OfferAnalysis } from '@/types/career';
import { displayDate, FormItem, TextArea, TextInput } from './CareerFields';

const bucketLabels: Record<NextActionAgendaItem['bucket'], string> = {
  conflict: '存在时间冲突', today: '今天', upcoming: '即将到来', unscheduled_planned: '已计划未排期', suggested: '待决定建议',
};
const stageLabels = { applied: '已投递', in_process: '进入流程', offer: '收到 Offer', terminal: '明确结束' } as const;

function ActionAgenda() {
  const agenda = useQuery({ queryKey: ['career-insights', 'agenda'], queryFn: getNextActionAgenda });
  if (agenda.isLoading) return <Spinner />;
  const items = agenda.data?.items ?? [];
  return <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
    <div className="mb-4 flex items-center gap-2"><FileCheck2 size={17} className="text-primary-700" /><h2 className="font-semibold text-stone-800">行动总览</h2></div>
    {items.length === 0 ? <EmptyState title="暂无跨会话行动" /> : <div className="grid gap-3 md:grid-cols-2">{items.map((item) => <article key={item.action.id} className={`rounded-lg border p-3 ${item.bucket === 'conflict' ? 'border-warning-300 bg-warning-50' : 'border-stone-200'}`}>
      <div className="flex items-start justify-between gap-3"><p className="text-sm font-medium text-stone-800">{item.action.content}</p><Pill tone={item.bucket === 'conflict' ? 'warn' : item.action.status === 'planned' ? 'primary' : 'neutral'}>{bucketLabels[item.bucket]}</Pill></div>
      <p className="mt-2 text-xs text-stone-500">{item.action.time_kind === 'fixed' ? `开始 ${displayDate(item.action.starts_at)}` : item.action.time_kind === 'deadline' ? `截止 ${displayDate(item.action.due_at)}` : '灵活安排'}</p>
      {(item.overdue || item.due_soon || item.duplicate_action_ids.length > 0) && <div className="mt-2 flex flex-wrap gap-1">{item.overdue && <Pill tone="danger">已逾期</Pill>}{item.due_soon && <Pill tone="warn">72 小时内</Pill>}{item.duplicate_action_ids.length > 0 && <Pill tone="neutral">疑似重复 {item.duplicate_action_ids.length}</Pill>}</div>}
    </article>)}</div>}
  </section>;
}

function ReminderSettings() {
  const queryClient = useQueryClient();
  const preferenceQuery = useQuery({ queryKey: ['career-insights', 'notification-preference'], queryFn: getNotificationPreference });
  const inboxQuery = useQuery({ queryKey: ['career-insights', 'reminder-inbox'], queryFn: listReminderInbox });
  const [draft, setDraft] = useState<NotificationPreference | null>(null);
  const [busy, setBusy] = useState(false);
  const current = draft ?? preferenceQuery.data;
  if (!current) return <Spinner />;
  const save = async () => {
    setBusy(true);
    try { const updated = await updateNotificationPreference(current); setDraft(updated); await queryClient.invalidateQueries({ queryKey: ['career-insights'] }); toast.success('通知设置已保存'); }
    catch (error) { toast.error(extractErr(error)); }
    finally { setBusy(false); }
  };
  const update = <K extends keyof NotificationPreference>(key: K, value: NotificationPreference[K]) => setDraft({ ...current, [key]: value });
  return <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
    <div className="mb-4 flex items-center gap-2"><Bell size={17} className="text-primary-700" /><h2 className="font-semibold text-stone-800">行动提醒</h2><Pill tone="neutral">NextAction 通知安排</Pill></div>
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <FormItem label="启用应用内提醒"><label className="flex h-10 items-center gap-2 text-sm text-stone-700"><input type="checkbox" checked={current.enabled} onChange={(event) => update('enabled', event.target.checked)} />启用</label></FormItem>
      <FormItem label="时区"><TextInput value={current.timezone} onChange={(event) => update('timezone', event.target.value)} /></FormItem>
      <FormItem label="安静时段开始"><TextInput type="time" value={current.quiet_start ?? ''} onChange={(event) => update('quiet_start', event.target.value || null)} /></FormItem>
      <FormItem label="安静时段结束"><TextInput type="time" value={current.quiet_end ?? ''} onChange={(event) => update('quiet_end', event.target.value || null)} /></FormItem>
    </div>
    <div className="mt-3 flex justify-end"><Btn size="sm" loading={busy} onClick={save}>保存通知设置</Btn></div>
    {(inboxQuery.data?.length ?? 0) > 0 && <div className="mt-5 border-t border-stone-100 pt-4"><h3 className="mb-2 text-sm font-medium text-stone-700">已送达提醒</h3><div className="space-y-2">{inboxQuery.data?.map((action) => <div key={action.id} className="flex items-center justify-between gap-3 rounded-md bg-primary-50 px-3 py-2"><div><p className="text-sm text-stone-800">{action.content}</p><p className="text-[11px] text-stone-500">送达于 {displayDate(action.reminder_delivered_at)}</p></div><button aria-label="关闭提醒" onClick={async () => { try { await dismissReminder(action); await inboxQuery.refetch(); } catch (error) { toast.error(extractErr(error)); } }}><X size={15} /></button></div>)}</div></div>}
  </section>;
}

function FunnelPanel() {
  const funnel = useQuery({ queryKey: ['career-insights', 'funnel'], queryFn: () => getFunnelAnalysis() });
  if (funnel.isLoading) return <Spinner />;
  if (!funnel.data) return <EmptyState title="漏斗分析暂不可用" />;
  const { coverage, groups } = funnel.data;
  return <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
    <div className="mb-4 flex items-center gap-2"><BarChart3 size={17} className="text-primary-700" /><h2 className="font-semibold text-stone-800">历史岗位漏斗</h2><Pill tone="neutral">{coverage.sample_count} 个确证投递样本</Pill></div>
    {coverage.sample_count === 0 ? <EmptyState title="还没有确证的投递样本" /> : <div className="space-y-3">{groups.map((group) => <article key={[group.direction_id, group.submitted_artifact_version_id, group.channel, group.calendar_month].join(':')} className="rounded-lg border border-stone-200 p-3">
      <div className="mb-3 flex flex-wrap gap-2"><Pill tone="primary">{group.direction_label ?? '方向未记录'}</Pill><Pill>{group.channel ?? '渠道未记录'}</Pill><Pill>{group.calendar_month}</Pill><Pill>{group.submitted_artifact_version_id ? `材料 ${group.submitted_artifact_version_id.slice(-8)}` : '材料版本未记录'}</Pill></div>
      <div className="grid gap-2 sm:grid-cols-4">{group.stages.map((stage) => <div key={stage.stage} className="rounded-md bg-stone-50 p-3"><div className="text-xs text-stone-500">{stageLabels[stage.stage]}</div><div className="mt-1 text-lg font-semibold text-stone-800">{Math.round(stage.conversion_from_sample * 100)}%</div><div className="text-[11px] text-stone-400">{stage.reached}/{group.sample_job_ids.length}{stage.median_wait_hours !== null ? ` · 中位 ${stage.median_wait_hours}h` : ''}</div></div>)}</div>
    </article>)}</div>}
    <div className="mt-4 rounded-lg bg-warning-50 p-3 text-xs leading-relaxed text-warning-700"><div className="flex gap-2"><AlertTriangle size={15} className="mt-0.5 shrink-0" /><div><p>{funnel.data.interpretation_limit}</p><p className="mt-1">混杂因素：{funnel.data.confounders.join('、')}</p>{funnel.data.missing_source_notes.map((note) => <p key={note} className="mt-1">数据覆盖：{note}</p>)}</div></div></div>
  </section>;
}

interface OfferAssumptionDraft { taxRate: string; jurisdiction: string; bonus: string; equity: string; currency: string; equityMethod: string }
const emptyAssumption = (): OfferAssumptionDraft => ({ taxRate: '', jurisdiction: '', bonus: '', equity: '', currency: '', equityMethod: '' });
const localDateTimeNow = () => {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
};

function OfferPanel() {
  const offersQuery = useQuery({ queryKey: ['career-insights', 'offers'], queryFn: listCurrentOffers });
  const [selected, setSelected] = useState<string[]>([]);
  const [baseCurrency, setBaseCurrency] = useState('CNY');
  const [rateCurrency, setRateCurrency] = useState('USD');
  const [rate, setRate] = useState('');
  const [sourceIdentity, setSourceIdentity] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [sourceObservedAt, setSourceObservedAt] = useState(localDateTimeNow);
  const [constraints, setConstraints] = useState('');
  const [assumptions, setAssumptions] = useState<Record<string, OfferAssumptionDraft>>({});
  const [saveArtifact, setSaveArtifact] = useState(false);
  const [result, setResult] = useState<OfferAnalysis | null>(null);
  const [objective, setObjective] = useState('');
  const [draft, setDraft] = useState<{ text: string; note: string; artifactId: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const offers = offersQuery.data ?? [];
  const updateAssumption = (offerId: string, key: keyof OfferAssumptionDraft, value: string) => setAssumptions((current) => ({ ...current, [offerId]: { ...(current[offerId] ?? emptyAssumption()), [key]: value } }));
  const run = async () => {
    const hasQuantifiedInput = selected.some((id) => {
      const item = assumptions[id];
      return Boolean(item?.taxRate || item?.jurisdiction || item?.bonus || item?.equity || item?.equityMethod);
    });
    if ((rate || hasQuantifiedInput) && !sourceIdentity.trim()) { toast.warn('所有汇率、税务、奖金或股权假设都必须保留真实来源'); return; }
    const observed = new Date(sourceObservedAt);
    if (sourceIdentity.trim() && Number.isNaN(observed.getTime())) { toast.warn('请填写有效的来源观察时点'); return; }
    if (sourceUrl.trim()) { try { const parsed = new URL(sourceUrl.trim()); if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error(); } catch { toast.warn('来源链接必须是有效的 HTTP(S) 地址'); return; } }
    for (const id of selected) {
      const item = assumptions[id];
      if (Boolean(item?.taxRate) !== Boolean(item?.jurisdiction)) { toast.warn('有效税率和税务辖区需要同时填写'); return; }
      if (item?.bonus && !item.currency) { toast.warn('年化奖金假设需要填写币种'); return; }
      if (item?.equity && (!item.currency || !item.equityMethod)) { toast.warn('股权估值需要币种和估值方法'); return; }
    }
    const actualSource = sourceIdentity.trim() ? { identity: sourceIdentity.trim(), observed_at: observed.toISOString(), ...(sourceUrl.trim() ? { url: sourceUrl.trim() } : {}) } : null;
    if (rate && (!actualSource || rateCurrency.length !== 3)) { toast.warn('汇率必须保留真实来源、观察时点和三位币种'); return; }
    const input: OfferComparisonInput = {
      offer_ids: selected, base_currency: baseCurrency.toUpperCase(),
      exchange_rates: rate && actualSource ? [{ currency: rateCurrency.toUpperCase(), rate_to_base: rate, source: actualSource }] : [],
      tax_assumptions: selected.flatMap((id) => { const item = assumptions[id]; return item?.taxRate && item.jurisdiction && actualSource ? [{ offer_id: id, effective_rate: String(Number(item.taxRate) / 100), jurisdiction: item.jurisdiction, source: actualSource }] : []; }),
      equity_assumptions: selected.flatMap((id) => { const item = assumptions[id]; return item?.equity && item.currency && item.equityMethod && actualSource ? [{ offer_id: id, annual_value: item.equity, currency: item.currency, method: item.equityMethod, source: actualSource }] : []; }),
      bonus_assumptions: selected.flatMap((id) => { const item = assumptions[id]; return item?.bonus && item.currency && actualSource ? [{ offer_id: id, annual_value: item.bonus, currency: item.currency, basis: '用户本次明确输入的年化奖金假设', source: actualSource }] : []; }),
      user_constraints: constraints.split('\n').map((value) => value.trim()).filter(Boolean), save_artifact: saveArtifact, operation_key: saveArtifact ? crypto.randomUUID() : undefined,
    };
    setBusy(true); try { setResult(await compareOffers(input)); toast.success(saveArtifact ? '比较报告已保存为材料' : '比较报告已生成'); } catch (error) { toast.error(extractErr(error)); } finally { setBusy(false); }
  };
  return <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
    <div className="mb-4 flex items-center gap-2"><Scale size={17} className="text-primary-700" /><h2 className="font-semibold text-stone-800">Offer 比较与协商</h2><Pill tone="neutral">按需执行</Pill></div>
    {offers.length === 0 ? <EmptyState title="还没有可比较的当前 Offer" /> : <>
      <div className="space-y-3">{offers.map((entry) => { const checked = selected.includes(entry.offer.id); const item = assumptions[entry.offer.id] ?? emptyAssumption(); const hasBonus = Boolean(entry.offer.terms_json.bonus_text); const hasEquity = Boolean(entry.offer.terms_json.equity_text); return <article key={entry.offer.id} className={`rounded-lg border p-3 ${checked ? 'border-primary-300 bg-primary-50/30' : 'border-stone-200'}`}><label className="flex items-center gap-2 text-sm font-medium text-stone-800"><input type="checkbox" checked={checked} onChange={() => setSelected((current) => checked ? current.filter((id) => id !== entry.offer.id) : [...current, entry.offer.id])} />{entry.company_name} · {entry.job_title}</label>{checked && <div className="mt-3 grid gap-3 sm:grid-cols-3"><FormItem label="有效税率 %"><TextInput type="number" min="0" max="100" value={item.taxRate} onChange={(event) => updateAssumption(entry.offer.id, 'taxRate', event.target.value)} /></FormItem><FormItem label="税务辖区"><TextInput value={item.jurisdiction} onChange={(event) => updateAssumption(entry.offer.id, 'jurisdiction', event.target.value)} /></FormItem>{(hasBonus || hasEquity) && <FormItem label="估值币种"><TextInput maxLength={3} value={item.currency} onChange={(event) => updateAssumption(entry.offer.id, 'currency', event.target.value.toUpperCase())} /></FormItem>}{hasBonus && <FormItem label="年化奖金假设"><TextInput type="number" min="0" value={item.bonus} onChange={(event) => updateAssumption(entry.offer.id, 'bonus', event.target.value)} /></FormItem>}{hasEquity && <FormItem label="年化股权估值"><TextInput type="number" min="0" value={item.equity} onChange={(event) => updateAssumption(entry.offer.id, 'equity', event.target.value)} /></FormItem>}{hasEquity && <FormItem label="股权估值方法"><TextInput value={item.equityMethod} onChange={(event) => updateAssumption(entry.offer.id, 'equityMethod', event.target.value)} /></FormItem>}</div>}</article>; })}</div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3"><FormItem label="展示币种"><TextInput maxLength={3} value={baseCurrency} onChange={(event) => setBaseCurrency(event.target.value.toUpperCase())} /></FormItem><FormItem label="换算币种"><TextInput maxLength={3} value={rateCurrency} onChange={(event) => setRateCurrency(event.target.value.toUpperCase())} /></FormItem><FormItem label={`1 ${rateCurrency || '原币'} = 多少 ${baseCurrency}`}><TextInput type="number" min="0" value={rate} onChange={(event) => setRate(event.target.value)} /></FormItem><FormItem label="外部数据来源"><TextInput value={sourceIdentity} onChange={(event) => setSourceIdentity(event.target.value)} placeholder="例如央行每日汇率" /></FormItem><FormItem label="来源链接"><TextInput type="url" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} /></FormItem><FormItem label="观察时点"><TextInput type="datetime-local" value={sourceObservedAt} onChange={(event) => setSourceObservedAt(event.target.value)} /></FormItem></div>
      <div className="mt-3"><FormItem label="当前明确约束" hint="每行一个，只作为本次报告输入"><TextArea rows={3} value={constraints} onChange={(event) => setConstraints(event.target.value)} /></FormItem></div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3"><label className="text-sm text-stone-700"><input className="mr-2" type="checkbox" checked={saveArtifact} onChange={(event) => setSaveArtifact(event.target.checked)} />保存为版本化分析材料</label><Btn loading={busy} disabled={selected.length === 0 || baseCurrency.length !== 3} onClick={run}>生成比较报告</Btn></div>
    </>}
    {result && <div className="mt-5 border-t border-stone-100 pt-4">{result.career_profile_constraints.length > 0 && <div className="mb-3 rounded-lg bg-primary-50 p-3 text-xs text-primary-800"><p className="font-medium">本次读取的已确认求职档案约束</p><ul className="mt-1 list-disc space-y-1 pl-4">{result.career_profile_constraints.map((value) => <li key={value}>{value}</li>)}</ul></div>}<div className="grid gap-3 md:grid-cols-2">{result.items.map((item) => <article key={item.offer_id} className="rounded-lg bg-stone-50 p-4"><h3 className="font-medium text-stone-800">{item.company_name} · {item.job_title}</h3><div className="mt-2 grid grid-cols-2 gap-2 text-xs"><span>年化基本薪资</span><strong>{item.annual_base_in_base_currency ?? '无法计算'} {result.base_currency}</strong><span>估算税后现金</span><strong>{item.estimated_after_tax_cash ?? '无法计算'} {result.base_currency}</strong><span>估算总价值</span><strong>{item.estimated_total_value ?? '无法计算'} {result.base_currency}</strong></div><details className="mt-3 text-xs"><summary>假设、缺失与风险</summary><ul className="mt-2 list-disc space-y-1 pl-4">{[...item.assumptions, ...item.missing_information, ...item.risks].map((value) => <li key={value}>{value}</li>)}</ul></details></article>)}</div>{result.artifact_id && <p className="mt-2 text-xs text-success-700">已保存为 Artifact：{result.artifact_id}</p>}</div>}
    {selected.length === 1 && <div className="mt-5 border-t border-stone-100 pt-4"><h3 className="mb-2 text-sm font-medium text-stone-700">谈判草稿</h3><FormItem label="协商目标"><TextArea rows={3} value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="例如：希望将基本薪资提高到…，或延长回复截止" /></FormItem><div className="mt-2 flex justify-end"><Btn kind="outline" disabled={!objective.trim()} onClick={async () => { setBusy(true); try { const response = await createNegotiationDraft({ offerId: selected[0], objective, tone: 'professional', constraints: constraints.split('\n').filter(Boolean), saveArtifact }); setDraft({ text: response.draft_markdown, note: response.execution_note, artifactId: response.artifact_id }); } catch (error) { toast.error(extractErr(error)); } finally { setBusy(false); } }}>生成草稿</Btn></div>{draft && <div className="mt-3 rounded-lg border border-stone-200 p-3"><pre className="whitespace-pre-wrap font-sans text-sm text-stone-700">{draft.text}</pre><p className="mt-3 rounded-md bg-warning-50 p-2 text-xs text-warning-700">{draft.note}</p>{draft.artifactId && <p className="mt-1 text-xs text-success-700">已保存：{draft.artifactId}</p>}</div>}</div>}
  </section>;
}

export function CareerInsightsPage() {
  return <div className="mx-auto max-w-7xl space-y-5 p-4 md:p-6"><header><h1 className="text-xl font-semibold text-stone-800">行动与决策</h1><p className="mt-1 text-sm text-stone-500">聚合下一步、通知安排、历史漏斗和 Offer 分析；事实、行动与带假设的报告保持分离。</p></header><ActionAgenda /><ReminderSettings /><FunnelPanel /><OfferPanel /></div>;
}
