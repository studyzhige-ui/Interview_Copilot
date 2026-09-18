import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getMemoryPipelineStatus, getMemoryReceipts, setMemoryFeedback } from '@/api/personalization';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { toast } from '@/store/uiStore';
import type { AgentMemory } from '@/types/personalization';

export function MemoryActivity({ memories }: { memories: AgentMemory[] }) {
  const client = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const pipeline = useQuery({ queryKey: ['memory-pipeline'], queryFn: getMemoryPipelineStatus, refetchInterval: 30000 });
  const receipts = useQuery({ queryKey: ['memory-receipts'], queryFn: getMemoryReceipts });
  const feedback = async (id: string, value: 'helpful' | 'unhelpful') => {
    setBusy(id);
    try {
      await setMemoryFeedback(id, value);
      await client.invalidateQueries({ queryKey: ['memory-receipts'] });
      toast.success('已记录你的反馈');
    } catch (error) {
      toast.error(extractErr(error, '反馈保存失败，请重试'));
    } finally { setBusy(null); }
  };
  const status = pipeline.data;
  const failed = (status?.extractions.failed ?? 0) > 0 || status?.consolidation?.status === 'failed';
  return (
    <details className="mt-4 border-t border-stone-100 pt-3 text-xs text-stone-600">
      <summary className="cursor-pointer font-medium">记忆整理与使用记录</summary>
      {pipeline.isError ? <p role="alert" className="mt-2">暂时无法读取整理状态。<button onClick={() => { void pipeline.refetch(); }}>重试</button></p>
        : status ? <p className="mt-2">{!status.producer_available ? '自动整理尚未启用。'
          : failed ? '部分记忆整理失败，系统会稍后重试；已有记忆仍可使用。'
            : status.consolidation?.status === 'running' ? '正在整理过去的协作经验。'
              : status.consolidation?.revision ? '已完成最近一次整理。' : '等待可整理的对话。'}
          {' '}已提取 {status.extractions.succeeded ?? 0} 段经验，{status.extractions.no_output ?? 0} 段无需记住。
        </p> : <p className="mt-2">正在读取整理状态…</p>}
      <p className="mt-2">读取过不代表有帮助。这里区分回答中的引用和你的实际反馈。</p>
      {receipts.isError && <p role="alert">使用记录暂时无法读取。<button onClick={() => { void receipts.refetch(); }}>重试</button></p>}
      {(receipts.data ?? []).slice(0, 10).map((receipt) => {
        const memory = memories.find((item) => item.id === receipt.memory_id);
        return <div key={receipt.id} className="mt-3 border-b border-stone-100 pb-3">
          <p>{memory?.status === 'active' && memory.version === receipt.memory_version ? memory.content : '这条记忆已更新或不再使用'}</p>
          <p className="mt-1 text-stone-400">{receipt.cited_at ? '回答中曾引用' : '曾被读取，未确认引用'} · {new Date(receipt.created_at).toLocaleString()}</p>
          <div className="mt-2 flex gap-2">
            <Btn kind="ghost" size="sm" disabled={busy === receipt.id} onClick={() => { void feedback(receipt.id, 'helpful'); }}>{receipt.feedback === 'helpful' ? '已标记有帮助' : '有帮助'}</Btn>
            <Btn kind="ghost" size="sm" disabled={busy === receipt.id} onClick={() => { void feedback(receipt.id, 'unhelpful'); }}>{receipt.feedback === 'unhelpful' ? '已标记没帮助' : '没帮助'}</Btn>
          </div>
        </div>;
      })}
      {receipts.data?.length === 0 && <p className="mt-2">还没有记忆使用记录。</p>}
    </details>
  );
}
