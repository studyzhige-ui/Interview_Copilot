/** 知识点 — list of knowledge_doc topics + per-topic view / edit / delete. */
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  BookOpen, Pencil, Trash2, Save, X as XIcon,
} from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { MarkdownBody } from '@/components/ui/MarkdownBody';
import { Pill } from '@/components/ui/Pill';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  deleteKnowledgeTopic,
  editKnowledgeTopic,
  getKnowledgeTopic,
  listKnowledgeTopics,
} from '@/api/memory';
import type { MasteryLevel } from '@/types/api';
import { useToastOnError } from '@/hooks/useToastOnError';
import { LoadingBlock, MasteryDot } from './shared';

export function KnowledgeSection() {
  const queryClient = useQueryClient();
  const [activeTopic, setActiveTopic] = useState<string | null>(null);
  const [filterMastery, setFilterMastery] = useState<MasteryLevel | 'all'>('all');
  const [query, setQuery] = useState('');

  const { data: topics = [], isPending, error } = useQuery({
    queryKey: ['memory', 'knowledge'],
    queryFn: ({ signal }) => listKnowledgeTopics({ signal }),
  });
  useToastOnError(error, '知识点列表加载失败');

  const refreshList = () =>
    queryClient.invalidateQueries({ queryKey: ['memory', 'knowledge'] });

  // Default to the first topic once the list lands.
  const effectiveTopic = activeTopic ?? topics[0]?.topic ?? null;

  const filtered = useMemo(() => {
    let arr = topics;
    if (filterMastery !== 'all') {
      arr = arr.filter((t) => t.mastery_level === filterMastery);
    }
    if (query.trim()) {
      const q = query.toLowerCase();
      arr = arr.filter((t) => t.topic.toLowerCase().includes(q));
    }
    return arr;
  }, [topics, filterMastery, query]);

  if (isPending) return <LoadingBlock />;
  if (topics.length === 0) {
    return (
      <EmptyState
        icon={<BookOpen size={28} />}
        title="还没有知识点"
        description="对话中讨论过的技术主题（如 Redis / TCP / React）会自动建档。继续聊就好。"
      />
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
      {/* Topic list */}
      <div className="border border-stone-200 rounded-lg bg-white overflow-hidden">
        <div className="p-2.5 border-b border-stone-200 space-y-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索主题..."
            className="w-full px-2.5 py-1.5 bg-stone-50 border border-stone-200 rounded-md text-sm outline-none focus:border-primary-300"
          />
          <div className="flex items-center gap-1 text-[11px]">
            {(['all', 'weak', 'progressing', 'strong', 'unknown'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setFilterMastery(m)}
                className={[
                  'px-2 py-0.5 rounded-full',
                  filterMastery === m
                    ? 'bg-primary-50 text-primary-700 border border-primary-100'
                    : 'text-stone-500 hover:bg-stone-100',
                ].join(' ')}
              >
                {m === 'all' ? '全部' : m}
              </button>
            ))}
          </div>
        </div>
        <div className="max-h-[60vh] overflow-y-auto">
          {filtered.length === 0 && (
            <div className="p-4 text-xs text-stone-400 text-center">无匹配主题</div>
          )}
          {filtered.map((t) => (
            <button
              key={t.topic}
              onClick={() => setActiveTopic(t.topic)}
              className={[
                'w-full text-left px-3 py-2 border-b border-stone-100 last:border-b-0',
                t.topic === effectiveTopic
                  ? 'bg-primary-50/50'
                  : 'hover:bg-stone-50',
              ].join(' ')}
            >
              <div className="flex items-center gap-1.5">
                <MasteryDot level={t.mastery_level} />
                <span className={[
                  'text-sm truncate',
                  t.topic === effectiveTopic ? 'text-primary-700 font-semibold' : 'text-stone-800',
                ].join(' ')}>
                  {t.topic}
                </span>
                <span className="ml-auto text-[10px] text-stone-400 font-mono">
                  {t.fact_count}
                </span>
              </div>
              {t.one_liner && (
                <div className="text-[11px] text-stone-500 mt-0.5 truncate">
                  {t.one_liner}
                </div>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Selected topic detail */}
      <div className="min-w-0">
        {effectiveTopic && (
          <KnowledgeTopicDetailView
            key={effectiveTopic}
            topic={effectiveTopic}
            onDeleted={() => {
              setActiveTopic(null);
              refreshList();
            }}
            onEdited={refreshList}
          />
        )}
      </div>
    </div>
  );
}

function KnowledgeTopicDetailView({
  topic, onDeleted, onEdited,
}: {
  topic: string;
  onDeleted: () => void;
  onEdited: () => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draftBody, setDraftBody] = useState('');
  const [draftOneLiner, setDraftOneLiner] = useState('');
  const [draftMastery, setDraftMastery] = useState<MasteryLevel>('unknown');
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  // React Query aborts the in-flight fetch on topic switch (the signal is
  // wired through), so rapid clicks A → B → A can't paint stale data.
  const { data: doc, isPending, error } = useQuery({
    queryKey: ['memory', 'knowledge', topic],
    queryFn: ({ signal }) => getKnowledgeTopic(topic, { signal }),
  });
  useToastOnError(error, '主题内容加载失败');

  const startEditing = () => {
    if (!doc) return;
    setDraftBody(doc.body);
    setDraftOneLiner(doc.one_liner ?? '');
    setDraftMastery(doc.mastery_level ?? 'unknown');
    setEditing(true);
  };

  const saveMutation = useMutation({
    mutationFn: () => editKnowledgeTopic(topic, {
      body: draftBody,
      one_liner: draftOneLiner.trim() || null,
      mastery_level: draftMastery,
    }),
    onSuccess: async () => {
      toast.success('已保存');
      setEditing(false);
      onEdited();
      // Reload to pick up server-side body re-derivation (fact_count etc.)
      await queryClient.invalidateQueries({ queryKey: ['memory', 'knowledge', topic] });
    },
    onError: (e) => toast.error(extractErr(e, '保存失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteKnowledgeTopic(topic),
    onSuccess: () => {
      toast.success(`已删除主题「${topic}」`);
      setConfirmingDelete(false);
      queryClient.removeQueries({ queryKey: ['memory', 'knowledge', topic] });
      onDeleted();
    },
    onError: (e) => toast.error(extractErr(e, '删除失败')),
  });

  if (isPending) return <LoadingBlock />;
  if (!doc) return null;

  return (
    <div className="border border-stone-200 rounded-lg bg-white overflow-hidden">
      <div className="px-4 py-3 border-b border-stone-200 flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <MasteryDot level={doc.mastery_level} />
            <h3 className="text-base font-semibold text-stone-800 truncate">{doc.topic}</h3>
            <Pill tone="neutral">{doc.fact_count} 条</Pill>
          </div>
          {!editing && doc.one_liner && (
            <div className="text-xs text-stone-500 mt-1">{doc.one_liner}</div>
          )}
        </div>
        {editing ? (
          <>
            <Btn kind="ghost" size="sm" icon={<XIcon size={12} />}
              onClick={() => setEditing(false)} disabled={saveMutation.isPending}>
              取消
            </Btn>
            <Btn size="sm" icon={<Save size={12} />} loading={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}>
              保存
            </Btn>
          </>
        ) : (
          <>
            <Btn kind="ghost" size="sm" icon={<Pencil size={12} />} onClick={startEditing}>
              编辑
            </Btn>
            <Btn kind="danger" size="sm" icon={<Trash2 size={12} />}
              onClick={() => setConfirmingDelete(true)}>
              删除
            </Btn>
          </>
        )}
      </div>
      <div className="p-4">
        {editing ? (
          <div className="space-y-3">
            <div>
              <label className="text-[11px] text-stone-500 uppercase tracking-wider">
                一句话总结 (one_liner)
              </label>
              <input
                value={draftOneLiner}
                onChange={(e) => setDraftOneLiner(e.target.value)}
                placeholder="e.g. 这是分布式缓存的核心概念"
                className="mt-1 w-full px-2.5 py-1.5 border border-stone-200 rounded-md text-sm outline-none focus:border-primary-300"
              />
            </div>
            <div>
              <label className="text-[11px] text-stone-500 uppercase tracking-wider">
                掌握程度
              </label>
              <div className="mt-1 flex items-center gap-1">
                {(['unknown', 'weak', 'progressing', 'strong'] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setDraftMastery(m)}
                    className={[
                      'px-2.5 py-1 rounded-full text-xs',
                      draftMastery === m
                        ? 'bg-primary-50 text-primary-700 border border-primary-100'
                        : 'text-stone-500 hover:bg-stone-100 border border-transparent',
                    ].join(' ')}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="text-[11px] text-stone-500 uppercase tracking-wider">
                正文 (markdown)
              </label>
              <textarea
                value={draftBody}
                onChange={(e) => setDraftBody(e.target.value)}
                rows={18}
                className="mt-1 w-full px-3 py-2 border border-stone-200 rounded-md text-[13px] font-mono outline-none focus:border-primary-300"
              />
            </div>
          </div>
        ) : (
          <MarkdownBody source={doc.body || '（正文为空）'} />
        )}
      </div>

      <ConfirmDialog
        open={confirmingDelete}
        danger
        title="删除知识点"
        description={`确认删除主题「${doc.topic}」？所有版本历史都会消失，不可恢复。`}
        confirmText="删除"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteMutation.mutate()}
        onCancel={() => setConfirmingDelete(false)}
      />
    </div>
  );
}
