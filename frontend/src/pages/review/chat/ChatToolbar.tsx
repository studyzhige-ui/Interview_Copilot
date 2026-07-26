import { useRef, useState } from 'react';
import {
  Send, Paperclip, Bot, MessageSquare, Square, Brain,
} from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import { KNOWLEDGE_ACCEPT, uploadKnowledgeFile } from '@/api/knowledge';
import { useIsMounted } from '@/hooks/useIsMounted';
import type { Attachment, Mode } from './types';
import { SessionCapabilities } from './SessionCapabilities';

/**
 * Bottom toolbar: mode pill, global-memory toggle, attachment picker,
 * input textarea, and the send / stop button. Owns the attachment
 * upload state; everything else comes in as props.
 */
export function ChatToolbar({
  activeSessionId,
  externalMode,
  mode,
  setMode,
  globalMemoryOn,
  togglingMemory,
  onToggleGlobalMemory,
  input,
  setInput,
  streaming,
  onSend,
  onCancel,
  attachments,
  setAttachments,
}: {
  activeSessionId: string | null;
  externalMode: boolean;
  mode: Mode;
  setMode: (next: Mode | ((prev: Mode) => Mode)) => void;
  globalMemoryOn: boolean;
  togglingMemory: boolean;
  onToggleGlobalMemory: () => void;
  input: string;
  setInput: (v: string) => void;
  streaming: boolean;
  onSend: () => void;
  onCancel: () => void;
  attachments: Attachment[];
  setAttachments: React.Dispatch<React.SetStateAction<Attachment[]>>;
}) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const isMounted = useIsMounted();

  const onAttachFiles = async (files: FileList) => {
    setUploading(true);
    const added: Attachment[] = [];
    for (const f of Array.from(files)) {
      try {
        const doc = await uploadKnowledgeFile(f, { category: 'chat_attachment', source_kind: 'user_upload' });
        added.push({ doc_id: doc.id, filename: f.name });
      } catch (e) {
        // Surface the backend's specific message (e.g. the format-whitelist
        // rejection or a parser-level friendly error) instead of a generic failure.
        if (isMounted.current) toast.error(extractErr(e, `附件上传失败：${f.name}`));
      }
    }
    // Bail before touching state if the user navigated away during
    // a slow upload — multi-file uploads can take 10+ seconds.
    if (!isMounted.current) return;
    if (added.length > 0) {
      setAttachments((arr) => [...arr, ...added]);
      toast.success(`已附加 ${added.length} 个文件`);
    }
    setUploading(false);
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend(); }
  };

  return (
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
        <SessionCapabilities sessionId={activeSessionId} />
        <button
          onClick={onToggleGlobalMemory}
          disabled={!activeSessionId || togglingMemory}
          title={
            globalMemoryOn
              ? '关闭全局记忆（本会话不再注入跨会话记忆）'
              : '开启全局记忆（本会话注入个人资料 + 知识 / 策略 / 习惯）'
          }
          className={[
            'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-medium tracking-wider disabled:opacity-50',
            globalMemoryOn
              ? 'bg-accent-50 border-accent-200 text-accent-700'
              : 'bg-white border-stone-200 text-stone-600',
          ].join(' ')}
        >
          <Brain size={11} />
          {globalMemoryOn ? '全局记忆 · 开' : '全局记忆 · 关'}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept={KNOWLEDGE_ACCEPT}
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
          disabled={!activeSessionId || streaming}
          placeholder={
            activeSessionId
              ? '问点什么 · Shift+Enter 换行'
              : (externalMode ? '先在左侧选择' : '点右上 + 新建一段会话')
          }
          rows={2}
          className="flex-1 resize-none border border-stone-200 rounded-lg px-3 py-2 text-[13px] outline-none focus:border-primary-300 bg-stone-50 text-stone-800 disabled:opacity-50"
        />
        {streaming ? (
          <button
            onClick={onCancel}
            title="停止任务"
            aria-label="停止任务"
            className="w-9 h-9 rounded-lg bg-danger-500 text-white hover:bg-danger-700 flex items-center justify-center"
          >
            <Square size={12} fill="currentColor" />
          </button>
        ) : (
          <button
            onClick={onSend}
            disabled={!activeSessionId || !input.trim()}
            className="w-9 h-9 rounded-lg bg-primary-500 text-white hover:bg-primary-600 flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Send size={14} />
          </button>
        )}
      </div>
    </div>
  );
}
