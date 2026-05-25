/**
 * Memory tab — v3 architecture browser inside the Library page.
 *
 * Replaces the retired ``memory_items`` browser. Five sub-areas:
 *
 *   概览      — overview snapshot of all four v3 doc types
 *   个人资料  — user_profile_doc body (read-only; no PUT endpoint backend-side)
 *   知识点    — list of knowledge_doc topics + per-topic view / edit / delete
 *   策略      — single strategy_doc body view + edit
 *   习惯      — single habit_doc body view + edit
 *   审计      — memory_audit_log paginated list + before/after detail
 *
 * Edits go through ``PUT /memory/{doc}`` which holds the per-user
 * memory-lock server-side, so user-edits serialise with realtime
 * extraction and dreaming writers.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Brain, FileText, BookOpen, Compass, Target, History, RefreshCw,
  Pencil, Trash2, Save, X as XIcon, ChevronLeft, ChevronRight,
  ChevronDown, ExternalLink,
} from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { MarkdownBody } from '@/components/ui/MarkdownBody';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  deleteKnowledgeTopic,
  editHabitDoc,
  editKnowledgeTopic,
  editStrategyDoc,
  getHabitDoc,
  getKnowledgeTopic,
  getMemoryAuditEntry,
  getMemoryOverview,
  getStrategyDoc,
  getUserProfileDoc,
  listKnowledgeTopics,
  listMemoryAudit,
} from '@/api/memory';
import type {
  KnowledgeTopicDetail, KnowledgeTopicSummary,
  MasteryLevel, MemoryAuditDetail, MemoryAuditEntry,
  MemoryChangeType, MemoryDocType, MemoryOverviewResp,
} from '@/types/api';

// ── Sub-tab definitions ─────────────────────────────────────────────────

type SubTab = 'overview' | 'profile' | 'knowledge' | 'strategy' | 'habit' | 'audit';

interface SubTabDef {
  id: SubTab;
  label: string;
  icon: typeof Brain;
}

const SUB_TABS: SubTabDef[] = [
  { id: 'overview',  label: '概览',     icon: Brain },
  { id: 'profile',   label: '个人资料', icon: FileText },
  { id: 'knowledge', label: '知识点',   icon: BookOpen },
  { id: 'strategy',  label: '策略',     icon: Compass },
  { id: 'habit',     label: '习惯',     icon: Target },
  { id: 'audit',     label: '审计',     icon: History },
];

// ── Top component ──────────────────────────────────────────────────────

export function MemoryTab() {
  const [sub, setSub] = useState<SubTab>('overview');
  return (
    <div className="bg-white border border-stone-200 rounded-xl shadow-xs">
      <div className="px-4 py-3 border-b border-stone-200 flex items-center gap-1.5 overflow-x-auto">
        {SUB_TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setSub(id)}
            className={[
              'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm whitespace-nowrap',
              sub === id
                ? 'bg-primary-50 text-primary-700 border border-primary-100'
                : 'text-stone-600 hover:bg-stone-100 border border-transparent',
            ].join(' ')}
          >
            <Icon size={13} />
            {label}
          </button>
        ))}
      </div>
      <div className="p-5">
        {sub === 'overview'  && <OverviewSection switchTo={setSub} />}
        {sub === 'profile'   && <ProfileSection />}
        {sub === 'knowledge' && <KnowledgeSection />}
        {sub === 'strategy'  && <SingleDocSection kind="strategy" />}
        {sub === 'habit'     && <SingleDocSection kind="habit" />}
        {sub === 'audit'     && <AuditSection />}
      </div>
    </div>
  );
}

// ── 概览 ───────────────────────────────────────────────────────────────

function OverviewSection({ switchTo }: { switchTo: (s: SubTab) => void }) {
  const [data, setData] = useState<MemoryOverviewResp | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = () => {
    setLoading(true);
    getMemoryOverview()
      .then(setData)
      .catch((e) => toast.error(extractErr(e, '记忆概览加载失败')))
      .finally(() => setLoading(false));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(refresh, []);

  if (loading) return <LoadingBlock />;
  if (!data) return null;

  const empty = !data.user_profile_body.trim()
    && data.knowledge_topics.length === 0
    && !data.strategy_body.trim()
    && !data.habit_body.trim();

  if (empty) {
    return (
      <EmptyState
        icon={<Brain size={28} />}
        title="还没有跨会话记忆"
        description="开几场对话或面试复盘后，系统会自动总结出你的认知、策略与习惯。也可以在「个人中心」开启「全局记忆」让对话主动注入。"
      />
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <OverviewCard
        icon={<FileText size={14} />}
        title="个人资料"
        subtitle="durable identity & preferences"
        empty={!data.user_profile_body.trim()}
        emptyHint="未生成 — 在「个人中心」填写 bio 或在对话中提及你的目标公司 / 技术栈"
        onOpen={() => switchTo('profile')}
      >
        <PreviewBody body={data.user_profile_body} />
      </OverviewCard>

      <OverviewCard
        icon={<BookOpen size={14} />}
        title="知识点"
        subtitle={`${data.knowledge_topics.length} 个主题`}
        empty={data.knowledge_topics.length === 0}
        emptyHint="对话中讨论过的技术主题会自动建档"
        onOpen={() => switchTo('knowledge')}
      >
        <div className="space-y-1.5">
          {data.knowledge_topics.slice(0, 6).map((t) => (
            <div key={t.topic} className="flex items-center gap-2 text-[13px]">
              <span className="font-medium text-stone-800 truncate">{t.topic}</span>
              <MasteryDot level={t.mastery_level} />
              <span className="text-[11px] text-stone-400 ml-auto shrink-0">
                {t.fact_count} 条
              </span>
            </div>
          ))}
          {data.knowledge_topics.length > 6 && (
            <div className="text-[11px] text-stone-400 pt-1">
              … 还有 {data.knowledge_topics.length - 6} 个
            </div>
          )}
        </div>
      </OverviewCard>

      <OverviewCard
        icon={<Compass size={14} />}
        title="策略"
        subtitle="cross-topic answering methodology"
        empty={!data.strategy_body.trim()}
        emptyHint="对话中验证有效的方法论会沉淀到这里"
        onOpen={() => switchTo('strategy')}
      >
        <PreviewBody body={data.strategy_body} />
      </OverviewCard>

      <OverviewCard
        icon={<Target size={14} />}
        title="习惯"
        subtitle="stable practice & mindset"
        empty={!data.habit_body.trim()}
        emptyHint="稳定的练习节奏 / 心态会沉淀到这里"
        onOpen={() => switchTo('habit')}
      >
        <PreviewBody body={data.habit_body} />
      </OverviewCard>

      <div className="lg:col-span-2 flex items-center justify-end">
        <button
          onClick={refresh}
          className="inline-flex items-center gap-1.5 text-xs text-stone-500 hover:text-stone-700 px-2 py-1"
        >
          <RefreshCw size={11} /> 刷新
        </button>
      </div>
    </div>
  );
}

function OverviewCard({
  icon, title, subtitle, empty, emptyHint, onOpen, children,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  empty: boolean;
  emptyHint: string;
  onOpen: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="border border-stone-200 rounded-lg overflow-hidden bg-white">
      <div className="px-3.5 py-2.5 bg-stone-50 border-b border-stone-200 flex items-center gap-2">
        <span className="text-stone-500">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-stone-800">{title}</div>
          <div className="text-[10px] text-stone-400 font-mono">{subtitle}</div>
        </div>
        <button
          onClick={onOpen}
          className="text-[11px] text-primary-600 hover:text-primary-700 inline-flex items-center gap-0.5"
        >
          打开 <ChevronRight size={12} />
        </button>
      </div>
      <div className="p-3.5 text-stone-700 min-h-[100px]">
        {empty ? (
          <div className="text-xs text-stone-400 italic">{emptyHint}</div>
        ) : children}
      </div>
    </div>
  );
}

function PreviewBody({ body }: { body: string }) {
  // First ~8 lines of the body, no heavy markdown rendering — just a peek.
  const lines = body.split('\n').slice(0, 8).join('\n');
  const truncated = body.split('\n').length > 8;
  return (
    <div className="text-[12.5px] leading-relaxed font-mono whitespace-pre-wrap break-words text-stone-700">
      {lines}
      {truncated && <div className="text-stone-400 mt-1">…</div>}
    </div>
  );
}

function MasteryDot({ level }: { level: MasteryLevel | null }) {
  const tone =
    level === 'strong'      ? 'bg-success-500'
    : level === 'progressing' ? 'bg-primary-400'
    : level === 'weak'        ? 'bg-warning-500'
    : 'bg-stone-300';
  // null (no row in DB) vs 'unknown' (explicit "I don't know yet") are
  // semantically different — keep the tooltip honest.
  const title =
    level === null ? '未评估' : level;
  return (
    <span
      title={title}
      className={['inline-block w-1.5 h-1.5 rounded-full shrink-0', tone].join(' ')}
    />
  );
}

// ── 个人资料 (read-only) ────────────────────────────────────────────────

function ProfileSection() {
  const [body, setBody] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    getUserProfileDoc()
      .then(setBody)
      .catch((e) => toast.error(extractErr(e, '个人资料加载失败')))
      .finally(() => setLoading(false));
  }, []);
  if (loading) return <LoadingBlock />;
  if (!body?.trim()) {
    return (
      <EmptyState
        icon={<FileText size={28} />}
        title="个人资料文档为空"
        description="在「个人中心」填写昵称 / 简介，或者在对话中提及你的目标公司 / 技术栈 / 当前职级，系统会自动沉淀到这里。"
      />
    );
  }
  return (
    <div className="bg-stone-50 border border-stone-200 rounded-lg p-4">
      <div className="text-[11px] text-stone-400 font-mono mb-2 uppercase tracking-wider">
        user_profile_doc · 只读
      </div>
      <MarkdownBody source={body} />
    </div>
  );
}

// ── 知识点 ──────────────────────────────────────────────────────────────

function KnowledgeSection() {
  const [topics, setTopics] = useState<KnowledgeTopicSummary[]>([]);
  const [activeTopic, setActiveTopic] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [filterMastery, setFilterMastery] = useState<MasteryLevel | 'all'>('all');
  const [query, setQuery] = useState('');

  const refreshList = () => {
    setLoadingList(true);
    listKnowledgeTopics()
      .then((rows) => {
        setTopics(rows);
        if (!activeTopic && rows[0]) setActiveTopic(rows[0].topic);
      })
      .catch((e) => toast.error(extractErr(e, '知识点列表加载失败')))
      .finally(() => setLoadingList(false));
  };
  useEffect(refreshList, []);  // eslint-disable-line react-hooks/exhaustive-deps

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

  if (loadingList) return <LoadingBlock />;
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
                t.topic === activeTopic
                  ? 'bg-primary-50/50'
                  : 'hover:bg-stone-50',
              ].join(' ')}
            >
              <div className="flex items-center gap-1.5">
                <MasteryDot level={t.mastery_level} />
                <span className={[
                  'text-sm truncate',
                  t.topic === activeTopic ? 'text-primary-700 font-semibold' : 'text-stone-800',
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
        {activeTopic && (
          <KnowledgeTopicDetailView
            key={activeTopic}
            topic={activeTopic}
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
  const [doc, setDoc] = useState<KnowledgeTopicDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [draftBody, setDraftBody] = useState('');
  const [draftOneLiner, setDraftOneLiner] = useState('');
  const [draftMastery, setDraftMastery] = useState<MasteryLevel>('unknown');
  const [saving, setSaving] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    setLoading(true);
    setEditing(false);
    getKnowledgeTopic(topic)
      .then((d) => {
        setDoc(d);
        setDraftBody(d.body);
        setDraftOneLiner(d.one_liner ?? '');
        setDraftMastery(d.mastery_level ?? 'unknown');
      })
      .catch((e) => toast.error(extractErr(e, '主题内容加载失败')))
      .finally(() => setLoading(false));
  }, [topic]);

  const onSave = async () => {
    setSaving(true);
    try {
      await editKnowledgeTopic(topic, {
        body: draftBody,
        one_liner: draftOneLiner.trim() || null,
        mastery_level: draftMastery,
      });
      toast.success('已保存');
      setEditing(false);
      onEdited();
      // Reload to pick up server-side body re-derivation (fact_count etc.)
      const d = await getKnowledgeTopic(topic);
      setDoc(d);
    } catch (e) {
      toast.error(extractErr(e, '保存失败'));
    } finally {
      setSaving(false);
    }
  };

  const onConfirmDelete = async () => {
    setDeleting(true);
    try {
      await deleteKnowledgeTopic(topic);
      toast.success(`已删除主题「${topic}」`);
      setConfirmingDelete(false);
      onDeleted();
    } catch (e) {
      toast.error(extractErr(e, '删除失败'));
    } finally {
      setDeleting(false);
    }
  };

  if (loading) return <LoadingBlock />;
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
              onClick={() => setEditing(false)} disabled={saving}>
              取消
            </Btn>
            <Btn size="sm" icon={<Save size={12} />} loading={saving} onClick={onSave}>
              保存
            </Btn>
          </>
        ) : (
          <>
            <Btn kind="ghost" size="sm" icon={<Pencil size={12} />}
              onClick={() => setEditing(true)}>
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
        loading={deleting}
        onConfirm={onConfirmDelete}
        onCancel={() => setConfirmingDelete(false)}
      />
    </div>
  );
}

// ── 策略 / 习惯 (共享 single-body shape) ──────────────────────────────────

function SingleDocSection({ kind }: { kind: 'strategy' | 'habit' }) {
  const [body, setBody] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  const label = kind === 'strategy' ? '策略文档' : '习惯文档';
  const docTypeLabel = kind === 'strategy' ? 'strategy_doc' : 'habit_doc';
  const fetchBody = kind === 'strategy' ? getStrategyDoc : getHabitDoc;
  const saveBody = kind === 'strategy' ? editStrategyDoc : editHabitDoc;

  const refresh = () => {
    setLoading(true);
    fetchBody()
      .then((b) => { setBody(b); setDraft(b); })
      .catch((e) => toast.error(extractErr(e, `${label}加载失败`)))
      .finally(() => setLoading(false));
  };
  useEffect(refresh, [kind]);  // eslint-disable-line react-hooks/exhaustive-deps

  const onSave = async () => {
    setSaving(true);
    try {
      await saveBody(draft);
      toast.success('已保存');
      setEditing(false);
      refresh();
    } catch (e) {
      toast.error(extractErr(e, '保存失败'));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <LoadingBlock />;
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
              disabled={saving}>
              取消
            </Btn>
            <Btn size="sm" icon={<Save size={12} />} loading={saving} onClick={onSave}>
              保存
            </Btn>
          </>
        ) : (
          <Btn kind="ghost" size="sm" icon={<Pencil size={12} />}
            onClick={() => setEditing(true)}>
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

// ── 审计 ───────────────────────────────────────────────────────────────

const AUDIT_PAGE_SIZE = 20;

const DOC_TYPE_LABEL: Record<MemoryDocType, string> = {
  user_profile: '个人资料',
  knowledge: '知识',
  strategy: '策略',
  habit: '习惯',
};

const CHANGE_TYPE_LABEL: Record<MemoryChangeType, string> = {
  patch_realtime: '实时提取',
  patch_dreaming: '夜间整理',
  user_edit: '手动编辑',
  user_delete: '手动删除',
  migration: '迁移',
};

const CHANGE_TYPE_TONE: Record<MemoryChangeType, 'success' | 'warn' | 'danger' | 'neutral'> = {
  patch_realtime: 'success',
  patch_dreaming: 'success',
  user_edit: 'warn',
  user_delete: 'danger',
  migration: 'neutral',
};

function AuditSection() {
  const [entries, setEntries] = useState<MemoryAuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [docFilter, setDocFilter] = useState<MemoryDocType | 'all'>('all');
  const [changeFilter, setChangeFilter] = useState<MemoryChangeType | 'all'>('all');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const refresh = () => {
    setLoading(true);
    listMemoryAudit({
      doc_type: docFilter === 'all' ? undefined : docFilter,
      change_type: changeFilter === 'all' ? undefined : changeFilter,
      limit: AUDIT_PAGE_SIZE,
      offset: (page - 1) * AUDIT_PAGE_SIZE,
    })
      .then((resp) => {
        setEntries(resp.entries);
        setTotal(resp.total);
      })
      .catch((e) => toast.error(extractErr(e, '审计日志加载失败')))
      .finally(() => setLoading(false));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(refresh, [docFilter, changeFilter, page]);

  const totalPages = Math.max(1, Math.ceil(total / AUDIT_PAGE_SIZE));

  return (
    <div>
      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap mb-3">
        <FilterGroup<MemoryDocType | 'all'>
          label="文档"
          value={docFilter}
          options={[
            { v: 'all', label: '全部' },
            { v: 'user_profile', label: '个人资料' },
            { v: 'knowledge', label: '知识' },
            { v: 'strategy', label: '策略' },
            { v: 'habit', label: '习惯' },
          ]}
          onChange={(v) => { setDocFilter(v); setPage(1); }}
        />
        <FilterGroup<MemoryChangeType | 'all'>
          label="变更"
          value={changeFilter}
          options={[
            { v: 'all', label: '全部' },
            { v: 'patch_realtime', label: '实时提取' },
            { v: 'patch_dreaming', label: '夜间整理' },
            { v: 'user_edit', label: '手动编辑' },
            { v: 'user_delete', label: '手动删除' },
            { v: 'migration', label: '迁移' },
          ]}
          onChange={(v) => { setChangeFilter(v); setPage(1); }}
        />
        <button
          onClick={refresh}
          className="ml-auto inline-flex items-center gap-1.5 text-xs text-stone-500 hover:text-stone-700 px-2 py-1"
        >
          <RefreshCw size={11} /> 刷新
        </button>
      </div>

      {loading && <LoadingBlock />}
      {!loading && entries.length === 0 && (
        <EmptyState
          icon={<History size={28} />}
          title="没有审计记录"
          description="切换筛选条件或来一次新对话试试。"
        />
      )}
      {!loading && entries.length > 0 && (
        <div className="border border-stone-200 rounded-lg overflow-hidden">
          {entries.map((e) => (
            <AuditRow
              key={e.id}
              entry={e}
              expanded={expandedId === e.id}
              onToggle={() => setExpandedId((id) => (id === e.id ? null : e.id))}
            />
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="mt-3 flex items-center justify-between text-xs text-stone-500">
          <span>共 {total} 条</span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="w-7 h-7 rounded hover:bg-stone-100 disabled:opacity-30 inline-flex items-center justify-center"
            >
              <ChevronLeft size={14} />
            </button>
            <span className="px-2">{page} / {totalPages}</span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="w-7 h-7 rounded hover:bg-stone-100 disabled:opacity-30 inline-flex items-center justify-center"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function FilterGroup<T extends string>({
  label, value, options, onChange,
}: {
  label: string;
  value: T;
  options: ReadonlyArray<{ v: T; label: string }>;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[11px] text-stone-400 uppercase tracking-wider">{label}</span>
      <div className="flex items-center gap-1">
        {options.map((o) => (
          <button
            key={o.v}
            onClick={() => onChange(o.v)}
            className={[
              'px-2 py-0.5 rounded-full text-[11px]',
              value === o.v
                ? 'bg-primary-50 text-primary-700 border border-primary-100'
                : 'text-stone-500 hover:bg-stone-100',
            ].join(' ')}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function AuditRow({
  entry, expanded, onToggle,
}: {
  entry: MemoryAuditEntry;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="border-b border-stone-100 last:border-b-0">
      <button
        onClick={onToggle}
        className="w-full px-3 py-2.5 text-left hover:bg-stone-50/60 flex items-start gap-3"
      >
        {expanded ? <ChevronDown size={14} className="mt-0.5 text-stone-400" />
                  : <ChevronRight size={14} className="mt-0.5 text-stone-400" />}
        <div className="text-xs font-mono text-stone-500 shrink-0 w-32">
          {entry.created_at
            ? new Date(entry.created_at).toLocaleString(undefined, {
                year: 'numeric', month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit',
              })
            : '—'}
        </div>
        <Pill tone={CHANGE_TYPE_TONE[entry.change_type]}>
          {CHANGE_TYPE_LABEL[entry.change_type]}
        </Pill>
        <div className="text-xs text-stone-500 shrink-0">
          {DOC_TYPE_LABEL[entry.doc_type]}
          {entry.topic && <span className="text-stone-400"> · {entry.topic}</span>}
        </div>
        <div className="text-sm text-stone-700 flex-1 truncate">{entry.summary}</div>
      </button>
      {expanded && <AuditDetail entryId={entry.id} entry={entry} />}
    </div>
  );
}

function AuditDetail({ entryId, entry }: { entryId: string; entry: MemoryAuditEntry }) {
  const [detail, setDetail] = useState<MemoryAuditDetail | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    setLoading(true);
    getMemoryAuditEntry(entryId)
      .then(setDetail)
      .catch((e) => toast.error(extractErr(e, '审计详情加载失败')))
      .finally(() => setLoading(false));
  }, [entryId]);
  return (
    <div className="bg-stone-50 px-3 py-3 border-t border-stone-100">
      {loading && <Spinner size={14} />}
      {detail && (
        <div className="space-y-2">
          {(entry.source_session_id || entry.source_record_id) && (
            <div className="flex items-center gap-3 text-[11px] font-mono text-stone-500">
              {entry.source_session_id && (
                <span className="inline-flex items-center gap-1">
                  <ExternalLink size={10} /> session={entry.source_session_id}
                </span>
              )}
              {entry.source_record_id && (
                <span className="inline-flex items-center gap-1">
                  <ExternalLink size={10} /> record={entry.source_record_id}
                </span>
              )}
            </div>
          )}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <DiffPane label="变更前 (before)" body={detail.before_body} />
            <DiffPane label="变更后 (after)" body={detail.after_body} highlight />
          </div>
        </div>
      )}
    </div>
  );
}

function DiffPane({
  label, body, highlight,
}: { label: string; body: string; highlight?: boolean }) {
  return (
    <div className="border border-stone-200 rounded bg-white">
      <div className="px-2.5 py-1 border-b border-stone-100 text-[10px] uppercase tracking-wider text-stone-500">
        {label}
      </div>
      <pre className={[
        'p-2 text-[11px] leading-snug font-mono whitespace-pre-wrap break-words overflow-x-auto max-h-[280px] overflow-y-auto',
        highlight ? 'text-stone-800' : 'text-stone-500',
      ].join(' ')}>
        {body || '（空）'}
      </pre>
    </div>
  );
}

// ── Shared ─────────────────────────────────────────────────────────────

function LoadingBlock() {
  return (
    <div className="py-8 flex items-center justify-center text-sm text-stone-500 gap-2">
      <Spinner size={14} /> 载入中…
    </div>
  );
}
