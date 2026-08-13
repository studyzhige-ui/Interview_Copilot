import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  FolderInput,
  Loader2,
  RotateCcw,
  Trash2,
  X,
} from 'lucide-react';
import {
  listAttachmentSources,
  listDebriefSources,
  promoteAttachmentToDebrief,
  removeDebriefSource,
  removeFailedConversationAttachment,
  retryAttachmentSource,
} from '@/api/chat';
import { extractErr } from '@/api/client';
import { toast } from '@/store/uiStore';
import type { AttachmentSource, PendingSubmissionItem } from '@/types/api';

interface Props {
  sessionId: string;
  interviewId?: string | null;
  pendingSubmissions: PendingSubmissionItem[];
  refreshKey: string;
  onRemovePendingSource: (
    submission: PendingSubmissionItem,
    sourceId: string,
  ) => Promise<void>;
}

/**
 * One read projection over the real AttachmentRef / pending draft /
 * InterviewSourceRef owners. This component never promotes a file implicitly
 * and never invents a client-only processing result.
 */
export function AttachmentSources({
  sessionId,
  interviewId,
  pendingSubmissions,
  refreshKey,
  onRemovePendingSource,
}: Props) {
  const [conversationSources, setConversationSources] = useState<AttachmentSource[]>([]);
  const [debriefSources, setDebriefSources] = useState<AttachmentSource[]>([]);
  const [pendingSources, setPendingSources] = useState<Record<string, AttachmentSource[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [actingSourceId, setActingSourceId] = useState<string | null>(null);
  const [resumeNotice, setResumeNotice] = useState<{
    sessionId: string;
    message: string;
  } | null>(null);
  const visibleResumeNotice = resumeNotice?.sessionId === sessionId
    ? resumeNotice.message
    : null;

  const pendingSignature = pendingSubmissions
    .map((item) => `${item.submission_id}:${item.version}`)
    .join('|');

  const load = useCallback(async (signal?: AbortSignal) => {
    const pendingRequests = pendingSubmissions.map(async (submission) => {
      const sources = await listAttachmentSources(sessionId, {
        submissionId: submission.submission_id,
        signal,
      });
      return [submission.submission_id, sources] as const;
    });
    try {
      const [conversation, debrief, pending] = await Promise.all([
        listAttachmentSources(sessionId, { signal }),
        interviewId ? listDebriefSources(interviewId, { signal }) : Promise.resolve([]),
        Promise.all(pendingRequests),
      ]);
      setConversationSources(conversation);
      setDebriefSources(debrief);
      setPendingSources(Object.fromEntries(pending));
      setError(null);
    } catch (loadError) {
      if ((loadError as { name?: string })?.name === 'CanceledError') return;
      setError(extractErr(loadError, '附件来源状态暂时无法读取'));
    }
  }, [interviewId, pendingSignature, sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => { void load(controller.signal); }, 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [load, refreshKey]);

  const allSources = useMemo(
    () => [
      ...conversationSources,
      ...debriefSources,
      ...Object.values(pendingSources).flat(),
    ],
    [conversationSources, debriefSources, pendingSources],
  );
  const processing = allSources.some((source) => source.status === 'processing');

  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(() => { void load(); }, 2_000);
    return () => window.clearInterval(timer);
  }, [load, processing]);

  const run = async (sourceId: string, action: () => Promise<void>) => {
    setActingSourceId(sourceId);
    try {
      await action();
      await load();
    } catch (actionError) {
      toast.error(extractErr(actionError, '附件来源操作失败'));
    } finally {
      setActingSourceId(null);
    }
  };

  const promotedKeys = new Set(
    debriefSources.map((source) => `${source.file_asset_id}:${source.file_asset_version}`),
  );
  const hasVisibleContent = allSources.length > 0 || error !== null;
  if (!hasVisibleContent) return null;

  return (
    <section
      aria-label="附件来源"
      className="border-t border-stone-100 bg-stone-50/70 px-3 py-2"
    >
      <div className="mb-1.5 flex items-center justify-between text-[11px] text-stone-500">
        <span className="font-medium text-stone-600">附件来源</span>
        <span>
          本对话 {conversationSources.length}
          {interviewId ? ` · 本次复盘 ${debriefSources.length}` : ''}
        </span>
      </div>
      {error && (
        <div role="alert" className="mb-1.5 flex items-center gap-1 text-[11px] text-danger-700">
          <AlertCircle size={11} /> {error}
          <button type="button" onClick={() => { void load(); }} className="underline">
            重试读取
          </button>
        </div>
      )}
      {visibleResumeNotice && (
        <div role="status" className="mb-1.5 rounded-md border border-success-200 bg-success-50 px-2 py-1.5 text-[11px] text-success-800">
          {visibleResumeNotice}
        </div>
      )}
      <div className="max-h-36 space-y-1 overflow-y-auto">
        {pendingSubmissions.flatMap((submission) => (
          (pendingSources[submission.submission_id] ?? []).map((source) => (
            <SourceRow
              key={`pending:${submission.submission_id}:${source.source_id}`}
              source={source}
              scopeLabel={`待发送 #${submission.queue_position}`}
              acting={actingSourceId === source.source_id}
              onRetry={source.can_retry ? () => run(source.source_id, async () => {
                await retryAttachmentSource(sessionId, source.source_id);
              }) : undefined}
              onRemove={() => run(source.source_id, () => (
                onRemovePendingSource(submission, source.source_id)
              ))}
            />
          ))
        ))}
        {conversationSources.map((source) => {
          const promoted = promotedKeys.has(`${source.file_asset_id}:${source.file_asset_version}`);
          return (
            <SourceRow
              key={`conversation:${source.source_id}`}
              source={source}
              scopeLabel="本对话"
              acting={actingSourceId === source.source_id}
              onRetry={source.can_retry ? () => run(source.source_id, async () => {
                await retryAttachmentSource(sessionId, source.source_id);
              }) : undefined}
              onRemove={source.status === 'failed' ? () => run(source.source_id, async () => {
                const result = await removeFailedConversationAttachment(sessionId, source.source_id);
                setResumeNotice({
                  sessionId,
                  message: result.resumed_turn
                    ? '失败附件已移除，服务端已恢复当前 Turn。'
                    : '失败附件已移除，服务端确认当前 Turn 无需恢复。',
                });
              }) : undefined}
              removeActionLabel={source.status === 'failed' ? '移除失败项并继续' : undefined}
              onPromote={interviewId && !promoted ? () => run(source.source_id, async () => {
                await promoteAttachmentToDebrief(sessionId, source.source_id);
                toast.success('已添加到本次复盘资料');
              }) : undefined}
              promoted={promoted}
            />
          );
        })}
        {debriefSources.map((source) => (
          <SourceRow
            key={`debrief:${source.source_id}`}
            source={source}
            scopeLabel="本次复盘"
            acting={actingSourceId === source.source_id}
            onRetry={source.can_retry ? () => run(source.source_id, async () => {
              await retryAttachmentSource(sessionId, source.source_id);
            }) : undefined}
            onRemove={interviewId ? () => run(source.source_id, async () => {
              await removeDebriefSource(interviewId, source.source_id);
              toast.success('已从本次复盘资料移除');
            }) : undefined}
          />
        ))}
      </div>
    </section>
  );
}

