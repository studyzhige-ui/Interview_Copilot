import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  FolderInput,
  Loader2,
  RotateCcw,
  Save,
  Trash2,
  X,
} from 'lucide-react';
import {
  listAttachmentSources,
  listDebriefSources,
  promoteAttachmentToDebrief,
  promoteAttachmentToArtifact,
  removeDebriefSource,
  removeConversationAttachmentFromScope,
  retryAttachmentSource,
} from '@/api/chat';
import {
  getFileAssetDeletionImpact,
  permanentlyDeleteFileAsset,
} from '@/api/fileAssets';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/store/uiStore';
import type {
  AttachmentSource,
  FileAssetDeletionImpact,
  PendingSubmissionItem,
} from '@/types/api';

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
  const [permanentDelete, setPermanentDelete] = useState<{
    source: AttachmentSource;
    impact: FileAssetDeletionImpact | null;
    error: string | null;
  } | null>(null);
  const [filenameConfirmation, setFilenameConfirmation] = useState('');
  const [artifactPromotion, setArtifactPromotion] = useState<{
    source: AttachmentSource;
    kind: string;
    title: string;
  } | null>(null);
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

  const preparePermanentDelete = (source: AttachmentSource) => {
    if (!source.file_asset_id) return;
    setFilenameConfirmation('');
    setPermanentDelete({ source, impact: null, error: null });
    void getFileAssetDeletionImpact(source.file_asset_id).then(
      (impact) => setPermanentDelete((current) => (
        current?.source.source_id === source.source_id
          ? { ...current, impact, error: null }
          : current
      )),
      (deleteError) => setPermanentDelete((current) => (
        current?.source.source_id === source.source_id
          ? { ...current, error: extractErr(deleteError, '永久删除影响暂时无法读取') }
          : current
      )),
    );
  };

  const promotedKeys = new Set(
    debriefSources.map((source) => `${source.file_asset_id}:${source.file_asset_version}`),
  );
  const hasVisibleContent = allSources.length > 0 || error !== null;
  if (!hasVisibleContent) return null;

  return (
    <>
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
              onRemove={() => run(source.source_id, async () => {
                const result = await removeConversationAttachmentFromScope(sessionId, source.source_id);
                setResumeNotice({
                  sessionId,
                  message: result.resumed_turn
                    ? '附件已从本对话移除，服务端已恢复当前 Turn。'
                    : '附件已从本对话移除；历史来源卡保留为不可访问 tombstone。',
                });
              })}
              removeActionLabel={source.status === 'failed' ? '移除失败项并继续' : '从本对话移除'}
              onPermanentDelete={source.file_asset_id ? () => preparePermanentDelete(source) : undefined}
              onSaveArtifact={source.file_asset_id && source.file_asset_version ? () => {
                setArtifactPromotion({
                  source,
                  kind: /(?:简历|resume|cv)/i.test(source.title) ? 'resume' : 'interview_notes',
                  title: source.title,
                });
              } : undefined}
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
            onPermanentDelete={source.file_asset_id ? () => preparePermanentDelete(source) : undefined}
          />
        ))}
      </div>
    </section>
    <Modal
      open={Boolean(permanentDelete)}
      onClose={() => { if (!actingSourceId) setPermanentDelete(null); }}
      title="永久删除原始文件"
      width={560}
      footer={<>
        <Btn kind="ghost" disabled={Boolean(actingSourceId)} onClick={() => setPermanentDelete(null)}>取消</Btn>
        <Btn
          kind="danger"
          loading={Boolean(actingSourceId)}
          disabled={!permanentDelete?.impact
            || filenameConfirmation !== permanentDelete.impact.filename
            || Boolean(permanentDelete.error)}
          onClick={() => {
            if (!permanentDelete?.impact) return;
            const sourceId = permanentDelete.source.source_id;
            void run(sourceId, async () => {
              await permanentlyDeleteFileAsset(permanentDelete.impact!, filenameConfirmation);
              setPermanentDelete(null);
              setFilenameConfirmation('');
              toast.success('原始文件与 Copilot 可控解析投影已进入永久删除流程');
            });
          }}
        >永久删除</Btn>
      </>}
    >
      {permanentDelete?.error ? (
        <div role="alert" className="text-sm text-danger-700">{permanentDelete.error}</div>
      ) : permanentDelete?.impact ? (
        <div className="space-y-3 text-sm text-stone-600">
          <div className="rounded-md border border-danger-200 bg-danger-50 p-3 text-danger-800">
            {permanentDelete.impact.disclosures.map((item) => <p key={item}>• {item}</p>)}
          </div>
          {permanentDelete.impact.reference_impacts.length > 0 && (
            <div className="space-y-1 text-xs">
              {permanentDelete.impact.reference_impacts.map((item) => (
                <div key={item.reference_type}>
                  {item.reference_type}：有效 {item.active_count}，tombstone {item.tombstone_count}。{item.effect}
                </div>
              ))}
            </div>
          )}
          <div className="rounded-md border border-warning-200 bg-warning-50 p-2 text-xs text-warning-800">
            已识别与此文件精确关联的已完成外传：
            {permanentDelete.impact.known_external_transmission_count} 次。
            永久删除不会撤回这些外部动作或 Provider 已接收的副本。
          </div>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-stone-700">
              输入完整文件名“{permanentDelete.impact.filename}”确认
            </span>
            <input
              value={filenameConfirmation}
              onChange={(event) => setFilenameConfirmation(event.target.value)}
              className="w-full rounded-md border border-stone-300 px-3 py-2 outline-none focus:border-danger-400"
            />
          </label>
        </div>
      ) : <div className="text-sm text-stone-500">正在核对引用、scope 和已知外传影响……</div>}
    </Modal>
    <Modal
      open={Boolean(artifactPromotion)}
      onClose={() => { if (!actingSourceId) setArtifactPromotion(null); }}
      title="保存为正式材料"
      width={520}
      footer={<>
        <Btn kind="ghost" disabled={Boolean(actingSourceId)} onClick={() => setArtifactPromotion(null)}>取消</Btn>
        <Btn
          loading={Boolean(actingSourceId)}
          disabled={!artifactPromotion?.title.trim()}
          onClick={() => {
            if (!artifactPromotion) return;
            const pending = artifactPromotion;
            void run(pending.source.source_id, async () => {
              const result = await promoteAttachmentToArtifact(
                sessionId,
                pending.source.source_id,
                {
                  operationKey: crypto.randomUUID(),
                  artifactKind: pending.kind,
                  title: pending.title.trim(),
                },
              );
              setArtifactPromotion(null);
              setResumeNotice({
                sessionId,
                message: result.artifact.kind === 'resume'
                  ? '已保存为简历；系统将解析原始文件并生成待你确认的求职档案候选，不会自动改写个人详情。'
                  : '已保存为正式材料；本对话附件仍保留在原 scope。',
              });
              toast.success('正式材料已保存');
            });
          }}
        >确认保存</Btn>
      </>}
    >
      {artifactPromotion && (
        <div className="space-y-3 text-sm text-stone-600">
          <div className="rounded-md border border-primary-200 bg-primary-50 p-3 text-primary-900">
            此操作会为同一份原始文件新增正式 Artifact scope，并冻结当前文件版本；不会复制解析正文，也不会移除本对话附件。
          </div>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-stone-700">材料类型</span>
            <select
              aria-label="材料类型"
              value={artifactPromotion.kind}
              onChange={(event) => setArtifactPromotion((current) => (
                current ? { ...current, kind: event.target.value } : current
              ))}
              className="w-full rounded-md border border-stone-300 px-3 py-2 outline-none focus:border-primary-400"
            >
              <option value="resume">简历</option>
              <option value="cover_letter">求职信</option>
              <option value="portfolio">作品集说明</option>
              <option value="interview_notes">面试材料</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-stone-700">材料标题</span>
            <input
              aria-label="材料标题"
              value={artifactPromotion.title}
              onChange={(event) => setArtifactPromotion((current) => (
                current ? { ...current, title: event.target.value } : current
              ))}
              className="w-full rounded-md border border-stone-300 px-3 py-2 outline-none focus:border-primary-400"
            />
          </label>
          {artifactPromotion.kind === 'resume' && (
            <p className="rounded-md border border-warning-200 bg-warning-50 p-2 text-xs text-warning-800">
              保存后会触发简历解析和候选提取。候选必须由你确认后才会进入个人详情/求职档案。
            </p>
          )}
        </div>
      )}
    </Modal>
    </>
  );
}

