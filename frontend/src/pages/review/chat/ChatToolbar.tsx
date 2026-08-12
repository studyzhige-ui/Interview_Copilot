import { useEffect, useRef, useState } from 'react';
import {
  Send, Paperclip, Bot, MessageSquare, Square, Brain, X, FileText, AlertCircle,
} from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  KNOWLEDGE_ACCEPT,
  uploadKnowledgeFile,
  waitForKnowledgeDocument,
} from '@/api/knowledge';
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
  allowModeSwitch,
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
  questionIndexes,
  onRemoveQuestion,
  onClearQuestions,
}: {
  activeSessionId: string | null;
  externalMode: boolean;
  mode: Mode;
  setMode: (next: Mode | ((prev: Mode) => Mode)) => void;
  allowModeSwitch: boolean;
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
  questionIndexes: number[];
  onRemoveQuestion: (index: number) => void;
  onClearQuestions: () => void;
}) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const activeSessionRef = useRef(activeSessionId);
  const pollingRef = useRef<AbortController | null>(null);
  const [uploadState, setUploadState] = useState<{
    sessionId: string | null;
    active: boolean;
  }>({ sessionId: activeSessionId, active: false });
  const uploading = uploadState.sessionId === activeSessionId && uploadState.active;
  const isMounted = useIsMounted();

  useEffect(() => {
    activeSessionRef.current = activeSessionId;
    pollingRef.current?.abort();
    pollingRef.current = new AbortController();
    return () => pollingRef.current?.abort();
  }, [activeSessionId]);

  const onAttachFiles = async (files: FileList) => {
    if (!activeSessionId) return;
    const available = Math.max(0, 10 - attachments.length);
    if (available === 0) {
      toast.error('每轮最多附加 10 个文件');
      return;
    }
    const selected = Array.from(files).slice(0, available);
    if (selected.length < files.length) toast.error('每轮最多附加 10 个文件');
    const uploadSessionId = activeSessionId;
    const signal = pollingRef.current?.signal;
    setUploadState({ sessionId: uploadSessionId, active: true });
    let readyCount = 0;
    await Promise.all(selected.map(async (file) => {
      let documentId = '';
      try {
        const doc = await uploadKnowledgeFile(file, {
          category: '会话附件',
          source_kind: 'chat_attachment',
          conversation_id: uploadSessionId,
        });
        documentId = doc.id;
        if (!isMounted.current || activeSessionRef.current !== uploadSessionId) return;
        setAttachments((items) => [
          ...items,
          { document_id: doc.id, filename: file.name, status: 'processing' },
        ]);
        await waitForKnowledgeDocument(doc.id, { signal });
        if (!isMounted.current || activeSessionRef.current !== uploadSessionId) return;
        setAttachments((items) => items.map((item) => (
          item.document_id === doc.id ? { ...item, status: 'ready' } : item
        )));
        readyCount += 1;
      } catch (error) {
        if ((error as { name?: string })?.name === 'AbortError') return;
        const message = extractErr(error, `附件处理失败：${file.name}`);
        if (isMounted.current && activeSessionRef.current === uploadSessionId) {
          if (documentId) {
            setAttachments((items) => items.map((item) => (
              item.document_id === documentId
                ? { ...item, status: 'failed', error: message }
                : item
            )));
          }
          toast.error(message);
        }
      }
    }));
    if (!isMounted.current || activeSessionRef.current !== uploadSessionId) return;
    if (readyCount > 0) toast.success(`已附加 ${readyCount} 个文件`);
    setUploadState({ sessionId: uploadSessionId, active: false });
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!uploading && attachments.every((item) => item.status === 'ready')) onSend();
    }
  };

  const attachmentsReady = attachments.every((item) => item.status === 'ready');

  return (
    <div className="p-3 border-t border-stone-200">
      {questionIndexes.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-stone-400">引用题目</span>
          {questionIndexes.map((index) => (
            <button
              key={index}
              type="button"
              onClick={() => onRemoveQuestion(index)}
              title={`移除 Q${index}`}
              className="inline-flex max-w-full items-center gap-1 rounded-full bg-primary-50 px-2 py-1 text-[11px] text-primary-700 hover:bg-primary-100"
            >
              <span>Q{index}</span>
              <X size={11} />
            </button>
          ))}
          <button
            type="button"
            onClick={onClearQuestions}
            className="text-[11px] text-stone-400 hover:text-danger-500"
          >
            清空
          </button>
        </div>
      )}
      <div className="flex items-center gap-1.5 mb-2">
        {allowModeSwitch ? (
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
        ) : (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-primary-200 bg-primary-50 text-[11px] font-medium tracking-wider text-primary-700">
            <span className="w-1.5 h-1.5 rounded-full bg-primary-500" />
            <Bot size={11} /> 求职 AGENT
          </span>
        )}
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
          disabled={!activeSessionId || uploading || attachments.length >= 10}
          className="p-1.5 text-stone-500 hover:text-stone-700 disabled:opacity-50"
          title="附加文件"
        >
          {uploading ? <Spinner size={12} /> : <Paperclip size={14} />}
        </button>
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {attachments.length > 0 ? attachments.map((attachment) => (
            <span
              key={attachment.document_id}
              title={attachment.error || attachment.filename}
              className={[
                'inline-flex max-w-[150px] shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px]',
                attachment.status === 'failed'
                  ? 'border-danger-200 bg-danger-50 text-danger-700'
                  : 'border-stone-200 bg-stone-50 text-stone-600',
              ].join(' ')}
            >
              {attachment.status === 'processing' ? <Spinner size={10} />
                : attachment.status === 'failed' ? <AlertCircle size={10} />
                  : <FileText size={10} />}
              <span className="truncate">{attachment.filename}</span>
              <button
                type="button"
                onClick={() => setAttachments((items) => items.filter(
                  (item) => item.document_id !== attachment.document_id,
                ))}
                aria-label={`移除附件 ${attachment.filename}`}
              >
                <X size={10} />
              </button>
            </span>
          )) : (
            <span className="text-[11px] text-stone-400">点 📎 附加简历 / 文档</span>
          )}
        </div>
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
          disabled={!activeSessionId || streaming || uploading}
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
            disabled={!activeSessionId || !input.trim() || uploading || !attachmentsReady}
            className="w-9 h-9 rounded-lg bg-primary-500 text-white hover:bg-primary-600 flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Send size={14} />
          </button>
        )}
      </div>
    </div>
  );
}