function SourceRow({
  source,
  scopeLabel,
  acting,
  onRetry,
  onRemove,
  onPromote,
  removeActionLabel,
  promoted = false,
}: {
  source: AttachmentSource;
  scopeLabel: string;
  acting: boolean;
  onRetry?: () => void;
  onRemove?: () => void;
  onPromote?: () => void;
  removeActionLabel?: string;
  promoted?: boolean;
}) {
  const statusLabel = source.status === 'processing'
    ? '处理中'
    : source.status === 'ready' ? '已就绪' : '失败';
  return (
    <div className="rounded-md border border-stone-200 bg-white px-2 py-1.5 text-[11px]">
      <div className="flex min-w-0 items-center gap-1.5">
        {acting ? <Loader2 size={11} className="shrink-0 animate-spin text-primary-600" />
          : source.status === 'processing' ? <Loader2 size={11} className="shrink-0 animate-spin text-warning-700" />
            : source.status === 'failed' ? <AlertCircle size={11} className="shrink-0 text-danger-700" />
              : <CheckCircle2 size={11} className="shrink-0 text-success-700" />}
        <FileText size={11} className="shrink-0 text-stone-400" />
        <span className="min-w-0 flex-1 truncate text-stone-700" title={source.title}>
          {source.title}
        </span>
        <span className="shrink-0 text-stone-400">{scopeLabel} · {statusLabel}</span>
        {onRetry && (
          <button
            type="button"
            disabled={acting}
            onClick={onRetry}
            aria-label={`重试附件 ${source.title}`}
            className="inline-flex shrink-0 items-center gap-0.5 text-primary-700 hover:underline disabled:opacity-50"
          >
            <RotateCcw size={10} /> 重试
          </button>
        )}
        {onPromote && (
          <button
            type="button"
            disabled={acting}
            onClick={onPromote}
            aria-label={`添加到本次复盘资料 ${source.title}`}
            className="inline-flex shrink-0 items-center gap-0.5 text-primary-700 hover:underline disabled:opacity-50"
          >
            <FolderInput size={10} /> 添加到复盘
          </button>
        )}
        {promoted && <span className="shrink-0 text-success-700">已加入复盘</span>}
        {onRemove && (
          <button
            type="button"
            disabled={acting}
            onClick={onRemove}
            aria-label={`${removeActionLabel ?? '移除附件来源'} ${source.title}`}
            className="inline-flex shrink-0 items-center gap-0.5 text-danger-600 hover:text-danger-700 disabled:opacity-50"
          >
            {source.scope_kind === 'pending_submission' ? <X size={11} /> : <Trash2 size={11} />}
            {removeActionLabel && <span>{removeActionLabel}</span>}
          </button>
        )}
      </div>
      {source.error_message && (
        <div role="alert" className="mt-1 pl-7 text-danger-700">{source.error_message}</div>
      )}
    </div>
  );
}