function SourceRow({
  source,
  scopeLabel,
  acting,
  onRetry,
  onRemove,
  onPromote,
  onSaveArtifact,
  onPermanentDelete,
  removeActionLabel,
  promoted = false,
}: {
  source: AttachmentSource;
  scopeLabel: string;
  acting: boolean;
  onRetry?: () => void;
  onRemove?: () => void;
  onPromote?: () => void;
  onSaveArtifact?: () => void;
  onPermanentDelete?: () => void;
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
        {onSaveArtifact && (
          <button
            type="button"
            disabled={acting}
            onClick={onSaveArtifact}
            aria-label={`保存为正式材料 ${source.title}`}
            className="inline-flex shrink-0 items-center gap-0.5 text-primary-700 hover:underline disabled:opacity-50"
          >
            <Save size={10} /> 保存为材料
          </button>
        )}
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
        {onPermanentDelete && (
          <button
            type="button"
            disabled={acting}
            onClick={onPermanentDelete}
            aria-label={`永久删除原始文件 ${source.title}`}
            className="shrink-0 text-danger-700 underline disabled:opacity-50"
          >永久删除文件</button>
        )}
      </div>
      {source.error_message && (
        <div role="alert" className="mt-1 pl-7 text-danger-700">{source.error_message}</div>
      )}
      {source.parse_quality.warnings.length > 0 && (
        <div role="status" className="mt-1 pl-7 text-warning-700">
          解析提示：{source.parse_quality.warnings.join('、')}
        </div>
      )}
      {source.status === 'ready' && (
        <div className="mt-1 pl-7 text-stone-500">
          文本覆盖：{source.coverage.parsed_char_count} 字符 / {source.coverage.chunk_count} 段
          {source.coverage.page_count != null ? ` / ${source.coverage.page_count} 页` : ''}
          {source.parse_quality.ocr_used ? ' · 使用 OCR' : ''}
          {!source.coverage.visual_layout_reviewed ? ' · 未证明已检查视觉版式' : ''}
        </div>
      )}
    </div>
  );
}
