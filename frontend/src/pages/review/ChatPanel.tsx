import { useEffect, useRef, useState } from 'react';
import {
  Send,
  Paperclip,
  Bot,
  MessageSquare,
  Sparkles,
  ChevronDown,
  Plus,
  Pencil,
  X as XIcon,
} from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  createChatSession,
  deleteChatSession,
  getChatHistory,
  listChatSessions,
  renameChatSession,
} from '@/api/chat';
import { uploadKnowledgeFile } from '@/api/knowledge';
import { getModelsRuntime, updateModelsRuntime, getModelsCatalog } from '@/api/models';
import { useChatStream } from '@/hooks/useChatStream';
import type { ChatMessageItem, ChatSessionListItem, ModelProfile, ModelRole } from '@/types/api';

interface Props {
  /** Real InterviewRecord id, or null for unscoped general chat. */
  interviewId: string | null;
  /** Title of the currently selected interview record (for header subtitle). */
  interviewTitle: string | null;
  width?: number;
}

interface UIMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

interface Attachment {
  doc_id: string;
  filename: string;
}

type Mode = 'CHAT' | 'AGENT';

function toUI(m: ChatMessageItem): UIMessage {
  return {
    role: m.role === 'user' ? 'user' : m.role === 'assistant' ? 'assistant' : 'system',
    content: m.content,
  };
}

