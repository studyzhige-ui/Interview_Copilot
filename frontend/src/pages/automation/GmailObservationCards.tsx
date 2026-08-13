import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Inbox, RefreshCw, RotateCcw, SkipForward, X } from 'lucide-react';
import { listJobOpportunities } from '@/api/careerProcess';
import {
  listGmailObservations,
  listGmailReviewCards,
  rebaselineGmailObservations,
  resolveGmailReviewCard,
  retractGmailObservation,
  syncGmailObservations,
} from '@/api/gmailObservations';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { FormItem, SelectInput, TextArea, displayDate } from '@/pages/career/CareerFields';
import { toast } from '@/store/uiStore';
import type { ProcessEventKind } from '@/types/career';
import type { GmailObservation, GmailObservationReviewCard } from '@/types/gmailObservation';
import type { PersistentTask } from '@/types/persistentTask';

const EVENT_OPTIONS: Array<{ value: ProcessEventKind; label: string }> = [
  { value: 'application_submitted', label: '投递成功' },
  { value: 'application_acknowledged', label: '申请已收到' },
  { value: 'recruiter_contact', label: '招聘方联系' },
  { value: 'assessment_invited', label: '测评邀请' },
  { value: 'assessment_completed', label: '测评完成' },
  { value: 'hiring_step', label: '其他招聘步骤' },
  { value: 'interview_scheduled', label: '面试安排' },
  { value: 'interview_completed', label: '面试完成' },
  { value: 'background_check_started', label: '背调开始' },
  { value: 'offer_received', label: '收到 Offer' },
  { value: 'rejected', label: '招聘方拒绝' },
  { value: 'posting_closed', label: '岗位关闭' },
];

