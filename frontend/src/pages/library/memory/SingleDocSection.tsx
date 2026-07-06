/**
 * One editable v3 memory doc (user_profile / learning_strategy).
 *
 * Edits carry the optimistic-concurrency token (MEM-3): the updated_at the
 * body was loaded with rides along on save; a 409 means a background writer
 * (realtime extraction) landed in between — we surface the server message
 * and refetch so the user re-edits on the fresh version instead of silently
 * erasing it.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Compass, Pencil } from 'lucide-react';
import {
  editLearningStrategyDoc,
  editUserProfileDoc,
  getLearningStrategyDoc,
  getUserProfileDoc,
} from '@/api/memory';
import { extractErr } from '@/api/client';
import { toast } from '@/store/uiStore';
import { Btn } from '@/components/ui/Btn';
import { EmptyState } from '@/components/ui/EmptyState';
import { LoadingBlock } from './shared';

interface Props {
  kind: 'profile' | 'strategy';
}

export function SingleDocSection({ kind }: Props) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  // Set on a 409: a background writer landed during the edit window. The
  // next save must be an EXPLICIT choice (overwrite vs discard) — silently
  // retrying with a refreshed token would erase lines the user never saw.
  const [conflict, setConflict] = useState(false);

  const label = kind === 'profile' ? '用户画像' : '学习策略';
  const fetchDoc = kind === 'profile' ? getUserProfileDoc : getLearningStrategyDoc;
  const saveDoc = kind === 'profile' ? editUserProfileDoc : editLearningStrategyDoc;

  // Keyed by kind — React Query aborts the stale fetch when the user flips
  // tabs fast, so the wrong doc's body can't land in the editor.
  const { data, isPending, error } = useQuery({
    queryKey: ['memory', 'doc', kind],
    queryFn: ({ signal }) => fetchDoc({ signal }),
  });
  const body = data?.body ?? '';
  const baseUpdatedAt = data?.updated_at ?? null;

  const refetchDoc = () => {
    queryClient.invalidateQueries({ queryKey: ['memory', 'doc', kind] });
    queryClient.invalidateQueries({ queryKey: ['memory', 'overview'] });
  };

  const saveMutation = useMutation({
    mutationFn: (opts: { force?: boolean }) =>
      saveDoc(draft, opts.force ? null : baseUpdatedAt),
    onSuccess: () => {
      toast.success('已保存');
      setEditing(false);
      setConflict(false);
      refetchDoc();
    },
    onError: (e) => {
      const status = (e as { response?: { status?: number } })?.response?.status;
      toast.error(extractErr(e, '保存失败'));
      if (status === 409) {
        // Keep the draft; require an explicit resolution (banner below).
        setConflict(true);
        refetchDoc();
      }
    },
  });

  if (isPending) return <LoadingBlock />;
  if (error) {
    return <div className="text-sm text-red-600 py-8 text-center">{label}加载失败</div>;
  }
  const empty = !body.trim();
  if (empty && !editing) {
    return (
      <div className="text-center py-12">
        <EmptyState
          icon={<Compass size={28} />}
          title={`${label}还是空的`}
          description={kind === 'profile'
            ? '你的背景、目标、偏好会随对话自动沉淀到这里，也可以现在手动填写。'
            : '对话中确认有效的方法论（答题思路、复盘方法、训练节奏）会沉淀到这里，也可以手动新建。'}
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
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-stone-100 bg-stone-50">
        <span className="text-sm font-medium text-stone-700">{label}</span>
        <span className="ml-auto" />
        {editing ? (
          <>
            <Btn size="sm" kind="ghost" onClick={() => { setEditing(false); setConflict(false); }} disabled={saveMutation.isPending}>
              取消
            </Btn>
            <Btn size="sm" onClick={() => saveMutation.mutate({})} loading={saveMutation.isPending} disabled={conflict}>
              保存
            </Btn>
          </>
        ) : (
          <Btn size="sm" kind="ghost" icon={<Pencil size={12} />} onClick={() => { setDraft(body); setEditing(true); }}>
            编辑
          </Btn>
        )}
      </div>
      {editing && conflict && (
        <div className="mx-4 mt-3 flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          <span className="text-xs text-amber-900 flex-1">
            后台在你编辑期间更新了内容。请选择：放弃我的修改并查看最新版本，或强制覆盖（会丢失后台更新）。
          </span>
          <Btn
            size="sm"
            kind="ghost"
            onClick={() => { setConflict(false); setEditing(false); refetchDoc(); }}
          >
            放弃我的修改
          </Btn>
          <Btn size="sm" onClick={() => saveMutation.mutate({ force: true })} loading={saveMutation.isPending}>
            强制覆盖
          </Btn>
        </div>
      )}
      {editing ? (
        <textarea
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={16}
          className="w-full p-4 text-sm font-mono bg-white outline-none resize-y"
        />
      ) : (
        <pre className="p-4 text-sm text-stone-700 whitespace-pre-wrap font-sans">{body}</pre>
      )}
    </div>
  );
}