export function ChatPanel({ interviewId, interviewTitle, width = 360 }: Props) {
  const [sessions, setSessions] = useState<ChatSessionListItem[]>([]);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState<Mode>('CHAT');
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [modelName, setModelName] = useState('DeepSeek V4 Flash');
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [primaryId, setPrimaryId] = useState<string>('');
  const listRef = useRef<HTMLDivElement | null>(null);
  const modelRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // Load model info once on mount.
  useEffect(() => {
    getModelsRuntime()
      .then((rt) => {
        const resolved = rt.resolved?.primary;
        if (resolved) {
          setModelName(resolved.display_name);
          setPrimaryId(resolved.profile_id);
        }
      })
      .catch(() => {});
    getModelsCatalog()
      .then((c) => setProfiles(c.profiles))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!modelRef.current?.contains(e.target as Node)) setModelOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const stream = useChatStream(activeSession, (final) => {
    if (final) setMessages((m) => [...m, { role: 'assistant', content: final }]);
  });

  // Refetch session list when scope (interviewId) changes.
  // - interviewId set: load that interview's debrief sessions; auto-create one if none.
  // - interviewId null: load general (no interview_id) sessions; user creates manually.
  useEffect(() => {
    let alive = true;
    const q = interviewId
      ? { session_type: 'debrief', interview_id: interviewId }
      : { session_type: 'general' };
    listChatSessions(q)
      .then(async (rows) => {
        if (!alive) return;
        setSessions(rows);
        if (rows.length > 0) {
          setActiveSession(rows[0].session_id);
          return;
        }
        // No debrief chat yet for this record — seed one automatically so the
        // user can immediately type. (Spec: 分析完成后自动新增一个对话栏)
        if (interviewId) {
          try {
            const created = await createChatSession({
              session_type: 'debrief',
              interview_id: interviewId,
              title: '复盘对话 1',
            });
            if (!alive) return;
            setSessions([{
              session_id: created.session_id,
              title: created.title,
              session_type: created.session_type,
              state_summary: '',
              turn_count: 0,
              updated_at: new Date().toISOString(),
            }]);
            setActiveSession(created.session_id);
          } catch (e) {
            if (alive) toast.error(extractErr(e, '自动创建对话失败'));
          }
        } else {
          setActiveSession(null);
        }
      })
      .catch((e) => alive && toast.error(extractErr(e, '对话列表加载失败')));
    return () => { alive = false; };
  }, [interviewId]);

  // Load history for the active session.
  useEffect(() => {
    if (!activeSession) { setMessages([]); return; }
    let alive = true;
    getChatHistory(activeSession, 0, 100)
      .then((rows) => alive && setMessages(rows.map(toUI)))
      .catch(() => alive && setMessages([]));
    return () => { alive = false; };
  }, [activeSession]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, stream.buffer]);

  const newChat = async () => {
    setCreating(true);
    try {
      const payload = interviewId
        ? { session_type: 'debrief' as const, interview_id: interviewId, title: `对话 ${sessions.length + 1}` }
        : { session_type: 'general' as const, title: `对话 ${sessions.length + 1}` };
      const created = await createChatSession(payload);
      setSessions((s) => [
        {
          session_id: created.session_id,
          title: created.title,
          session_type: created.session_type,
          state_summary: '',
          turn_count: 0,
          updated_at: new Date().toISOString(),
        },
        ...s,
      ]);
      setActiveSession(created.session_id);
    } catch (e) {
      toast.error(extractErr(e, '创建对话失败'));
    } finally {
      setCreating(false);
    }
  };

  const removeChat = async (id: string) => {
    try {
      await deleteChatSession(id);
      setSessions((s) => {
        const next = s.filter((x) => x.session_id !== id);
        if (activeSession === id) setActiveSession(next[0]?.session_id ?? null);
        return next;
      });
    } catch (e) {
      toast.error(extractErr(e, '删除对话失败'));
    }
  };

  const commitRename = async () => {
    if (!renaming) return;
    const title = renaming.title.trim();
    if (!title) { setRenaming(null); return; }
    try {
      await renameChatSession(renaming.id, title);
      setSessions((s) => s.map((x) => x.session_id === renaming.id ? { ...x, title } : x));
    } catch (e) {
      toast.error(extractErr(e, '重命名失败'));
    }
    setRenaming(null);
  };

  const onAttachFiles = async (files: FileList) => {
    setUploading(true);
    const added: Attachment[] = [];
    for (const f of Array.from(files)) {
      try {
        const doc = await uploadKnowledgeFile(f, { category: 'chat_attachment', source_type: 'official_docs' });
        added.push({ doc_id: doc.id, filename: f.name });
      } catch {
        toast.error(`附件上传失败：${f.name}`);
      }
    }
    if (added.length > 0) {
      setAttachments((arr) => [...arr, ...added]);
      toast.success(`已附加 ${added.length} 个文件`);
    }
    setUploading(false);
  };

  const send = () => {
    const text = input.trim();
    if (!text || !activeSession || stream.isStreaming) return;
    let payload = text;
    if (attachments.length > 0) {
      const tail = attachments.map((a) => `[附件: ${a.filename} (doc=${a.doc_id})]`).join('\n');
      payload = `${tail}\n\n${text}`;
    }
    setMessages((m) => [...m, { role: 'user', content: payload }]);
    stream.send(payload);
    setInput('');
    setAttachments([]);
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const onPickModel = async (p: ModelProfile) => {
    if (!p.ready) {
      toast.warn(`需先配置 ${p.api_key_env}`);
      return;
    }
    setModelOpen(false);
    setModelName(p.display_name);
    setPrimaryId(p.id);
    try {
      const patch: Partial<Record<ModelRole, string>> = { primary: p.id };
      await updateModelsRuntime(patch);
      toast.success(`已切换为 ${p.display_name}`);
    } catch {
      toast.error('切换模型失败');
    }
  };

  // Subtitle reflects the chat scope, not the chat session title.
  const subtitle = interviewId ? interviewTitle ?? '基于本次记录' : '通用对话（未绑定面试）';

  return (
    <aside
      style={{ width }}
      className="shrink-0 bg-white border-l border-stone-200 flex flex-col"
    >
      <Header
        subtitle={subtitle}
        modelRef={modelRef}
        modelName={modelName}
        modelOpen={modelOpen}
        setModelOpen={setModelOpen}
        profiles={profiles}
        primaryId={primaryId}
        onPickModel={onPickModel}
      />

      {/* Chat tabs row */}
      <div className="px-3 py-2.5 border-b border-stone-200 flex items-center gap-1.5 overflow-x-auto">
        {sessions.length === 0 && (
          <span className="text-xs text-stone-400">点 + 开始一段对话</span>
        )}
        {sessions.map((s) => {
          const act = s.session_id === activeSession;
          const isEditing = renaming?.id === s.session_id;
          return (
            <div key={s.session_id} className="group relative shrink-0">
              {isEditing ? (
                <input
                  autoFocus
                  value={renaming!.title}
                  onChange={(e) => setRenaming({ id: s.session_id, title: e.target.value })}
                  onBlur={commitRename}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRename();
                    if (e.key === 'Escape') setRenaming(null);
                  }}
                  className="w-28 px-2.5 py-1 text-xs rounded-full border border-accent-300 outline-none bg-white"
                />
              ) : (
                <div
                  className={[
                    'inline-flex items-center gap-1 pl-3 pr-1 py-1 rounded-full border cursor-pointer transition-colors',
                    act
                      ? 'bg-primary-50 border-primary-200'
                      : 'bg-white border-stone-200 hover:bg-stone-50',
                  ].join(' ')}
                  onDoubleClick={() => setRenaming({ id: s.session_id, title: s.title })}
                >
                  <span
                    onClick={() => setActiveSession(s.session_id)}
                    className={[
                      'text-xs truncate max-w-[110px]',
                      act ? 'text-primary-700 font-semibold' : 'text-stone-700 font-medium',
                    ].join(' ')}
                  >
                    {s.title}
                  </span>
                  <span className={`inline-flex items-center ${act ? '' : 'opacity-0 group-hover:opacity-100'}`}>
                    <button
                      onClick={(e) => { e.stopPropagation(); setRenaming({ id: s.session_id, title: s.title }); }}
                      title="重命名"
                      className="w-5 h-5 rounded-full text-stone-400 hover:text-stone-600 inline-flex items-center justify-center"
                    >
                      <Pencil size={10} />
                    </button>
                    {sessions.length > 1 && (
                      <button
                        onClick={(e) => { e.stopPropagation(); removeChat(s.session_id); }}
                        title="删除"
                        className="w-5 h-5 rounded-full text-stone-400 hover:text-danger-500 inline-flex items-center justify-center"
                      >
                        <XIcon size={10} />
                      </button>
                    )}
                  </span>
                </div>
              )}
            </div>
          );
        })}
        <button
          onClick={newChat}
          disabled={creating}
          title="新对话"
          className="w-[26px] h-[26px] rounded-full border border-dashed border-stone-300 text-stone-500 hover:bg-stone-50 inline-flex items-center justify-center shrink-0 disabled:opacity-50"
        >
          <Plus size={12} />
        </button>
      </div>

      {/* Messages */}
      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-3">
        {!activeSession && (
          <div className="m-auto text-center text-stone-400 px-6">
            <div className="w-11 h-11 mx-auto rounded-2xl bg-stone-100 text-stone-400 flex items-center justify-center mb-3">
              <Sparkles size={18} />
            </div>
            <div className="text-[13px] text-stone-500 font-medium mb-1">点 + 开始一段对话</div>
            <div className="text-[11px] leading-relaxed">
              {interviewId ? '上传解析完成后会自动给出复盘建议' : '不绑定面试也可以使用通用对话'}
            </div>
          </div>
        )}
        {activeSession && messages.length === 0 && !stream.isStreaming && (
          <div className="m-auto text-center text-stone-400 px-6">
            <div className="w-11 h-11 mx-auto rounded-2xl bg-stone-100 text-stone-400 flex items-center justify-center mb-3">
              <Sparkles size={18} />
            </div>
            <div className="text-[13px] text-stone-500 font-medium mb-1">
              {interviewId ? '上传解析完成后会自动给出复盘建议' : '说点什么开始对话'}
            </div>
            <div className="text-[11px] leading-relaxed">
              输入消息后会看到流式生成的回答
            </div>
          </div>
        )}
        {messages.map((m, i) => <Bubble key={i} role={m.role} content={m.content} />)}
        {stream.isStreaming && stream.buffer && (
          <Bubble role="assistant" content={stream.buffer} streaming />
        )}
      </div>

      {/* Toolbar */}
      <div className="p-3 border-t border-stone-200">
        <div className="flex items-center gap-1.5 mb-2">
          <button
            onClick={() => setMode((m) => (m === 'AGENT' ? 'CHAT' : 'AGENT'))}
            className={[
              'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-medium tracking-wider',
              mode === 'AGENT'
                ? 'bg-primary-50 border-primary-200 text-primary-700'
                : 'bg-white border-stone-200 text-stone-600',
            ].join(' ')}
          >
            <span className={[
              'w-1.5 h-1.5 rounded-full',
              mode === 'AGENT' ? 'bg-primary-500' : 'bg-stone-400',
            ].join(' ')} />
            {mode === 'AGENT' ? <><Bot size={11} /> AGENT</> : <><MessageSquare size={11} /> CHAT</>}
          </button>
          <input
            ref={fileRef}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) onAttachFiles(e.target.files);
              e.target.value = '';
            }}
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="p-1.5 text-stone-500 hover:text-stone-700 disabled:opacity-50"
            title="附加文件"
          >
            {uploading ? <Spinner size={12} /> : <Paperclip size={14} />}
          </button>
          <span className="text-[11px] text-stone-400 truncate flex-1">
            {attachments.length > 0
              ? attachments.map((a) => a.filename).join(' · ')
              : '点 📎 附加简历 / 文档'}
          </span>
          {attachments.length > 0 && (
            <button
              onClick={() => setAttachments([])}
              className="text-[11px] text-stone-400 hover:text-danger-500"
            >
              清空
            </button>
          )}
        </div>
        <div className="flex items-end gap-1.5">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKey}
            disabled={!activeSession || stream.isStreaming}
            placeholder={
              activeSession
                ? '问点什么 · Shift+Enter 换行'
                : '先点 + 新建一段对话'
            }
            rows={2}
            className="flex-1 resize-none border border-stone-200 rounded-lg px-3 py-2 text-[13px] outline-none focus:border-primary-300 bg-stone-50 text-stone-800 disabled:opacity-50"
          />
          <button
            onClick={send}
            disabled={!activeSession || !input.trim() || stream.isStreaming}
            className="w-9 h-9 rounded-lg bg-primary-500 text-white hover:bg-primary-600 flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Send size={14} />
          </button>
        </div>
      </div>
    </aside>
  );
}