function operationId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `ui-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function errorDetail(error: unknown): string | undefined {
  return (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
}

export function GmailObservationCards({
  task,
  observationIds,
}: {
  task: PersistentTask;
  observationIds: string[];
}) {
  const queryClient = useQueryClient();
  const [syncing, setSyncing] = useState(false);
  const [cursorExpired, setCursorExpired] = useState(false);
  const [retractTarget, setRetractTarget] = useState<GmailObservation | null>(null);
  const cardsKey = ['persistent-task', task.id, 'gmail-review-cards'] as const;
  const observationsKey = ['gmail-observations'] as const;
  const cardsQuery = useQuery({
    queryKey: cardsKey,
    queryFn: () => listGmailReviewCards(task.id),
  });
  const observationsQuery = useQuery({
    queryKey: observationsKey,
    queryFn: listGmailObservations,
  });
  const jobsQuery = useQuery({
    queryKey: ['job-opportunities', 'gmail-review'],
    queryFn: () => listJobOpportunities(true),
  });
  const observationSet = new Set(observationIds);
  const reports = (observationsQuery.data ?? []).filter(
    (observation) => observationSet.has(observation.id)
      && ['applied', 'retracted'].includes(observation.status),
  );

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: cardsKey }),
      queryClient.invalidateQueries({ queryKey: observationsKey }),
      queryClient.invalidateQueries({ queryKey: ['persistent-task', task.id, 'triggers'] }),
      queryClient.invalidateQueries({ queryKey: ['job-opportunities'] }),
    ]);
  };

  const sync = async (rebaseline = false) => {
    setSyncing(true);
    try {
      const result = rebaseline
        ? await rebaselineGmailObservations(operationId())
        : await syncGmailObservations();
      setCursorExpired(false);
      await refresh();
      toast.success(result.initialized_cursor
        ? 'Gmail 增量游标已从当前时点建立'
        : `同步完成：新增 ${result.observations_created} 条 Observation`);
    } catch (error) {
      const detail = errorDetail(error);
      if (detail === 'history_cursor_expired') setCursorExpired(true);
      toast.error(detail === 'history_cursor_expired'
        ? 'Gmail 增量游标已过期；请确认从当前时点重新建立。'
        : extractErr(error));
    } finally {
      setSyncing(false);
    }
  };

  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 shadow-xs">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Inbox size={17} className="mt-0.5 shrink-0 text-primary-600" />
          <div>
            <h3 className="text-sm font-medium text-stone-800">Gmail Observation 待处理合集</h3>
            <p className="mt-0.5 text-xs text-stone-500">模糊匹配只停留在本任务；批准后才进入岗位事实时间线。高置信自动记录可在下方撤销。</p>
          </div>
        </div>
        <div className="flex gap-2">
          {cursorExpired && (
            <Btn kind="outline" size="sm" onClick={() => { void sync(true); }}>从当前时点重建游标</Btn>
          )}
          <Btn size="sm" icon={<RefreshCw size={14} />} loading={syncing} onClick={() => { void sync(); }}>立即增量同步</Btn>
        </div>
      </div>

      {cardsQuery.isLoading || jobsQuery.isLoading ? (
        <div className="mt-4 flex items-center gap-2 text-xs text-stone-500"><Spinner size={13} />正在读取待确认内容…</div>
      ) : cardsQuery.isError ? (
        <div role="alert" className="mt-4 rounded-lg border border-danger-200 bg-danger-50 px-3 py-2 text-xs text-danger-700">{extractErr(cardsQuery.error)}</div>
      ) : (cardsQuery.data ?? []).length === 0 ? (
        <div className="mt-4 rounded-lg bg-stone-50 px-3 py-4 text-center text-xs text-stone-500">当前没有待确认 Observation</div>
      ) : (
        <div className="mt-4 space-y-3">
          {(cardsQuery.data ?? []).map((card) => (
            <ReviewCardItem
              key={card.id}
              task={task}
              card={card}
              jobs={jobsQuery.data ?? []}
              onResolved={refresh}
            />
          ))}
        </div>
      )}

      {reports.length > 0 && (
        <div className="mt-5 border-t border-stone-100 pt-4">
          <h4 className="text-xs font-medium text-stone-600">已汇报的自动应用</h4>
          <div className="mt-2 space-y-2">
            {reports.map((observation) => (
              <div key={observation.id} className="rounded-lg border border-stone-200 px-3 py-2.5">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm text-stone-700">{observation.latest_snapshot.subject || '无主题邮件'}</div>
                    <div className="mt-1 text-xs text-stone-500">{observation.notification_summary}</div>
                  </div>
                  {observation.status === 'applied' ? (
                    <Btn kind="ghost" size="sm" icon={<RotateCcw size={13} />} onClick={() => setRetractTarget(observation)}>撤销记录</Btn>
                  ) : <Pill>已撤销</Pill>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(retractTarget)}
        title="撤销这条自动记录？"
        description="系统会追加一条撤销事件并重建岗位投影；原始 Gmail Observation 与历史 ProcessEvent 仍保留用于审计。"
        confirmText="追加撤销事件"
        danger
        onCancel={() => setRetractTarget(null)}
        onConfirm={() => {
          if (!retractTarget) return;
          void (async () => {
            try {
              await retractGmailObservation(
                retractTarget,
                '用户在 PersistentTask 待处理视图中撤销自动记录',
                operationId(),
              );
              setRetractTarget(null);
              await refresh();
              toast.success('已追加撤销事件');
            } catch (error) {
              toast.error(extractErr(error));
            }
          })();
        }}
      />
    </section>
  );
}

function ReviewCardItem({
  task,
  card,
  jobs,
  onResolved,
}: {
  task: PersistentTask;
  card: GmailObservationReviewCard;
  jobs: Awaited<ReturnType<typeof listJobOpportunities>>;
  onResolved: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [opportunityId, setOpportunityId] = useState(card.candidate_opportunity_id ?? '');
  const [eventKind, setEventKind] = useState<ProcessEventKind>(card.candidate_event_kind);
  const [description, setDescription] = useState(card.description);
  const canApprove = Boolean(opportunityId || card.new_opportunity_json);

  const resolve = async (decision: 'approve' | 'reject' | 'skip') => {
    setBusy(true);
    try {
      await resolveGmailReviewCard({
        taskId: task.id,
        card,
        decision,
        operationId: operationId(),
        opportunityId: opportunityId || undefined,
        eventKind,
        description: description.trim(),
        resolutionNote: decision === 'approve' ? '用户确认或修正候选后批准' : undefined,
      });
      await onResolved();
      toast.success(decision === 'approve' ? '已写入岗位事实时间线' : decision === 'reject' ? '已拒绝候选' : '已跳过候选');
    } catch (error) {
      toast.error(extractErr(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="rounded-lg border border-warning-200 bg-warning-50/40 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-stone-800">{card.source_snapshot.subject || '无主题邮件'}</div>
          <div className="mt-1 text-[11px] text-stone-500">{card.source_snapshot.from_hint || '未知发件人'} · {displayDate(card.source_snapshot.received_at)}</div>
        </div>
        <div className="flex gap-1.5"><Pill>{Math.round(card.confidence * 100)}% 置信度</Pill>{card.unique_match && <Pill tone="success">唯一匹配</Pill>}</div>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-stone-600">{card.rationale}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <FormItem label="关联岗位">
          <SelectInput aria-label="关联岗位" value={opportunityId} onChange={(event) => setOpportunityId(event.target.value)}>
            <option value="">{card.new_opportunity_json ? `新岗位：${card.new_opportunity_json.company_name} · ${card.new_opportunity_json.job_title}` : '请选择岗位'}</option>
            {jobs.map((job) => <option key={job.id} value={job.id}>{job.company_name} · {job.job_title}{job.outcome ? '（已封存）' : ''}</option>)}
          </SelectInput>
        </FormItem>
        <FormItem label="流程事件">
          <SelectInput aria-label="流程事件" value={eventKind} onChange={(event) => setEventKind(event.target.value as ProcessEventKind)}>
            {EVENT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </SelectInput>
        </FormItem>
        <div className="sm:col-span-2"><FormItem label="事实描述"><TextArea rows={2} value={description} onChange={(event) => setDescription(event.target.value)} /></FormItem></div>
      </div>
      <details className="mt-2 text-xs text-stone-500"><summary className="cursor-pointer">查看来源摘要</summary><p className="mt-1 whitespace-pre-wrap">{card.source_snapshot.content_available ? (card.source_snapshot.snippet || '邮件没有可用摘要') : '邮件在增量记录后已不可读取；仅保留 Gmail History 中的消息与会话标识。'}</p></details>
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <Btn kind="ghost" size="sm" icon={<SkipForward size={13} />} disabled={busy} onClick={() => { void resolve('skip'); }}>跳过</Btn>
        <Btn kind="outline" size="sm" icon={<X size={13} />} disabled={busy} onClick={() => { void resolve('reject'); }}>拒绝</Btn>
        <Btn size="sm" icon={<Check size={13} />} loading={busy} disabled={!canApprove || !description.trim()} onClick={() => { void resolve('approve'); }}>批准并记录</Btn>
      </div>
    </article>
  );
}
