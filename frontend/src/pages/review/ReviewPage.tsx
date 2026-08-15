import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { Bot, Sparkles, ChevronRight } from 'lucide-react';
import { SessionList } from './SessionList';
import { QAPanel } from './QAPanel';
import { ChatPanel } from './chat/ChatPanel';
import { UploadCards, applyDraftMetadata } from './UploadCards';
import { AnalysisRunner, type AnalysisProgress } from './AnalysisRunner';
import { Resizer } from '@/components/ui/Resizer';
import { toast } from '@/store/uiStore';
import { cancelAnalyze, getInterviewRecord, listInterviewRecords, reanalyzeRecord } from '@/api/interview';
import { retryMockReview } from '@/api/mock';
import { useToastOnError } from '@/hooks/useToastOnError';
import type { InterviewRecordDetail, InterviewRecordListItem } from '@/types/api';
import { useIsMounted } from '@/hooks/useIsMounted';

const PANEL_KEY = 'review.panelWidths';
const RECORDS_KEY = ['interview', 'records'] as const;

function loadWidths(): { left: number; right: number } {
  try {
    const raw = localStorage.getItem(PANEL_KEY);
    if (!raw) return { left: 280, right: 380 };
    const v = JSON.parse(raw);
    return {
      left: typeof v.left === 'number' ? v.left : 280,
      right: typeof v.right === 'number' ? v.right : 380,
    };
  } catch {
    return { left: 280, right: 380 };
  }
}

interface Draft extends InterviewRecordListItem {
  source: 'draft';
}

function makeDraft(): Draft {
  return {
    id: `draft-${Date.now()}`,
    title: '新建面试复盘',
    tag: null,
    source: 'draft',
    status: 'draft',
    created_at: new Date().toISOString(),
  };
}

function isDraft(id: string | null): boolean {
  return !!id && id.startsWith('draft-');
}

interface AnalysisEntry {
  record_id: string;
  title: string;
  tag?: string;
  state: AnalysisProgress;
}

