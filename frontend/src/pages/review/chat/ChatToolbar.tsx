import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Send, Plus, Bot, MessageSquare, Square, X, FileText, AlertCircle,
  Pencil, RotateCcw, Trash2, Zap, ShieldCheck, ChevronDown, Check, Sparkles,
  Link2,
} from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import { uploadFileAsset } from '@/api/fileAssets';
import {
  createAttachmentDraft,
  removeAttachmentDraft,
  retryAttachmentSource,
  waitForAttachmentDraft,
} from '@/api/chat';
import { useIsMounted } from '@/hooks/useIsMounted';
import type { ModelProfile, PendingSubmissionItem, ProductObjectReference } from '@/types/api';
import { productObjectReferenceLabel } from '@/lib/copilotObjectReference';
import type { Attachment, Mode } from './types';
import {
  CONVERSATION_ATTACHMENT_ACCEPT,
  conversationAttachmentPurpose,
} from './attachmentUpload';

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
  modelProfiles,
  activeModelProfileId,
  activeModelName,
  pickModel,
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
  modelProfiles: ModelProfile[];
  activeModelProfileId: string;
  activeModelName: string;
  pickModel: (profile: ModelProfile) => Promise<boolean>;
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
  const approvalMenuRef = useRef<HTMLDivElement | null>(null);
  const modelMenuRef = useRef<HTMLDivElement | null>(null);
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
  const [approvalMenuOpen, setApprovalMenuOpen] = useState(false);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const uploading = uploadState.sessionId === activeSessionId && uploadState.active;
  const isMounted = useIsMounted();

  useEffect(() => {
    activeSessionRef.current = activeSessionId;
    pollingRef.current?.abort();
    pollingRef.current = new AbortController();
    return () => pollingRef.current?.abort();
  }, [activeSessionId]);

  useEffect(() => {
    const onDocumentPointerDown = (event: MouseEvent) => {
      if (!approvalMenuRef.current?.contains(event.target as Node)) {
        setApprovalMenuOpen(false);
      }
      if (!modelMenuRef.current?.contains(event.target as Node)) {
        setModelMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocumentPointerDown);
    return () => document.removeEventListener('mousedown', onDocumentPointerDown);
  }, []);

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
        const fileAssetId = await uploadFileAsset(
          file,
          conversationAttachmentPurpose(file),
        );
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
  const callableModels = modelProfiles.filter((profile) => (
    profile.ready && (mode !== 'AGENT' || profile.supports_function_calling)
  ));

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
      <div className="overflow-visible rounded-[22px] border border-stone-200 bg-white shadow-sm transition focus-within:border-primary-300 focus-within:ring-2 focus-within:ring-primary-100">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          disabled={!activeSessionId || streaming || uploading}
          placeholder={
            activeSessionId
              ? '随心输入 · Shift+Enter 换行'
              : (externalMode ? '先在左侧选择' : '点右上 + 新建一段会话')
          }
          rows={3}
          aria-label="消息输入"
          className="min-h-[84px] w-full resize-none bg-transparent px-4 pb-2 pt-3 text-[14px] leading-6 text-stone-800 outline-none placeholder:text-stone-400 disabled:opacity-50"
        />
        {attachments.length > 0 && (
          <div className="flex items-center gap-1.5 overflow-x-auto px-3 pb-2" aria-label="待发送附件">
            {attachments.map((attachment) => (
              <span
                key={attachment.draft_id}
                title={attachment.error || attachment.filename}
                className={[
                  'inline-flex max-w-[170px] shrink-0 items-center gap-1 rounded-lg border px-2 py-1 text-[11px]',
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
            ))}
            <button
              type="button"
              onClick={clearDrafts}
              className="shrink-0 text-[11px] text-stone-400 hover:text-danger-500"
            >
              清空
            </button>
          </div>
        )}
        <div className="flex items-end justify-between gap-2 px-2.5 pb-2.5">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <input
              ref={fileRef}
              type="file"
              accept={CONVERSATION_ATTACHMENT_ACCEPT}
              multiple
              hidden
              onChange={(e) => {
                if (e.target.files && e.target.files.length > 0) onAttachFiles(e.target.files);
                e.target.value = '';
              }}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={!activeSessionId || uploading || attachments.length >= 10}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-stone-600 transition hover:bg-stone-100 disabled:opacity-40"
              title="添加附件"
              aria-label="添加附件"
            >
              {uploading ? <Spinner size={14} /> : <Plus size={18} />}
            </button>

            {allowModeSwitch ? (
              <button
                type="button"
                onClick={() => setMode((current) => (current === 'AGENT' ? 'CHAT' : 'AGENT'))}
                aria-label="切换 Chat Agent 模式"
                className={[
                  'inline-flex h-8 items-center gap-1 rounded-full px-2.5 text-[11px] font-medium tracking-wide transition',
                  mode === 'AGENT'
                    ? 'bg-primary-50 text-primary-700 hover:bg-primary-100'
                    : 'text-stone-600 hover:bg-stone-100',
                ].join(' ')}
              >
                {mode === 'AGENT' ? <Bot size={13} /> : <MessageSquare size={13} />}
                {mode === 'AGENT' ? 'Agent' : 'Chat'}
              </button>
            ) : (
              <span className="inline-flex h-8 items-center gap-1 rounded-full bg-primary-50 px-2.5 text-[11px] font-medium text-primary-700">
                <Bot size={13} /> 求职 Agent
              </span>
            )}

            <div ref={approvalMenuRef} className="relative">
              <button
                type="button"
                onClick={() => setApprovalMenuOpen((open) => !open)}
                disabled={executionModePending || !activeSessionId}
                aria-label="选择审批模式"
                aria-expanded={approvalMenuOpen}
                className={[
                  'inline-flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[11px] font-medium transition disabled:cursor-wait disabled:opacity-50',
                  executionMode === 'auto'
                    ? 'bg-warning-50 text-warning-800 hover:bg-warning-100'
                    : 'text-stone-600 hover:bg-stone-100',
                ].join(' ')}
              >
                <ShieldCheck size={14} />
                {executionMode === 'auto' ? '自动审批' : '每次确认'}
                <ChevronDown size={12} />
              </button>
              {approvalMenuOpen && (
                <div className="absolute bottom-full left-0 z-40 mb-2 w-[310px] overflow-hidden rounded-xl border border-stone-200 bg-white p-1.5 shadow-xl">
                  <div className="px-2.5 pb-1.5 pt-1 text-[11px] text-stone-400">工具操作如何获得批准？</div>
                  <ApprovalModeOption
                    title="每次确认"
                    description="外部副作用默认逐次询问，适合希望逐步确认的任务。"
                    selected={executionMode === 'standard'}
                    onClick={() => {
                      void setExecutionMode('standard').then(() => setApprovalMenuOpen(false));
                    }}
                  />
                  <ApprovalModeOption
                    title="自动审批"
                    description="仅在当前任务明确范围内减少普通审批；风险、越界与歧义仍会询问。"
                    selected={executionMode === 'auto'}
                    onClick={() => {
                      void setExecutionMode('auto').then(() => setApprovalMenuOpen(false));
                    }}
                  />
                </div>
              )}
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            <div ref={modelMenuRef} className="relative">
              <button
                type="button"
                onClick={() => setModelMenuOpen((open) => !open)}
                aria-label="选择回答模型"
                aria-expanded={modelMenuOpen}
                className="inline-flex h-8 max-w-[170px] items-center gap-1 rounded-full px-2.5 text-xs font-medium text-stone-700 transition hover:bg-stone-100"
              >
                <Sparkles size={13} className="shrink-0 text-accent-700" />
                <span className="truncate">{activeModelName}</span>
                <ChevronDown size={12} className="shrink-0 text-stone-400" />
              </button>
              {modelMenuOpen && (
                <div className="absolute bottom-full right-0 z-40 mb-2 w-[300px] overflow-hidden rounded-xl border border-stone-200 bg-white shadow-xl">
                  <div className="border-b border-stone-100 px-3 py-2.5">
                    <div className="text-xs font-medium text-stone-700">选择回答模型</div>
                    <div className="mt-0.5 text-[11px] text-stone-400">
                      只显示已配置密钥且当前可调用的模型
                      {mode === 'AGENT' ? '，并要求支持工具调用' : ''}
                    </div>
                  </div>
                  <div className="max-h-[260px] overflow-y-auto p-1.5">
                    {callableModels.length === 0 ? (
                      <div className="px-2 py-3 text-xs text-stone-500">还没有符合当前模式的可用模型。</div>
                    ) : callableModels.map((profile) => {
                      const selected = profile.id === activeModelProfileId;
                      return (
                        <button
                          key={profile.id}
                          type="button"
                          onClick={() => {
                            void pickModel(profile).then((ok) => {
                              if (ok) setModelMenuOpen(false);
                            });
                          }}
                          className={[
                            'flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition',
                            selected ? 'bg-primary-50 text-primary-800' : 'text-stone-700 hover:bg-stone-50',
                          ].join(' ')}
                        >
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[13px] font-medium">{profile.display_name}</span>
                            <span className="block truncate font-mono text-[10px] text-stone-400">{profile.provider} · {profile.model}</span>
                          </span>
                          {selected && <Check size={15} className="shrink-0 text-primary-600" />}
                        </button>
                      );
                    })}
                  </div>
                  <div className="border-t border-stone-100 bg-stone-50 px-3 py-2 text-[11px] text-stone-500">
                    需要更多模型？{' '}
                    <Link to="/models" onClick={() => setModelMenuOpen(false)} className="font-medium text-primary-700 hover:text-primary-900">
                      前往回答模型配置
                    </Link>
                  </div>
                </div>
              )}
            </div>

            {streaming ? (
              <button
                type="button"
                onClick={onCancel}
                title="停止任务"
                aria-label="停止任务"
                className="flex h-9 w-9 items-center justify-center rounded-full bg-danger-500 text-white transition hover:bg-danger-700"
              >
                <Square size={12} fill="currentColor" />
              </button>
            ) : (
              <button
                type="button"
                onClick={onSend}
                disabled={!activeSessionId || !input.trim() || uploading || !attachmentsReady}
                title="发送"
                aria-label="发送消息"
                className="flex h-9 w-9 items-center justify-center rounded-full bg-stone-900 text-white transition hover:bg-stone-700 disabled:cursor-not-allowed disabled:bg-stone-200 disabled:text-stone-400"
              >
                <Send size={15} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ApprovalModeOption({
  title,
  description,
  selected,
  onClick,
}: {
  title: string;
  description: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition',
        selected ? 'bg-stone-100 text-stone-900' : 'text-stone-700 hover:bg-stone-50',
      ].join(' ')}
    >
      <ShieldCheck size={15} className="mt-0.5 shrink-0" />
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-medium">{title}</span>
        <span className="mt-0.5 block text-[11px] leading-4 text-stone-500">{description}</span>
      </span>
      {selected && <Check size={15} className="mt-0.5 shrink-0 text-primary-600" />}
    </button>
  );
}