function Header({
  subtitle,
  modelRef,
  modelName,
  modelOpen,
  setModelOpen,
  profiles,
  primaryId,
  onPickModel,
}: {
  subtitle: string;
  modelRef: React.RefObject<HTMLDivElement>;
  modelName: string;
  modelOpen: boolean;
  setModelOpen: (v: boolean) => void;
  profiles: ModelProfile[];
  primaryId: string;
  onPickModel: (p: ModelProfile) => void;
}) {
  return (
    <div className="px-4 pt-3.5 pb-2 flex items-start justify-between gap-2">
      <div className="min-w-0">
        <div className="text-[13px] font-semibold text-stone-800">复盘对话</div>
        <div className="text-[11px] text-stone-500 mt-0.5 truncate">{subtitle}</div>
      </div>
      <div ref={modelRef} className="relative shrink-0">
        <button
          onClick={() => setModelOpen(!modelOpen)}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-stone-200 bg-stone-50 text-stone-700 text-[11px] hover:bg-stone-100 font-mono"
        >
          <Sparkles size={11} className="text-accent-700" />
          <span className="truncate max-w-[140px]">{modelName}</span>
          <ChevronDown size={11} className="text-stone-400" />
        </button>
        {modelOpen && (
          <div className="absolute top-full right-0 mt-1 w-[220px] max-h-[300px] overflow-y-auto p-1 bg-white border border-stone-200 rounded-lg shadow-lg z-20">
            {profiles.length === 0 && (
              <div className="px-2.5 py-2 text-[11px] text-stone-400">载入中…</div>
            )}
            {profiles.map((p) => {
              const sel = p.id === primaryId;
              return (
                <div
                  key={p.id}
                  onClick={() => onPickModel(p)}
                  className={[
                    'px-2.5 py-1.5 rounded-md cursor-pointer leading-tight',
                    sel ? 'bg-primary-50 text-primary-700' : 'text-stone-700 hover:bg-stone-50',
                    !p.ready ? 'opacity-60' : '',
                  ].join(' ')}
                >
                  <div className="font-sans font-medium text-[12px]">{p.display_name}</div>
                  <div className="text-[10px] text-stone-400 truncate font-mono">{p.model}</div>
                  {!p.ready && <div className="text-[10px] text-warning-700">未配置 {p.api_key_env}</div>}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function Bubble({ role, content, streaming }: { role: UIMessage['role']; content: string; streaming?: boolean }) {
  const mine = role === 'user';
  return (
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div
        className={[
          'max-w-[85%] px-3.5 py-2.5 text-[13px] leading-relaxed whitespace-pre-wrap',
          mine
            ? 'bg-primary-500 text-white rounded-[14px] rounded-br-[4px]'
            : role === 'system'
            ? 'bg-warning-50 text-warning-700 rounded-[14px] text-xs italic'
            : 'bg-stone-100 text-stone-800 rounded-[14px] rounded-bl-[4px]',
        ].join(' ')}
      >
        {content}
        {streaming && <span className="inline-block w-1.5 h-3 ml-1 bg-current animate-pulse align-middle" />}
      </div>
    </div>
  );
}
