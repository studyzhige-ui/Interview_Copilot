import { money } from '@/lib/money';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getAccountUsage, getUsageReceipts } from '@/api/usage';
import { useAuthStore } from '@/store/authStore';

const statuses: Record<string, string> = { reserved: '在途预留', settled: '用量已记录', estimated: '保守估算', rejected: '明确拒绝', unknown: '结果未知' };
const bases: Record<string, string> = { unpriced: '尚未定价', rated_estimate: '按预留估算', rated_usage: '按版本费率计算', provider_invoice: '凭供应商证据对账' };


/** Server accounting, not local progress; missing prices are never free calls. */
export function ModelUsagePanel() {
  const owner = useAuthStore((state) => state.subjectId);
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState<string | undefined>();
  const query = useQuery({ queryKey: ['account-usage', owner], queryFn: getAccountUsage, enabled: Boolean(owner), staleTime: 10_000, retry: false });
  const receipts = useQuery({ queryKey: ['usage-receipts', owner, cursor], queryFn: () => getUsageReceipts(cursor), enabled: Boolean(owner) && open, retry: false });
  if (!owner) return null;
  const usage = query.data;
  return <section aria-label="账户资源与费用" className="mb-6 rounded-xl border border-stone-200 bg-white p-4 text-sm">
    <div className="flex items-center justify-between gap-3">
      <h3 className="font-semibold">账户资源与费用</h3>
      <button disabled={query.isFetching} onClick={() => { void query.refetch(); if (open) void receipts.refetch(); }} className="text-primary-700 underline">刷新用量</button>
    </div>
    {query.isError ? <p role="alert" className="mt-2">用量暂不可读取；不能据此认为额度已清零。</p>
      : usage ? <>
        <p className="mt-2">{usage.window_date}（UTC）：已准入 {usage.calls_admitted} / {usage.call_limit} 次调用。</p>
        <p>已计入 {usage.tokens_used.toLocaleString()}，预留 {usage.tokens_reserved.toLocaleString()}，当日额度 {usage.token_limit.toLocaleString()} 个逻辑 token。</p>
        <p>已计价 {money(usage.rated_cost_used_micros)}，预留 {money(usage.rated_cost_reserved_micros)} {usage.currency}；{usage.cost_limit_micros === null ? '未配置货币上限，调用和资源额度仍生效' : `货币上限 ${money(usage.cost_limit_micros)} ${usage.currency}`}。</p>
        {usage.unpriced_requests > 0 && <p role="status" className="mt-2 text-amber-800">{usage.unpriced_requests} 次调用尚未定价，总费用尚不完整；不是免费。启用货币上限前需核对历史记录。</p>}
        <p className="text-stone-600">跨日期尚未核实 {usage.unresolved_all_dates} 次；已凭供应商证据对账 {usage.invoice_reconciled_requests} 次。</p>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">{Object.entries(usage.unit_limits).map(([unit, limit]) => <span key={unit}>{unit}：{((usage.units_used[unit] ?? 0) + (usage.units_reserved[unit] ?? 0)).toLocaleString()} / {limit.toLocaleString()}</span>)}</div>
      </> : <p className="mt-2">正在读取服务端额度…</p>}
    <p className="mt-2 text-xs text-stone-500">覆盖回答、内部模型、压缩、视觉、文档解析、检索向量、重排、语音与工具资源请求；不含基础设施运行成本和 OAuth/目录控制请求。这不是供应商账单：金额依调用时冻结的费率及实测或保守估算用量计算，只有经证据对账的记录属于供应商确认费用。新建、刷新或删除会话不会重置额度。</p>
    <button className="mt-3 text-primary-700 underline" onClick={() => { setOpen(!open); setCursor(undefined); }}>{open ? '收起调用记录' : '查看调用记录'}</button>
    {open && <div className="mt-3 overflow-x-auto">
      {receipts.isError ? <p role="alert">调用记录暂不可读取。</p> : receipts.data ? <>
        <table className="w-full text-left text-xs"><thead><tr><th>类别 / 模型</th><th>状态</th><th>费用依据</th><th>金额 / 原记录币种</th></tr></thead>
          <tbody>{receipts.data.items.map((r) => <tr key={r.id} className="border-t border-stone-100"><td className="py-2">{r.meter} / {r.model ?? '历史未记录'}<br /><span title={r.id}>{r.id.slice(0, 12)} · {r.date}</span></td><td>{statuses[r.status] ?? r.status}</td><td>{bases[r.cost_basis] ?? r.cost_basis}</td><td>{r.cost_basis === 'unpriced' ? '未定价' : `${money(r.cost_observed_micros ?? r.cost_reserved_micros)} ${r.currency}`}</td></tr>)}</tbody>
        </table>
        {receipts.data.items.length === 0 && <p>没有符合范围的调用记录。</p>}
        <button className="mt-2 mr-4 underline" disabled={!cursor} onClick={() => setCursor(undefined)}>最新记录</button>
        <button className="mt-2 underline" disabled={!receipts.data.next_cursor} onClick={() => setCursor(receipts.data?.next_cursor ?? undefined)}>更早记录</button>
      </> : <p>正在读取调用记录…</p>}
    </div>}
  </section>;
}
