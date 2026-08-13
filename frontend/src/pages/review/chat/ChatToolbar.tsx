import { useEffect, useRef, useState } from 'react';
import {
  Send, Paperclip, Bot, MessageSquare, Square, X, FileText, AlertCircle,
  Pencil, RotateCcw, Trash2, Zap,
  Link2,
} from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import { KNOWLEDGE_ACCEPT } from '@/api/knowledge';
import { uploadFileAsset } from '@/api/fileAssets';
import {
  createAttachmentDraft,
  removeAttachmentDraft,
  retryAttachmentSource,
  waitForAttachmentDraft,
} from '@/api/chat';
import { useIsMounted } from '@/hooks/useIsMounted';
import type { PendingSubmissionItem, ProductObjectReference } from '@/types/api';
import { productObjectReferenceLabel } from '@/lib/copilotObjectReference';
import type { Attachment, Mode } from './types';

/**
 * Bottom toolbar: mode pill, attachment picker, input textarea, and the
 * send / stop button. Owns the attachment upload state; everything else
 * comes in as props.
 */
export function ChatToolbar({
  activeSessionId,
  externalMode,
  mode,
  setMode,
  allowModeSwitch,
  executionMode,
  setExecutionMode,
  executionModePending,
  input,
  setInput,
  streaming,
  onSend,
  onCancel,
  attachments,
  setAttachments,
  pendingSubmissions,
  activeTurnId,
  onUpdatePendingSubmission,
  onWithdrawPendingSubmission,
  onRetryPendingSubmission,
  onInterruptForSubmission,
  questionIndexes,
  onRemoveQuestion,
  onClearQuestions,
  productObjectReferences,
  onRemoveProductObjectReference,
}: {
  activeSessionId: string | null;
  externalMode: boolean;
  mode: Mode;
  setMode: (next: Mode | ((prev: Mode) => Mode)) => void;
  allowModeSwitch: boolean;
  executionMode: 'standard' | 'auto';
  setExecutionMode: (next: 'standard' | 'auto') => Promise<void>;
  executionModePending: boolean;
  input: string;
  setInput: (v: string) => void;
  streaming: boolean;
  onSend: () => void;
  onCancel: () => void;
  attachments: Attachment[];
  setAttachments: React.Dispatch<React.SetStateAction<Attachment[]>>;
  pendingSubmissions: PendingSubmissionItem[];
  activeTurnId: string | null;
  onUpdatePendingSubmission: (
    submission: PendingSubmissionItem,
    update: Pick<PendingSubmissionItem, 'message' | 'mode' | 'execution_mode' | 'question_indexes' | 'attachments' | 'object_references'>,
  ) => Promise<void>;
  onWithdrawPendingSubmission: (submission: PendingSubmissionItem) => Promise<void>;
  onRetryPendingSubmission: (submission: PendingSubmissionItem) => Promise<void>;
  onInterruptForSubmission: (submission: PendingSubmissionItem) => Promise<void>;
  questionIndexes: number[];
  onRemoveQuestion: (index: number) => void;
  onClearQuestions: () => void;
  productObjectReferences: ProductObjectReference[];
  onRemoveProductObjectReference: (reference: ProductObjectReference) => void;
}) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const activeSessionRef = useRef(activeSessionId);
  const pollingRef = useRef<AbortController | null>(null);
  const [uploadState, setUploadState] = useState<{
    sessionId: string | null;
    active: boolean;
  }>({ sessionId: activeSessionId, active: false });
  const [editing, setEditing] = useState<{
    submissionId: string;
    message: string;
    mode: 'chat' | 'agent';
    executionMode: 'standard' | 'auto';
    questionIndexes: string;
  } | null>(null);
  const [actingSubmissionId, setActingSubmissionId] = useState<string | null>(null);
  const [retryingDraftId, setRetryingDraftId] = useState<string | null>(null);
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
      let draftId = '';
      try {
        const fileAssetId = await uploadFileAsset(file, 'knowledge_document');
        const draft = await createAttachmentDraft(uploadSessionId, fileAssetId);
        draftId = draft.draft_id;
        if (!isMounted.current || activeSessionRef.current !== uploadSessionId) return;
        const initialStatus = draft.status === 'failed' ? 'failed'
          : draft.status === 'ready' ? 'ready' : 'processing';
        setAttachments((items) => [
          ...items,
          {
            draft_id: draft.draft_id,
            file_asset_id: draft.file_asset_id,
            filename: file.name,
            status: initialStatus,
            ...(draft.error_message ? { error: draft.error_message } : {}),
          },
        ]);
        if (draft.status === 'processing') {
          void waitForAttachmentDraft(
            uploadSessionId,
            draft.draft_id,
            { signal },
          ).then((settled) => {
            if (!isMounted.current || activeSessionRef.current !== uploadSessionId) return;
            setAttachments((items) => items.map((item) => (
              item.draft_id === draft.draft_id
                ? {
                    ...item,
                    status: settled.status === 'ready' ? 'ready' : 'failed',
                    error: settled.error_message ?? undefined,
                  }
                : item
            )));
            if (settled.status === 'ready') toast.success(`附件已就绪：${file.name}`);
          }).catch((error) => {
            if ((error as { name?: string })?.name !== 'AbortError') {
              toast.error(extractErr(error, `附件状态检查失败：${file.name}`));
            }
          });
        } else if (draft.status === 'ready') {
          readyCount += 1;
        }
      } catch (error) {
        if ((error as { name?: string })?.name === 'AbortError') return;
        const message = extractErr(error, `附件处理失败：${file.name}`);
        if (isMounted.current && activeSessionRef.current === uploadSessionId) {
          if (draftId) {
            setAttachments((items) => items.map((item) => (
              item.draft_id === draftId
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
      if (!uploading && attachments.every((item) => item.status !== 'failed')) onSend();
    }
  };

  const attachmentsReady = attachments.every((item) => item.status !== 'failed');

  const removeDraft = (attachment: Attachment) => {
    if (!activeSessionId) return;
    setAttachments((items) => items.filter((item) => item.draft_id !== attachment.draft_id));
    void removeAttachmentDraft(activeSessionId, attachment.draft_id).catch((error) => {
      toast.error(extractErr(error, `移除附件失败：${attachment.filename}`));
      if (activeSessionRef.current === activeSessionId) {
        setAttachments((items) => [...items, attachment]);
      }
    });
  };

  const clearDrafts = () => {
    if (!activeSessionId) return;
    const selected = attachments;
    setAttachments([]);
    void Promise.all(selected.map((attachment) => (
      removeAttachmentDraft(activeSessionId, attachment.draft_id)
    ))).catch((error) => toast.error(extractErr(error, '清空附件失败')));
  };

  const retryDraft = async (attachment: Attachment) => {
    if (!activeSessionId) return;
    const retrySessionId = activeSessionId;
    setRetryingDraftId(attachment.draft_id);
    try {
      const result = await retryAttachmentSource(retrySessionId, attachment.draft_id);
      if (!isMounted.current || activeSessionRef.current !== retrySessionId) return;
      setAttachments((items) => items.map((item) => (
        item.draft_id === attachment.draft_id
          ? {
              ...item,
              status: result.source.status,
              error: result.source.error_message ?? undefined,
            }
          : item
      )));
      if (result.source.status === 'processing') {
        const settled = await waitForAttachmentDraft(
          retrySessionId,
          attachment.draft_id,
          { signal: pollingRef.current?.signal },
        );
        if (!isMounted.current || activeSessionRef.current !== retrySessionId) return;
        setAttachments((items) => items.map((item) => (
          item.draft_id === attachment.draft_id
            ? {
                ...item,
                status: settled.status === 'ready' ? 'ready' : 'failed',
                error: settled.error_message ?? undefined,
              }
            : item
        )));
      }
    } catch (error) {
      if ((error as { name?: string })?.name !== 'AbortError') {
        toast.error(extractErr(error, `重试附件失败：${attachment.filename}`));
      }
    } finally {
      if (isMounted.current) setRetryingDraftId(null);
    }
  };

  const beginEdit = (submission: PendingSubmissionItem) => {
    setEditing({
      submissionId: submission.submission_id,
      message: submission.message,
      mode: submission.mode,
      executionMode: submission.execution_mode,
      questionIndexes: submission.question_indexes.join(', '),
    });
  };

  const parsedQuestionIndexes = (value: string): number[] => [...new Set(
    value.split(',')
      .map((item) => Number(item.trim()))
      .filter((item) => Number.isInteger(item) && item > 0),
  )];

  const runSubmissionAction = async (
    submission: PendingSubmissionItem,
    action: () => Promise<void>,
  ): Promise<boolean> => {
    setActingSubmissionId(submission.submission_id);
    try {
      await action();
      return true;
    } catch (error) {
      toast.error(extractErr(error, '排队消息操作失败，请刷新后重试'));
      return false;
    } finally {
      setActingSubmissionId(null);
    }
  };

  const saveEdit = async (submission: PendingSubmissionItem) => {
    if (!editing) return;
    const message = editing.message.trim();
    if (!message) {
      toast.error('排队消息不能为空');
      return;
    }
    const saved = await runSubmissionAction(submission, async () => {
      // Pending attachments are owned by the submission, not the live
      // Composer draft. Retain their exact server-projected draft ids.
      await onUpdatePendingSubmission(submission, {
        message,
        mode: editing.mode,
        execution_mode: editing.executionMode,
        question_indexes: parsedQuestionIndexes(editing.questionIndexes),
        attachments: submission.attachments,
        object_references: submission.object_references,
      });
    });
    if (saved) setEditing(null);
  };

  return (
    <div className="p-3 border-t border-stone-200">
      {pendingSubmissions.length > 0 && (
        <div
          className="mb-2 rounded-lg border border-warning-200 bg-warning-50 px-2.5 py-2"
          aria-label="待处理消息"
        >
          <div className="mb-1 text-[11px] font-medium text-warning-700">
            待处理 {pendingSubmissions.length} 条
          </div>
          <div className="max-h-56 space-y-1 overflow-y-auto">
            {pendingSubmissions.map((submission) => {
              const isEditing = editing?.submissionId === submission.submission_id;
              const acting = actingSubmissionId === submission.submission_id;
              return (
                <div
                  key={submission.submission_id}
                  className={[
                    'rounded border px-2 py-1.5 text-[11px]',
                    submission.status === 'failed'
                      ? 'border-danger-200 bg-danger-50 text-danger-800'
                      : 'border-warning-200 bg-white text-stone-600',
                  ].join(' ')}
                >
                  {isEditing && editing ? (
                    <div className="space-y-1.5">
                      <textarea
                        value={editing.message}
                        onChange={(event) => setEditing({ ...editing, message: event.target.value })}
                        rows={2}
                        aria-label="编辑排队消息"
                        className="w-full resize-none rounded border border-stone-200 bg-white px-1.5 py-1 text-[11px] outline-none focus:border-primary-300"
                      />
                      <div className="flex items-center gap-1.5">
                        <select
                          value={editing.mode}
                          onChange={(event) => setEditing({
                            ...editing,
                            mode: event.target.value as 'chat' | 'agent',
                          })}
                          aria-label="排队消息模式"
                          className="rounded border border-stone-200 bg-white px-1 py-0.5 text-[11px]"
                        >
                          <option value="chat">CHAT</option>
                          <option value="agent">AGENT</option>
                        </select>
                        <select
                          value={editing.executionMode}
                          onChange={(event) => setEditing({
                            ...editing,
                            executionMode: event.target.value as 'standard' | 'auto',
                          })}
                          aria-label="排队消息执行模式"
                          className="rounded border border-stone-200 bg-white px-1 py-0.5 text-[11px]"
                        >
                          <option value="standard">STANDARD</option>
                          <option value="auto">AUTO</option>
                        </select>
                        <input
                          value={editing.questionIndexes}
                          onChange={(event) => setEditing({ ...editing, questionIndexes: event.target.value })}
                          aria-label="引用题目序号"
                          placeholder="题目序号，如 1, 2"
                          className="min-w-0 flex-1 rounded border border-stone-200 bg-white px-1 py-0.5 text-[11px]"
                        />
                      </div>
                      {submission.attachments.length > 0 && (
                        <div className="text-stone-400">
                          保留 {submission.attachments.length} 个原附件
                        </div>
                      )}
                      {submission.object_references.length > 0 && (
                        <div className="text-stone-400">
                          保留 {submission.object_references.length} 个产品对象引用
                        </div>
                      )}
                      <div className="flex justify-end gap-1">
                        <button
                          type="button"
                          onClick={() => setEditing(null)}
                          disabled={acting}
                          className="rounded px-1.5 py-0.5 text-stone-500 hover:bg-stone-100 disabled:opacity-50"
                        >
                          取消
                        </button>
                        <button
                          type="button"
                          onClick={() => { void saveEdit(submission); }}
                          disabled={acting}
                          className="rounded bg-primary-500 px-1.5 py-0.5 text-white hover:bg-primary-600 disabled:opacity-50"
                        >
                          保存
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="flex min-w-0 items-start gap-1.5" title={submission.message}>
                        <span className={[
                          'shrink-0',
                          submission.status === 'failed' ? 'text-danger-700' : 'text-warning-700',
                        ].join(' ')}>
                          #{submission.queue_position}
                        </span>
                        <span className="min-w-0 flex-1 break-words">{submission.message}</span>
                        <span className="shrink-0 text-stone-400">{submission.mode.toUpperCase()}</span>
                        <span className="shrink-0 text-stone-400">{submission.execution_mode.toUpperCase()}</span>
                      </div>
                      {submission.attachments.length > 0 && (
                        <div className="mt-0.5 text-stone-400">{submission.attachments.length} 个附件</div>
                      )}
                      {submission.object_references.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1 text-stone-500">
                          {submission.object_references.map((reference) => (
                            <span
                              key={`${reference.kind}:${reference.object_id}`}
                              className="inline-flex max-w-[260px] items-center gap-1 rounded bg-stone-100 px-1.5 py-0.5"
                              title={`${reference.kind} · ${reference.object_id}`}
                            >
                              <Link2 size={9} className="shrink-0" />
                              <span className="truncate">
                                {productObjectReferenceLabel(reference)}
                              </span>
                            </span>
                          ))}
                        </div>
                      )}
                      {submission.status === 'failed' && submission.error && (
                        <div role="alert" className="mt-1 text-danger-700">{submission.error}</div>
                      )}
                      <div className="mt-1 flex flex-wrap justify-end gap-1">
                        <button
                          type="button"
                          onClick={() => beginEdit(submission)}
                          disabled={acting}
                          aria-label={`编辑排队消息 ${submission.message}`}
                          className="inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-stone-500 hover:bg-stone-100 disabled:opacity-50"
                        >
                          <Pencil size={10} /> 编辑
                        </button>
                        <button
                          type="button"
                          onClick={() => { void runSubmissionAction(submission, () => onWithdrawPendingSubmission(submission)); }}
                          disabled={acting}
                          aria-label={`撤回排队消息 ${submission.message}`}
                          className="inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-danger-600 hover:bg-danger-100 disabled:opacity-50"
                        >
                          <Trash2 size={10} /> 撤回
                        </button>
                        {submission.status === 'failed' && (
                          <button
                            type="button"
                            onClick={() => { void runSubmissionAction(submission, () => onRetryPendingSubmission(submission)); }}
                            disabled={acting}
                            aria-label={`重试排队消息 ${submission.message}`}
                            className="inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-primary-700 hover:bg-primary-50 disabled:opacity-50"
                          >
                            <RotateCcw size={10} /> 重试
                          </button>
                        )}
                        {activeTurnId && (
                          <button
                            type="button"
                            onClick={() => { void runSubmissionAction(submission, () => onInterruptForSubmission(submission)); }}
                            disabled={acting}
                            aria-label={`停止当前并发送此条 ${submission.message}`}
                            className="inline-flex items-center gap-0.5 rounded bg-warning-100 px-1 py-0.5 text-warning-800 hover:bg-warning-200 disabled:opacity-50"
                          >
                            <Zap size={10} /> 停止当前并发送此条
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
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
      {productObjectReferences.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-1.5" aria-label="本轮产品对象引用">
          <span className="text-[11px] text-stone-400">本轮引用</span>
          {productObjectReferences.map((reference) => (
            <button
              key={`${reference.kind}:${reference.object_id}`}
              type="button"
              onClick={() => onRemoveProductObjectReference(reference)}
              title="移除产品对象引用"
              className="inline-flex max-w-full items-center gap-1 rounded-full bg-accent-50 px-2 py-1 text-[11px] text-accent-700 hover:bg-accent-100"
            >
              <Link2 size={11} className="shrink-0" />
              <span className="max-w-[260px] truncate">
                {productObjectReferenceLabel(reference)}
              </span>
              <X size={11} />
            </button>
          ))}
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
        <button
          type="button"
          onClick={() => { void setExecutionMode(executionMode === 'auto' ? 'standard' : 'auto'); }}
          disabled={executionModePending}
          aria-label="切换 Standard Auto 执行模式"
          title={executionMode === 'auto'
            ? 'Auto：仅在当前任务明确范围内减少普通审批；风险与歧义仍会询问'
            : 'Standard：外部副作用默认逐调用确认'}
          className={[
            'inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium disabled:cursor-wait disabled:opacity-60',
            executionMode === 'auto'
              ? 'border-warning-300 bg-warning-50 text-warning-800'
              : 'border-stone-200 bg-white text-stone-600',
          ].join(' ')}
        >
          {executionMode === 'auto' ? 'AUTO' : 'STANDARD'}
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
              key={attachment.draft_id}
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
              {attachment.status === 'failed' && (
                <button
                  type="button"
                  disabled={retryingDraftId === attachment.draft_id}
                  onClick={() => { void retryDraft(attachment); }}
                  aria-label={`重试附件 ${attachment.filename}`}
                  className="text-primary-700 hover:text-primary-800 disabled:opacity-50"
                >
                  {retryingDraftId === attachment.draft_id
                    ? <Spinner size={9} />
                    : <RotateCcw size={10} />}
                </button>
              )}
              <button
                type="button"
                onClick={() => removeDraft(attachment)}
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
            onClick={clearDrafts}
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
