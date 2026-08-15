import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  Pencil,
  X as XIcon,
  Sparkles,
  Target,
  Briefcase,
  TrendingUp,
  FileCheck,
} from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  createChatSession,
  deleteChatSession,
  getChatSessionDeletionImpact,
  listChatSessions,
  renameChatSession,
} from '@/api/chat';
import type { ConversationDeletionImpact } from '@/types/api';
import { useToastOnError } from '@/hooks/useToastOnError';
import { ChatPanel } from '@/pages/review/chat/ChatPanel';
import { clearPersistedSessionState } from '@/pages/review/chat/usePersistedSessionState';
import type { ChatSessionListItem } from '@/types/api';
import { PromptStarterCard } from '@/components/ui/PromptStarterCard';
import {
  clearCopilotObjectHandoff,
  productObjectReferenceLabel,
  readCopilotObjectHandoff,
} from '@/lib/copilotObjectReference';

const SESSIONS_KEY = ['chat', 'sessions', { type: 'general' }] as const;

export function GeneralChatPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);

  const productObjectReference = useMemo(
    () => readCopilotObjectHandoff(searchParams),
    [searchParams],
  );
  const clearProductObjectReference = useCallback(() => {
    setSearchParams(clearCopilotObjectHandoff(searchParams), { replace: true });
  }, [searchParams, setSearchParams]);

  const { data: sessions = [], isPending: loading, error } = useQuery({
    queryKey: SESSIONS_KEY,
    queryFn: ({ signal }) => listChatSessions({ type: 'general' }, { signal }),
  });
  useToastOnError(error, '对话列表加载失败');

  const setSessions = useCallback(
    (updater: (cur: ChatSessionListItem[]) => ChatSessionListItem[]) => {
      void queryClient.cancelQueries({ queryKey: SESSIONS_KEY });
      queryClient.setQueryData<ChatSessionListItem[]>(
        SESSIONS_KEY,
        (cur) => updater(cur ?? []),
      );
    },
    [queryClient],
  );

  const selectedId = activeId && sessions.some((row) => row.session_id === activeId)
    ? activeId
    : sessions[0]?.session_id ?? null;

  useEffect(() => {
    if (!renaming) return;
    requestAnimationFrame(() => {
      const el = renameInputRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    });
  }, [renaming]);

  const onNew = async () => {
    if (creating) return;
    setCreating(true);
    try {
      const created = await createChatSession({
        type: 'general',
        title: `求职对话 ${sessions.length + 1}`,
      });
      setSessions((s) => [
        {
          session_id: created.session_id,
          title: created.title,
          type: created.type,
          state_summary: '',
          mode: 'agent',
          execution_mode: created.execution_mode,
          execution_mode_version: created.execution_mode_version,
          turn_count: 0,
          updated_at: new Date().toISOString(),
        },
        ...s,
      ]);
      setActiveId(created.session_id);
    } catch (e) {
      toast.error(extractErr(e, '创建对话失败'));
    } finally {
      setCreating(false);
    }
  };

  const [pendingDelete, setPendingDelete] = useState<{
    id: string;
    title: string;
    impact: ConversationDeletionImpact | null;
    error: string | null;
  } | null>(null);
  const [deletingChat, setDeletingChat] = useState(false);

  const onDelete = useCallback((id: string) => {
    const s = sessions.find((x) => x.session_id === id);
    const title = s?.title ?? '该会话';
    setPendingDelete({ id, title, impact: null, error: null });
    void getChatSessionDeletionImpact(id).then(
      (impact) => setPendingDelete((current) => (
        current?.id === id ? { ...current, impact, error: null } : current
      )),
      (error) => setPendingDelete((current) => (
        current?.id === id
          ? { ...current, error: extractErr(error, '删除影响暂时无法读取') }
          : current
      )),
    );
  }, [sessions]);

  const confirmDelete = useCallback(async () => {
    if (!pendingDelete?.impact) return;
    const id = pendingDelete.id;
    setDeletingChat(true);
    try {
      await deleteChatSession(id, pendingDelete.impact);
      clearPersistedSessionState(id);
      setSessions((s) => s.filter((x) => x.session_id !== id));
      setPendingDelete(null);
    } catch (e) {
      toast.error(extractErr(e, '删除对话失败'));
    } finally {
      setDeletingChat(false);
    }
  }, [pendingDelete, setSessions]);

  const commitRename = useCallback(async () => {
    if (!renaming) return;
    const title = renaming.title.trim();
    if (!title) { setRenaming(null); return; }
    try {
      await renameChatSession(renaming.id, title);
      setSessions((s) =>
        s.map((x) => x.session_id === renaming.id ? { ...x, title } : x),
      );
    } catch (e) {
      toast.error(extractErr(e, '重命名失败'));
    } finally {
      setRenaming(null);
    }
  }, [renaming, setSessions]);

  const activeSession = sessions.find((s) => s.session_id === selectedId);

  return (
    <div className="flex h-full bg-[#F8FAFC] overflow-hidden">
      {/* Left Sidebar: Session List */}
      <aside className="w-[280px] shrink-0 bg-white/90 backdrop-blur-md border-r border-slate-200/80 flex flex-col h-full select-none">
        <div className="p-3.5 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-sm font-bold text-slate-800 tracking-tight">
            <span>Copilot</span>
            <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">
              {sessions.length}
            </span>
          </div>

          <button
            type="button"
            onClick={onNew}
            disabled={creating}
            title="新建对话"
            className="flex items-center gap-1 px-3 py-1.5 rounded-full bg-blue-50 hover:bg-blue-100 text-blue-600 text-xs font-semibold transition-all active:scale-95 shadow-xs cursor-pointer disabled:opacity-50"
          >
            <Plus size={14} />
            <span>新建</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {loading ? (
            <div className="p-8 flex items-center justify-center text-slate-400">
              <Spinner size={18} />
            </div>
          ) : sessions.length === 0 ? (
            <div className="p-8 text-center text-slate-400">
              <div className="w-10 h-10 mx-auto rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center mb-2">
                <Sparkles size={18} />
              </div>
              <div className="text-xs font-medium text-slate-700">暂无对话记录</div>
              <p className="text-[11px] text-slate-400 mt-1">点上方「新建」即可开始畅聊</p>
            </div>
          ) : (
            sessions.map((s) => {
              const act = s.session_id === selectedId;
              const editing = renaming?.id === s.session_id;

              return (
                <div
                  key={s.session_id}
                  className={[
                    'group relative p-3 rounded-2xl cursor-pointer transition-all duration-150 border',
                    act
                      ? 'bg-blue-50/80 border-blue-200/90 shadow-xs ring-1 ring-blue-100'
                      : 'bg-transparent border-transparent hover:bg-slate-50 hover:border-slate-200/60',
                  ].join(' ')}
                  onClick={() => !editing && setActiveId(s.session_id)}
                >
                  {editing ? (
                    <input
                      ref={renameInputRef}
                      value={renaming!.title}
                      onChange={(e) => setRenaming({ id: s.session_id, title: e.target.value })}
                      onBlur={() => { void commitRename(); }}
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => {
                        e.stopPropagation();
                        if (e.key === 'Enter') { e.preventDefault(); void commitRename(); }
                        else if (e.key === 'Escape') { e.preventDefault(); setRenaming(null); }
                      }}
                      placeholder="按 Enter 保存，Esc 取消"
                      className="w-full text-xs font-semibold px-2 py-1 bg-white border border-blue-400 rounded-lg outline-none"
                    />
                  ) : (
                    <>
                      <div className={`text-sm font-semibold truncate pr-12 ${act ? 'text-blue-900' : 'text-slate-800'}`}>
                        {s.title}
                      </div>

                      {s.turn_count > 0 && (
                        <div className="text-xs text-slate-400 mt-1">
                          {s.turn_count} 轮对话 · {new Date(s.updated_at).toLocaleString('zh-CN', {
                            month: '2-digit', day: '2-digit',
                            hour: '2-digit', minute: '2-digit',
                          })}
                        </div>
                      )}

                      <div className="absolute right-2 top-2.5 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setRenaming({ id: s.session_id, title: s.title });
                          }}
                          title="重命名"
                          className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 transition-colors"
                        >
                          <Pencil size={12} />
                        </button>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); void onDelete(s.session_id); }}
                          title="删除"
                          className="p-1 rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                        >
                          <XIcon size={12} />
                        </button>
                      </div>
                    </>
                  )}
                </div>
              );
            })
          )}
        </div>
      </aside>

      {/* Main Conversation Stage or Welcome Hero */}
      {selectedId ? (
        <div className="flex-1 min-w-0 flex flex-col h-full bg-[#F8FAFC]">
          <ChatPanel
            sessionId={selectedId}
            sessionTitle={activeSession?.title ?? 'Copilot'}
            fixedMode="AGENT"
            flexible
            productObjectReferences={productObjectReference ? [productObjectReference] : []}
            onRemoveProductObjectReference={clearProductObjectReference}
            onProductObjectReferencesConsumed={clearProductObjectReference}
          />
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center p-8 overflow-y-auto">
          <div className="max-w-2xl w-full text-center space-y-6 animate-in fade-in duration-300">
            {/* Ambient Sparkle Badge */}
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-blue-50 border border-blue-100 text-blue-700 text-xs font-semibold shadow-xs">
              <Sparkles size={15} className="text-blue-600" />
              <span>AI 智能求职与面试辅导</span>
            </div>

            {/* Greeting Headline */}
            <h2 className="text-3xl md:text-4xl font-extrabold text-slate-900 tracking-tight">
              今天想演练或攻克哪家大厂的面试？
            </h2>
            <p className="text-sm md:text-base text-slate-600 max-w-lg mx-auto leading-relaxed">
              全天候 AI 求职副驾。随时提问、演练核心项目、优化 STAR 经历或定制求职策略。
            </p>

            {/* Prompt Starter Bento Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 pt-4 text-left">
              <PromptStarterCard
                icon={<Target size={20} />}
                tag="匹配评估"
                title="岗位匹配度与差距诊断"
                description="评估我的个人技能树与目标岗位 JD 的匹配度，生成针对性复习清单。"
                onClick={onNew}
              />
              <PromptStarterCard
                icon={<Briefcase size={20} />}
                tag="高频追问"
                title="大厂项目深挖与八股演练"
                description="根据我的微服务与高并发架构经历，模拟大厂面试官连续追问。"
                onClick={onNew}
              />
              <PromptStarterCard
                icon={<FileCheck size={20} />}
                tag="经历优化"
                title="STAR 经历亮点重构"
                description="用 STAR 原则深度润色一段平淡的项目经历，突出可量化的业务价值。"
                onClick={onNew}
              />
              <PromptStarterCard
                icon={<TrendingUp size={20} />}
                tag="Offer 决策"
                title="薪资沟通与 Offer 谈判"
                description="拿到大厂 Offer 后，如何礼貌且有力地向 HR 争取更高定级与薪资。"
                onClick={onNew}
              />
            </div>

            {productObjectReference && (
              <div className="mt-4 rounded-2xl border border-blue-200 bg-blue-50/80 p-3.5 text-xs text-blue-800 font-medium">
                已选中关联对象：{productObjectReferenceLabel(productObjectReference)}。点击上方任意卡片新建会话后将自动挂载。
              </div>
            )}
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      <ConfirmDialog
        open={!!pendingDelete}
        danger
        title="删除对话"
        description={
          pendingDelete
            ? pendingDelete.error
              ?? (pendingDelete.impact
                ? `确定删除「${pendingDelete.title}」？\n\n${pendingDelete.impact.disclosures.join('\n')}`
                : '正在读取待发送输入、附件、消息与外部调用影响……')
            : ''
        }
        confirmText="删除"
        loading={deletingChat}
        confirmDisabled={!pendingDelete?.impact || !!pendingDelete?.error}
        onConfirm={() => { void confirmDelete(); }}
        onCancel={() => { if (!deletingChat) setPendingDelete(null); }}
      />
    </div>
  );
}
