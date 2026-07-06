/**
 * 能力状态 — the structured ability ledger (topic × skill_type × mastery).
 *
 * The 删除 action is the user's veto (MEM-2): archiving a state also blocks
 * automatic extraction from recreating the same (topic, skill_type) for 30
 * days, so a deleted hallucination can't resurrect a week later.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { archiveAbilityState, listAbilityStates } from '@/api/memory';
import { extractErr } from '@/api/client';
import { toast } from '@/store/uiStore';
import { EmptyState } from '@/components/ui/EmptyState';
import { Target } from 'lucide-react';
import { LoadingBlock } from './shared';

const MASTERY_LABEL: Record<string, { text: string; cls: string }> = {
  weak: { text: '弱', cls: 'bg-red-50 text-red-700 border-red-200' },
  improving: { text: '进步中', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  stable: { text: '稳定', cls: 'bg-sky-50 text-sky-700 border-sky-200' },
  strong: { text: '强', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
};

function staleDays(iso: string | null): number | null {
  if (!iso) return null;
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  return days >= 14 ? days : null;
}

export function AbilityStatesSection() {
  const queryClient = useQueryClient();
  const { data: states = [], isPending, error } = useQuery({
    queryKey: ['memory', 'abilities'],
    queryFn: ({ signal }) => listAbilityStates({ signal }),
  });

  const archiveMutation = useMutation({
    mutationFn: (id: string) => archiveAbilityState(id),
    onSuccess: () => {
      toast.success('已删除（30 天内自动记忆不会重建该条目）');
      queryClient.invalidateQueries({ queryKey: ['memory', 'abilities'] });
      queryClient.invalidateQueries({ queryKey: ['memory', 'overview'] });
    },
    onError: (e) => toast.error(extractErr(e, '删除失败')),
  });

  if (isPending) return <LoadingBlock />;
  if (error) {
    return <div className="text-sm text-red-600 py-8 text-center">能力状态加载失败</div>;
  }
  if (states.length === 0) {
    return (
      <div className="text-center py-12">
        <EmptyState
          icon={<Target size={28} />}
          title="还没有能力状态"
          description="复盘对话和模拟面试中的表现会自动沉淀成结构化的能力账本。"
        />
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {states.map((s) => {
        const m = MASTERY_LABEL[s.mastery_level] ?? { text: s.mastery_level, cls: 'bg-stone-50 text-stone-600 border-stone-200' };
        const stale = staleDays(s.last_evidence_at);
        return (
          <div key={s.id} className="flex items-start gap-3 border border-stone-200 rounded-lg bg-white px-4 py-3">
            <span className={`text-xs px-2 py-0.5 rounded border shrink-0 mt-0.5 ${m.cls}`}>{m.text}</span>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-stone-800">
                {s.topic}
                <span className="ml-2 text-xs text-stone-400">{s.skill_type}</span>
                {stale && (
                  <span className="ml-2 text-xs text-stone-400">距上次证据 {stale} 天</span>
                )}
              </div>
              {s.summary && <div className="text-xs text-stone-500 mt-0.5">{s.summary}</div>}
            </div>
            <button
              type="button"
              title="删除（自动记忆 30 天内不会重建）"
              onClick={() => archiveMutation.mutate(s.id)}
              disabled={archiveMutation.isPending}
              className="w-7 h-7 rounded text-stone-400 hover:text-red-600 hover:bg-red-50 flex items-center justify-center shrink-0"
            >
              <Trash2 size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