export function ReviewPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useSearchParams();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selectedActiveId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<InterviewRecordDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [widths, setWidths] = useState(loadWidths);
  const [analyses, setAnalyses] = useState<Record<string, AnalysisEntry>>({});
  const [mobilePane, setMobilePane] = useState<'records' | 'review' | 'chat'>('review');
  const [copilotOpen, setCopilotOpen] = useState(true);
  const [questionSelection, setQuestionSelection] = useState<{
    recordId: string | null;
    indexes: number[];
  }>({ recordId: null, indexes: [] });

  const { data: records = [], error: recordsError, isFetchedAfterMount } = useQuery({
    queryKey: RECORDS_KEY,
    queryFn: ({ signal }) => listInterviewRecords(0, 50, { signal }),
    refetchOnMount: 'always',
  });
  useToastOnError(recordsError, '面试记录加载失败');

  const setRecords = useCallback(
    (rows: InterviewRecordListItem[]) => {
      void queryClient.cancelQueries({ queryKey: RECORDS_KEY });
      queryClient.setQueryData<InterviewRecordListItem[]>([...RECORDS_KEY], rows);
    },
    [queryClient],
  );

  useEffect(() => {
    try {
      localStorage.setItem(PANEL_KEY, JSON.stringify(widths));
    } catch {
      /* ignore */
    }
  }, [widths]);

  const combined: InterviewRecordListItem[] = useMemo(
    () => [...drafts, ...records],
    [drafts, records],
  );

  const defaultActiveId = useMemo(() => {
    if (!isFetchedAfterMount) return null;
    const wanted = search.get('id');
    if (wanted && records.some((record) => record.id === wanted)) return wanted;
    return records[0]?.id ?? drafts[0]?.id ?? null;
  }, [drafts, isFetchedAfterMount, records, search]);

  const activeId = selectedActiveId ?? defaultActiveId;
  const selectedQuestionIndexes = questionSelection.recordId === activeId
    ? questionSelection.indexes
    : [];

  const toggleQuestion = useCallback((index: number) => {
    if (!activeId || isDraft(activeId)) return;
    setQuestionSelection((previous) => {
      const indexes = previous.recordId === activeId ? previous.indexes : [];
      const selected = indexes.includes(index);
      return {
        recordId: activeId,
        indexes: selected
          ? indexes.filter((item) => item !== index)
          : [...indexes, index],
      };
    });
    setCopilotOpen(true);
    setMobilePane('chat');
  }, [activeId]);

  const removeQuestion = useCallback((index: number) => {
    setQuestionSelection((previous) => previous.recordId === activeId
      ? { ...previous, indexes: previous.indexes.filter((item) => item !== index) }
      : previous);
  }, [activeId]);

  const clearQuestions = useCallback(() => {
    setQuestionSelection((previous) => previous.recordId === activeId
      ? { ...previous, indexes: [] }
      : previous);
  }, [activeId]);

  useEffect(() => {
    if (!activeId || isDraft(activeId)) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    let alive = true;
    setDetailLoading(true);
    getInterviewRecord(activeId, { signal: controller.signal })
      .then((d) => alive && setDetail(d))
      .catch((e) => {
        if ((e as { code?: string })?.code === 'ERR_CANCELED') return;
        if (alive) toast.error('记录详情加载失败');
      })
      .finally(() => alive && setDetailLoading(false));
    return () => {
      alive = false;
      controller.abort();
    };
  }, [activeId]);

  const onNew = () => {
    const d = makeDraft();
    setDrafts((arr) => [d, ...arr]);
    setActiveId(d.id);
    setSearch({}, { replace: true });
    setMobilePane('review');
  };

  const onDraftMutate = (id: string, patch: Partial<InterviewRecordListItem>) => {
    setDrafts((arr) =>
      arr.map((d) => (d.id === id ? { ...d, ...patch, source: 'draft' as const } : d)),
    );
  };

  const onDraftDelete = (id: string) => {
    const a = analyses[id];
    if (a) {
      cancelAnalyze(a.record_id).catch(() => {});
    }
    setDrafts((arr) => arr.filter((d) => d.id !== id));
    setAnalyses((prev) => {
      if (!(id in prev)) return prev;
      const { [id]: _, ...rest } = prev;
      return rest;
    });
    if (activeId === id) {
      setActiveId(null);
      setDetail(null);
    }
  };

  const isMounted = useIsMounted();
  const onRecordChangedAcRef = useRef<AbortController | null>(null);
  const onRecordChanged = async () => {
    onRecordChangedAcRef.current?.abort();
    const ac = new AbortController();
    onRecordChangedAcRef.current = ac;
    try {
      const rows = await listInterviewRecords(0, 50, { signal: ac.signal });
      if (ac.signal.aborted || !isMounted.current) return;
      setRecords(rows);
      if (activeId && !isDraft(activeId)) {
        const stillExists = rows.some((r) => r.id === activeId);
        if (!stillExists) {
          const next = rows[0]?.id ?? null;
          setActiveId(next);
          setDetail(null);
          if (next) setSearch({ id: next }, { replace: true });
          else setSearch({}, { replace: true });
        } else {
          try {
            const fresh = await getInterviewRecord(activeId, { signal: ac.signal });
            if (ac.signal.aborted || !isMounted.current) return;
            setDetail(fresh);
          } catch {
            // Non-fatal
          }
        }
      }
    } catch (e) {
      if ((e as { code?: string })?.code === 'ERR_CANCELED') return;
      if (isMounted.current) toast.error('刷新记录列表失败');
    } finally {
      if (onRecordChangedAcRef.current === ac) onRecordChangedAcRef.current = null;
    }
  };

  const [retryingReview, setRetryingReview] = useState<string | null>(null);
  const retryRecord = async (
    recordId: string,
    call: (id: string) => Promise<unknown>,
    errorToast: string,
  ) => {
    setRetryingReview(recordId);
    try {
      await call(recordId);
      if (!isMounted.current) return;
      setAnalyses((prev) => {
        if (!(recordId in prev)) return prev;
        const { [recordId]: _, ...rest } = prev;
        return rest;
      });
      await onRecordChanged();
    } catch {
      if (isMounted.current) toast.error(errorToast);
    } finally {
      if (isMounted.current) setRetryingReview(null);
    }
  };

  const retryReview = (recordId: string) =>
    retryRecord(recordId, retryMockReview, '重试复盘失败，请稍后再试');
  const retryUploadAnalysis = (
    recordId: string,
    fromStage?: 'extract' | 'transcribe',
  ) =>
    retryRecord(
      recordId,
      (id) => reanalyzeRecord(id, fromStage ? { fromStage } : undefined),
      '重新分析失败，请稍后再试',
    );

  const startAnalysis = (
    forActiveId: string,
    payload: { record_id: string; title: string; tag?: string },
  ) => {
    setAnalyses((prev) => ({
      ...prev,
      [forActiveId]: {
        record_id: payload.record_id,
        title: payload.title,
        tag: payload.tag,
        state: { phase: 'connecting', percent: 0 },
      },
    }));
  };

  const setAnalysisState = (forActiveId: string, state: AnalysisProgress) => {
    setAnalyses((prev) => {
      const cur = prev[forActiveId];
      if (!cur) return prev;
      return { ...prev, [forActiveId]: { ...cur, state } };
    });
  };

  const onAnalysisDone = async (forActiveId: string) => {
    const entry = analyses[forActiveId];
    setAnalyses((prev) => {
      if (!(forActiveId in prev)) return prev;
      const { [forActiveId]: _, ...rest } = prev;
      return rest;
    });
    try {
      const rows = await listInterviewRecords(0, 50);
      if (!isMounted.current) return;
      setRecords(rows);
      const target = entry?.record_id;
      if (target) {
        if (forActiveId !== target && entry) {
          await applyDraftMetadata(target, { title: entry.title, tag: entry.tag });
          if (!isMounted.current) return;
          const refreshed = await listInterviewRecords(0, 50);
          if (!isMounted.current) return;
          setRecords(refreshed);
        }
        try {
          const fresh = await getInterviewRecord(target);
          if (!isMounted.current) return;
          setDetail(fresh);
        } catch {
          // ignore
        }
        if (!isMounted.current) return;
        setActiveId((cur) => (cur === forActiveId ? target : cur));
        setDrafts((arr) => arr.filter((d) => d.id !== forActiveId));
        if (activeId === forActiveId) setSearch({ id: target }, { replace: true });
      }
    } catch {
      if (isMounted.current) toast.error('刷新记录失败');
    }
  };

  const onAnalysisError = (forActiveId: string, msg: string) => {
    toast.error(`分析失败：${msg}`);
    if (isDraft(forActiveId)) {
      return;
    }
    setAnalyses((prev) => {
      if (!(forActiveId in prev)) return prev;
      const { [forActiveId]: _, ...rest } = prev;
      return rest;
    });
    void onRecordChanged();
  };

  const activeRecord = combined.find((r) => r.id === activeId) ?? null;

  useEffect(() => {
    if (!activeId || !detail || isDraft(activeId)) return;
    const status = (detail.status ?? '').toLowerCase();
    const isAnalyzingStatus = ['pending', 'transcribing', 'extracting', 'analyzing', 'processing_review'].includes(status);
    if (!isAnalyzingStatus) return;
    if (analyses[activeId]) return;

    setAnalyses((prev) => {
      if (prev[activeId]) return prev;
      return {
        ...prev,
        [activeId]: {
          record_id: detail.id,
          title: detail.title || '面试',
          tag: detail.tag ?? undefined,
          state: { phase: 'connecting', percent: 0 },
        },
      };
    });
  }, [activeId, analyses, detail]);

  const analyzingStates = useMemo(() => {
    const m = new Map<string, AnalysisProgress>();
    for (const [id, entry] of Object.entries(analyses)) {
      m.set(id, entry.state);
    }
    return m;
  }, [analyses]);

  const middle = (() => {
    if (!activeId) {
      return (
        <UploadCards
          analysis={null}
          onStart={(payload) => {
            const d = makeDraft();
            setDrafts((arr) => [d, ...arr]);
            setActiveId(d.id);
            startAnalysis(d.id, payload);
          }}
        />
      );
    }

    if (isDraft(activeId)) {
      const entry = analyses[activeId];
      return (
        <UploadCards
          key={activeId}
          initialTitle={activeRecord?.title}
          analysis={entry ? entry.state : null}
          onStart={(payload) => startAnalysis(activeId, payload)}
        />
      );
    }

    const live = analyses[activeId];
    if (live) {
      const isMock = activeRecord?.source === 'mock';
      return (
        <AnalyzingState
          progress={live.state}
          sourceLabel={isMock ? '模拟面试' : '面试录音'}
        />
      );
    }

    if (detailLoading) {
      return (
        <div className="flex-1 min-w-0 flex items-center justify-center p-12">
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 rounded-full border-2 border-blue-600 border-r-transparent animate-spin" />
            <span className="text-xs font-medium text-slate-500">正在载入面试复盘数据…</span>
          </div>
        </div>
      );
    }

    if (!detail) {
      return (
        <div className="p-8 text-center text-xs text-slate-400">
          未能加载记录详情
        </div>
      );
    }

    const s = (detail.status ?? '').toLowerCase();

    if (s === 'review_failed') {
      return (
        <ReviewFailedState
          message={detail.error_message ?? null}
          retrying={retryingReview === activeId}
          onRetry={() => retryReview(activeId)}
          kind="mock"
        />
      );
    }

    if (s === 'failed') {
      return (
        <ReviewFailedState
          message={detail.error_message ?? null}
          retrying={retryingReview === activeId}
          onRetry={() => retryUploadAnalysis(activeId)}
          kind="upload"
        />
      );
    }

    const isAnalyzed = s === 'completed' || s === 'analyzed' || hasStructuredQA(detail);

    if (!isAnalyzed) {
      return (
        <UploadCards
          key={activeId}
          initialTitle={detail.title}
          analysis={null}
          onStart={(payload) => startAnalysis(activeId, payload)}
        />
      );
    }

    return (
      <QAPanel
        key={detail.id}
        detail={detail}
        loading={false}
        reanalyzing={retryingReview === activeId}
        onReanalyze={(mode) => {
          if (mode === 'report') retryUploadAnalysis(activeId);
          else if (mode === 'extract') retryUploadAnalysis(activeId, 'extract');
          else if (mode === 'transcribe') retryUploadAnalysis(activeId, 'transcribe');
        }}
        selectedQuestionIndexes={selectedQuestionIndexes}
        onToggleQuestion={toggleQuestion}
      />
    );
  })();

  return (
    <div className="h-full flex flex-col lg:flex-row relative overflow-hidden bg-[#F8FAFC]">
      {/* Background Active Analysis Runners */}
      {Object.entries(analyses).map(([draftId, entry]) => (
        <AnalysisRunner
          key={draftId}
          recordId={entry.record_id}
          onProgress={(p) => setAnalysisState(draftId, p)}
          onDone={() => onAnalysisDone(draftId)}
          onError={(msg) => onAnalysisError(draftId, msg)}
        />
      ))}

      {/* Mobile Switch Tabs */}
      <div className="flex items-center gap-1 border-b border-slate-200 bg-white/90 p-2 lg:hidden">
        {(
          [
            ['records', '档案列表'],
            ['review', '复盘报告'],
            ['chat', 'Copilot 对话'],
          ] as const
        ).map(([pane, label]) => (
          <button
            key={pane}
            type="button"
            onClick={() => setMobilePane(pane)}
            className={`flex-1 rounded-full px-3 py-1.5 text-xs font-semibold transition-all ${
              mobilePane === pane
                ? 'bg-blue-50 text-blue-700 shadow-xs'
                : 'text-slate-500'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Left Session List */}
      <SessionList
        records={combined}
        activeId={activeId}
        onSelect={(id) => {
          setActiveId(id);
          setMobilePane('review');
          if (isDraft(id)) setSearch({}, { replace: true });
          else setSearch({ id }, { replace: true });
        }}
        onNew={onNew}
        onChanged={onRecordChanged}
        onDraftMutate={onDraftMutate}
        onDraftDelete={onDraftDelete}
        analyzingStates={analyzingStates}
        width={widths.left}
        className={`${mobilePane === 'records' ? 'flex' : 'hidden'} lg:flex min-h-0 flex-1 lg:flex-none`}
      />

      <div className="hidden lg:contents">
        <Resizer
          value={widths.left}
          onChange={(v) => setWidths((w) => ({ ...w, left: v }))}
          min={220}
          max={400}
          direction="right"
        />
      </div>

      {/* Center Stage Workspace */}
      <section className={`${mobilePane === 'review' ? 'block' : 'hidden'} lg:block flex-1 min-h-0 min-w-0 overflow-y-auto relative`}>
        {middle}

        {/* Floating Toggle for Copilot Sidebar (when collapsed) */}
        {!copilotOpen && (
          <button
            type="button"
            onClick={() => setCopilotOpen(true)}
            className="hidden lg:flex fixed right-6 bottom-6 items-center gap-2 px-4 py-2.5 rounded-full bg-gradient-to-r from-blue-600 to-indigo-600 text-white font-medium text-xs shadow-lg shadow-blue-500/25 hover:scale-105 transition-all z-30 cursor-pointer"
          >
            <Bot size={16} />
            <span>开启面试副驾 Copilot</span>
          </button>
        )}
      </section>

      {/* Right Copilot Chat Drawer / Split Panel */}
      {copilotOpen && (
        <>
          <div className="hidden lg:contents">
            <Resizer
              value={widths.right}
              onChange={(v) => setWidths((w) => ({ ...w, right: v }))}
              min={280}
              max={560}
              direction="left"
            />
          </div>

          <div
            style={{ width: widths.right }}
            className={`${mobilePane === 'chat' ? 'flex' : 'hidden'} lg:flex flex-col h-full bg-white/95 border-l border-slate-200/80 shadow-xs relative`}
          >
            {/* Copilot Header with Collapse */}
            <div className="h-12 px-4 border-b border-slate-100 flex items-center justify-between shrink-0 bg-slate-50/60">
              <div className="flex items-center gap-2">
                <Sparkles size={15} className="text-purple-600" />
                <span className="text-xs font-bold text-slate-800">本场面试副驾</span>
              </div>
              <button
                type="button"
                onClick={() => setCopilotOpen(false)}
                title="收起副驾侧栏"
                className="hidden lg:flex p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 transition-colors"
              >
                <ChevronRight size={15} />
              </button>
            </div>

            <div className="flex-1 min-h-0 flex flex-col w-full">
              <ChatPanel
                interviewId={!isDraft(activeId ?? '') ? activeId : null}
                sessionTitle={activeRecord?.title ?? null}
                sessionType="debrief"
                questionIndexes={selectedQuestionIndexes}
                onRemoveQuestion={removeQuestion}
                onClearQuestions={clearQuestions}
                flexible={true}
                className="flex-1 min-h-0 w-full"
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function hasStructuredQA(detail: InterviewRecordDetail): boolean {
  return Array.isArray(detail.qa) && detail.qa.length > 0;
}

function ReviewFailedState({
  message,
  retrying,
  onRetry,
  kind,
}: {
  message: string | null;
  retrying: boolean;
  onRetry: () => void;
  kind: 'mock' | 'upload';
}) {
  const copy = kind === 'mock'
    ? {
        header: '模拟面试 · 复盘生成未完成',
        title: '复盘生成遇到中断',
        hint: '问答内容已完整安全保留，点击下方按钮即可直接重试生成。',
        button: '重新生成复盘',
      }
    : {
        header: '面试录音 · 分析未完成',
        title: '分析未完全结束',
        hint: '音频与中间转录结果已保留，无需重复上传文件。',
        button: '重新执行分析',
      };

  return (
    <div className="max-w-3xl mx-auto p-8 md:p-12">
      <div className="bg-white border border-red-200/80 rounded-3xl shadow-sm p-8">
        <div className="text-xs font-bold text-red-500 uppercase tracking-wider mb-2">
          {copy.header}
        </div>
        <div className="text-base font-bold text-slate-800 mb-1">{copy.title}</div>
        <p className="text-xs text-slate-500 mb-6 leading-relaxed">
          {message || copy.hint}
        </p>
        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          className="px-5 py-2.5 rounded-full bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold transition-all shadow-sm disabled:opacity-50 cursor-pointer"
        >
          {retrying ? '正在重新派发中…' : copy.button}
        </button>
      </div>
    </div>
  );
}

function AnalyzingState({
  progress,
  sourceLabel,
}: {
  progress: AnalysisProgress | null;
  sourceLabel: string;
}) {
  const percent = progress?.percent ?? 0;
  const status = progress?.status ?? '';
  const phaseHint =
    status === 'transcribing' ? '正在进行高精度语音识别…'
    : status === 'extracting' ? '正在抽取结构化 Q&A…'
    : status === 'analyzing' ? '正在进行 STAR 深度多维诊断…'
    : status === 'processing_review' ? '正在生成复盘诊断报告…'
    : status === 'pending' ? '任务排队中…'
    : '建立 SSE 实时连接中…';

  return (
    <div className="max-w-3xl mx-auto p-8 md:p-12">
      <div className="bg-white/90 backdrop-blur-xl border border-slate-200/90 rounded-3xl shadow-lg p-8">
        <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">
          {sourceLabel} · AI 智能复盘中
        </div>
        <div className="flex items-center gap-3 mb-4">
          <div className="w-2.5 h-2.5 rounded-full bg-blue-600 animate-pulse" />
          <div className="text-sm font-semibold text-blue-700 font-mono">
            ● {phaseHint} {percent}%
          </div>
        </div>
        <div className="w-full h-2.5 bg-slate-100 rounded-full overflow-hidden mb-4 p-0.5 shadow-inner">
          <div
            className="h-full bg-gradient-to-r from-blue-500 to-purple-600 rounded-full transition-all duration-300 ease-out"
            style={{ width: `${percent}%` }}
          />
        </div>
        <p className="text-xs text-slate-400 leading-relaxed">
          任务在后台持续执行，完成后将自动刷新呈现全量复盘报告。
        </p>
      </div>
    </div>
  );
}
