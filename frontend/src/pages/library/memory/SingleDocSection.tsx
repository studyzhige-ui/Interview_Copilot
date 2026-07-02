/** 策略 / 习惯 — single-body doc view + edit (shared shape). */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Compass, Pencil, Save, X as XIcon } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { EmptyState } from '@/components/ui/EmptyState';
import { MarkdownBody } from '@/components/ui/MarkdownBody';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  editHabitDoc,
  editStrategyDoc,
  getHabitDoc,
  getStrategyDoc,
} from '@/api/memory';
import { useToastOnError } from './useToastOnError';
import { LoadingBlock } from './shared';

export function SingleDocSection({ kind }: { kind: 'strategy' | 'habit' }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');

  const label = kind === 'strategy' ? '策略文档' : '习惯文档';
  const docTypeLabel = kind === 'strategy' ? 'strategy_doc' : 'habit_doc';
  const fetchBody = kind === 'strategy' ? getStrategyDoc : getHabitDoc;
  const saveBody = kind === 'strategy' ? editStrategyDoc : editHabitDoc;

  // Keyed by kind — React Query aborts the stale fetch when the user flips
  // strategy ↔ habit fast, so the wrong doc's body can't land in the editor.
  const { data: body, isPending, error } = useQuery({
    queryKey: ['memory', 'doc', kind],
    queryFn: ({ signal }) => fetchBody({ signal }),
  });
  useToastOnError(error, `${label}加载失败`);

  const saveMutation = useMutation({
    mutationFn: () => saveBody(draft),
    onSuccess: () => {
      toast.success('已保存');
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ['memory', 'doc', kind] });
      queryClient.invalidateQueries({ queryKey: ['memory', 'overview'] });
    },
    onError: (e) => toast.error(extractErr(e, '保存失败')),
  });

  if (isPending) return <LoadingBlock />;
  const empty = !body?.trim();
  if (empty && !editing) {
    return (
      <div className="text-center py-12">
        <EmptyState
          icon={<Compass size={28} />}
          title={`${label}还是空的`}
          description={kind === 'strategy'
            ? '对话中你确认有效的方法论（"用 XX 思路答这类题就稳了"）会沉淀到这里。也可以现在手动新建。'
            : '稳定的练习节奏（"每天 1 小时模拟面试"）和心态会沉淀到这里。也可以现在手动新建。'}
          action={
            <Btn icon={<Pencil size={12} />} onClick={() => { setDraft(''); setEditing(true); }}>
              新建
            </Btn>
          }
        />
      </div>
    );
  }

  return (
    <div className="border border-stone-200 rounded-lg bg-white overflow-hidden">
      <div className="px-4 py-3 border-b border-stone-200 flex items-center gap-2">
        <div className="flex-1">
          <div className="text-sm font-semibold text-stone-800">{label}</div>
          <div className="text-[10px] text-stone-400 font-mono">{docTypeLabel}</div>
        </div>
        {editing ? (
          <>
            <Btn kind="ghost" size="sm" icon={<XIcon size={12} />}
              onClick={() => { setEditing(false); setDraft(body ?? ''); }}
              disabled={saveMutation.isPending}>
              取消
            </Btn>
            <Btn size="sm" icon={<Save size={12} />} loading={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}>
              保存
            </Btn>
          </>
        ) : (
          <Btn kind="ghost" size="sm" icon={<Pencil size={12} />}
            onClick={() => { setDraft(body ?? ''); setEditing(true); }}>
            编辑
          </Btn>
        )}
      </div>
      <div className="p-4">
        {editing ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={20}
            className="w-full px-3 py-2 border border-stone-200 rounded-md text-[13px] font-mono outline-none focus:border-primary-300"
            placeholder={`# ${label}\n\n## ${kind === 'strategy' ? '已内化' : '稳定的练习节奏'}\n- ...`}
          />
        ) : (
          <MarkdownBody source={body ?? ''} />
        )}
      </div>
    </div>
  );
}
