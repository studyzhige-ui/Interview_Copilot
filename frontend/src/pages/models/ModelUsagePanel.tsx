import { useQuery } from '@tanstack/react-query';
import { getPrimaryModelUsage } from '@/api/workspace';
import { useAuthStore } from '@/store/authStore';

/** Account-scoped server accounting, not browser-local progress or an invoice. */
export function ModelUsagePanel() {
  const owner = useAuthStore((state) => state.subjectId);
  const query = useQuery({
    queryKey: ['model-usage', owner],
    queryFn: getPrimaryModelUsage,
    enabled: Boolean(owner),
    staleTime: 10_000,
    retry: false,
  });
  if (!owner) return null;
  const usage = query.data;
  return <section aria-label="回答模型用量" className="mb-6 rounded-xl border border-stone-200 bg-white p-4 text-sm">
    <div className="flex items-center justify-between gap-3">
      <h3 className="font-semibold">回答模型用量</h3>
      <button disabled={query.isFetching} onClick={() => { void query.refetch(); }} className="text-primary-700 underline">刷新用量</button>
    </div>
    {query.isError ? <p role="alert" className="mt-2">用量暂不可读取；不能据此认为额度已清零。</p>
      : usage ? <>
        <p className="mt-2">{usage.window_date}（UTC）：已准入 {usage.calls_admitted} / {usage.call_limit} 次模型请求。</p>
        <p>已计入 {usage.tokens_used.toLocaleString()}，预留 {usage.tokens_reserved.toLocaleString()}，当日额度 {usage.token_limit.toLocaleString()} 个逻辑 token。</p>
      </> : <p className="mt-2">正在读取服务端额度…</p>}
    <p className="mt-2 text-xs text-stone-500">覆盖对话与 Agent 的回答模型；不包含内部模型、压缩、检索、重排、语音或外部工具费用。这不是供应商账单。预留包含在途或结果未知的请求，新建、刷新或删除会话不会重置额度。</p>
  </section>;
}
