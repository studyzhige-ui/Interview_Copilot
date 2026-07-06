import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
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

// React Query cache key for the interview-record list. The refresh flows
// below fetch with their own AbortControllers (they need the fresh rows
// value for the active-id fallback logic) and write the result into this
// cache entry, so every consumer sees one list.
const RECORDS_KEY = ['interview', 'records'] as const;

function loadWidths(): { left: number; right: number } {
  try {
    const raw = localStorage.getItem(PANEL_KEY);
    if (!raw) return { left: 280, right: 400 };
    const v = JSON.parse(raw);
    return {
      left: typeof v.left === 'number' ? v.left : 280,
      right: typeof v.right === 'number' ? v.right : 400,
    };
  } catch {
    return { left: 280, right: 400 };
  }
}

// Local-only draft (not yet persisted). The 'draft' source is a frontend
// sentinel — see InterviewRecordListItem.source.
interface Draft extends InterviewRecordListItem {
  source: 'draft';
}

function makeDraft(): Draft {
  return {
    id: `draft-${Date.now()}`,
    title: '新建面试',
    tag: null,
    source: 'draft',
    status: 'draft',
    created_at: new Date().toISOString(),
  };
}

function isDraft(id: string | null): boolean {
  return !!id && id.startsWith('draft-');
}

// Per-active-id analysis runtime kept in ReviewPage state. The AnalysisRunner
// component subscribed for that record_id stays mounted as long as the entry
// exists in `analyses`, so SSE survives switching between sessions.
interface AnalysisEntry {
  record_id: string;
  // user-chosen metadata to apply to the freshly-created record after done
  title: string;
  tag?: string;
  state: AnalysisProgress;
}

export function ReviewPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useSearchParams();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<InterviewRecordDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [widths, setWidths] = useState(loadWidths);
  const [analyses, setAnalyses] = useState<Record<string, AnalysisEntry>>({});

  const { data: records = [], error: recordsError, isFetchedAfterMount } = useQuery({
    queryKey: RECORDS_KEY,
    queryFn: ({ signal }) => listInterviewRecords(0, 50, { signal }),
    // Always refresh on mount: mock-interview completion navigates here
    // with ?id=<fresh record> that a cached list won't contain yet. The
    // cached rows still paint instantly; the selection effect below just
    // waits for the post-mount fetch before defaulting.
    refetchOnMount: 'always',
  });
  useToastOnError(recordsError, '面试记录加载失败');
  const setRecords = useCallback(
    (rows: InterviewRecordListItem[]) => {
      // Cancel the in-flight (mount/background) refetch so its stale
      // response can't land after this deliberate overwrite.
      void queryClient.cancelQueries({ queryKey: RECORDS_KEY });
      queryClient.setQueryData<InterviewRecordListItem[]>([...RECORDS_KEY], rows);
    },
    [queryClient],
  );

  useEffect(() => {
    try { localStorage.setItem(PANEL_KEY, JSON.stringify(widths)); } catch { /* ignore */ }
  }, [widths]);

  const combined: InterviewRecordListItem[] = useMemo(
    () => [...drafts, ...records],
    [drafts, records],
  );

  useEffect(() => {
    if (activeId) return;
    // Don't default off a cached (possibly stale) list: a ?id= deep link
    // may point at a record created seconds ago (mock finish → /review),
    // and picking records[0] here would lock the wrong selection (this
    // effect never runs again once activeId is set). Wait for the
    // post-mount fetch — the cached rows still render meanwhile.
    if (!isFetchedAfterMount) return;
    const wanted = search.get('id');
    if (wanted && records.some((r) => r.id === wanted)) setActiveId(wanted);
    else if (records.length > 0) setActiveId(records[0].id);
    else if (drafts.length > 0) setActiveId(drafts[0].id);
  }, [activeId, records, drafts, search, isFetchedAfterMount]);

  useEffect(() => {
    if (!activeId || isDraft(activeId)) { setDetail(null); return; }
    // Abort the in-flight detail fetch on activeId change — same race
    // shape as the chat-panel transcript loader. Stale writes are
    // already gated by ``alive`` but the backend keeps materialising
    // the abandoned response without the abort.
    const controller = new AbortController();
    let alive = true;
    setDetailLoading(true);
    getInterviewRecord(activeId, { signal: controller.signal })
      .then((d) => alive && setDetail(d))
      .catch((e) => {
        // Aborted on switch → benign, no toast.
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
  };

  const onDraftMutate = (id: string, patch: Partial<InterviewRecordListItem>) => {
    setDrafts((arr) =>
      arr.map((d) => (d.id === id ? { ...d, ...patch, source: 'draft' as const } : d)),
    );
  };

  const onDraftDelete = (id: string) => {
    // If there's an analysis in flight for this draft, tell the backend to
    // revoke the Celery task. Fire-and-forget — if the cancel call itself
    // fails we still drop the local state.
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
    // Cancel any in-flight previous invocation so a fast
    // rename → rename → delete sequence doesn't land the
    // SECOND rename's detail while the user has just deleted
    // the record. Also bail post-await if the user navigated
    // away while the calls were in flight.
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
          // Active record was deleted — fall back to first row.
          const next = rows[0]?.id ?? null;
          setActiveId(next);
          setDetail(null);
          if (next) setSearch({ id: next }, { replace: true });
          else setSearch({}, { replace: true });
        } else {
          // Active record was renamed / re-tagged — re-fetch its detail so
          // QAPanel's header reflects the new title without the user having
          // to switch tabs and back.
          try {
            const fresh = await getInterviewRecord(activeId, { signal: ac.signal });
            if (ac.signal.aborted || !isMounted.current) return;
            setDetail(fresh);
          } catch {
            // Non-fatal — the list still shows the new title; the detail
            // header will catch up on the next id-change useEffect.
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

  // ── Mock review retry ───────────────────────────────────────────────────
  // review_failed is a terminal state the sweeper/worker can land a mock
  // record in; the retry endpoint flips it back to processing_review and
  // re-dispatches the Celery review task.
  // Holds the record id being retried (not a boolean — two review_failed
  // records must not share one "retrying" flag).
  const [retryingReview, setRetryingReview] = useState<string | null>(null);
  // One retry flow, two dispatchers (mock retry-review / upload reanalyze).
  const retryRecord = async (
    recordId: string,
    call: (id: string) => Promise<unknown>,
    errorToast: string,
  ) => {
    setRetryingReview(recordId);
    try {
      await call(recordId);
      if (!isMounted.current) return;
      // Drop any stale (errored) runner entry — the auto-spawn effect bails
      // on an existing entry, so leaving it would mean no SSE runner for the
      // re-dispatched run and a pane frozen at "建立 SSE 连接中".
      setAnalyses((prev) => {
        if (!(recordId in prev)) return prev;
        const { [recordId]: _, ...rest } = prev;
        return rest;
      });
      // Refresh list + detail: the new in-flight status is picked up by the
      // auto-spawn effect, which opens an SSE runner for it.
      await onRecordChanged();
    } catch {
      if (isMounted.current) toast.error(errorToast);
    } finally {
      if (isMounted.current) setRetryingReview(null);
    }
  };
  const retryReview = (recordId: string) =>
    retryRecord(recordId, retryMockReview, '重试复盘失败，请稍后再试');
  const retryUploadAnalysis = (recordId: string) =>
    retryRecord(recordId, reanalyzeRecord, '重新分析失败，请稍后再试');

  // ── Analysis lifecycle ──────────────────────────────────────────────────
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
    // Analysis completion can fire a few seconds after the user has
    // navigated away — guard every setState past an await.
    try {
      const rows = await listInterviewRecords(0, 50);
      if (!isMounted.current) return;
      setRecords(rows);
      const target = entry?.record_id;
      if (target) {
        // Drafts: rename / re-tag the freshly-promoted record. For mock-source
        // records we created the row up front, so this is a no-op there.
        if (forActiveId !== target && entry) {
          await applyDraftMetadata(target, { title: entry.title, tag: entry.tag });
          if (!isMounted.current) return;
          const refreshed = await listInterviewRecords(0, 50);
          if (!isMounted.current) return;
          setRecords(refreshed);
        }
        // Re-hydrate detail so QAPanel picks up the new qa[] + analysis.
        try {
          const fresh = await getInterviewRecord(target);
          if (!isMounted.current) return;
          setDetail(fresh);
        } catch {
          // ignore — useEffect will retry on next activeId change
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
      // Keep the entry so the user can see the error state; they can
      // re-create the draft to retry. (Removing here would silently send
      // them back to the upload cards without explanation.)
      return;
    }
    // Real record (e.g. a mock review that just failed while the user was
    // watching): drop the dead runner entry so a retry can register a fresh
    // one, and refetch so the terminal status (review_failed) renders its
    // retry card instead of a spinner frozen on the errored stream.
    setAnalyses((prev) => {
      if (!(forActiveId in prev)) return prev;
      const { [forActiveId]: _, ...rest } = prev;
      return rest;
    });
    void onRecordChanged();
  };

  const activeRecord = combined.find((r) => r.id === activeId) ?? null;

  // ── Auto-spawn an AnalysisRunner for the active record ──────────────
  // When the user lands on a record whose status is in-flight
  // (pending/transcribing/extracting/analyzing) but no Runner has
  // been registered yet, register one. Pre-fix this lived inside
  // the render-time ``middle = (() => { ... })()`` closure, gated
  // by ``queueMicrotask`` to avoid the setState-in-render warning.
  // That worked in React 18 stable but is an anti-pattern: React 19
  // / concurrent rendering can discard a render mid-flight, leaving
  // the queued microtask's setState dangling against a non-
  // committed state. An effect is the contractually-correct anchor.
  //
  // Deps are the four inputs the registration decision reads:
  //   - activeId, the row we're considering
  //   - whether it's a draft (drafts get a different path — see
  //     middle's UploadCards branch)
  //   - detail.status, the source of the analyzing-flag
  //   - whether an entry for this activeId already exists in
  //     analyses (otherwise we'd register a second Runner)
  //
  // Reading ``analyses[activeId]`` directly inside the effect would
  // make every register-call into a re-trigger (analyses changes on
  // setAnalyses), so we read it from a ref synced each render. This
  // mirrors the "latest-state-ref" idiom we use elsewhere for
  // AbortController patterns.
  const analysesRef = useRef(analyses);
  analysesRef.current = analyses;
  useEffect(() => {
    if (!activeId || !detail || isDraft(activeId)) return;
    const status = (detail.status ?? '').toLowerCase();
    const isAnalyzingStatus = ['pending', 'transcribing', 'extracting', 'analyzing', 'processing_review'].includes(status);
    if (!isAnalyzingStatus) return;
    if (analysesRef.current[activeId]) return;  // already registered

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
  }, [activeId, detail?.id, detail?.status, detail?.title, detail?.tag]);

  // Map of record_id → live progress, used by SessionList to render a pill
  // that shows the current sub-stage (connecting / transcribing / analyzing).
  const analyzingStates = useMemo(() => {
    const m = new Map<string, AnalysisProgress>();
    for (const [id, entry] of Object.entries(analyses)) {
      m.set(id, entry.state);
    }
    return m;
  }, [analyses]);

  const middle = (() => {
    if (!activeId) return <QAPanel detail={null} loading={false} />;
    const a = analyses[activeId] ?? null;
    if (isDraft(activeId)) {
      const draft = drafts.find((d) => d.id === activeId);
      return (
        <UploadCards
          key={activeId}
          initialTitle={draft?.title}
          analysis={a?.state ?? null}
          onStart={(payload) => startAnalysis(activeId, payload)}
        />
      );
    }
    // For real records: if no content and not analyzing, show upload cards.
    const status = (detail?.status ?? '').toLowerCase();
    const isAnalyzingStatus = ['pending', 'transcribing', 'extracting', 'analyzing', 'processing_review'].includes(status);
    const isMockSource = detail?.source === 'mock';
    const hasContent = !!detail && (!!detail.transcript || hasStructuredQA(detail));

    // A failed mock review must NOT fall into the AnalyzingState spinner
    // below (it would spin forever) — show an explicit retry card wired
    // to the retry-review endpoint.
    if (detail && status === 'review_failed') {
      return (
        <ReviewFailedState
          kind="mock"
          message={detail.error_message ?? null}
          retrying={retryingReview === detail.id}
          onRetry={() => { void retryReview(detail.id); }}
        />
      );
    }

    // Failed upload analysis: the audio + transcript are still persisted —
    // one-click rerun (ANA-7) instead of the old delete-and-reupload dead end.
    // With partial results (transcript/QA rows persisted before the failure)
    // keep them readable and show a slim retry banner instead of hiding
    // everything behind the full-page card.
    if (detail && status === 'failed' && !isMockSource) {
      if (hasContent) {
        return (
          <div className="h-full flex flex-col">
            <div className="mx-6 mt-4 flex items-center gap-3 bg-red-50 border border-red-200 rounded-xl px-4 py-2.5">
              <span className="text-xs text-red-700 flex-1">
                分析未完成：{detail.error_message || '中途出错'}。已保留的转录与逐题结果如下。
              </span>
              <button
                type="button"
                onClick={() => { void retryUploadAnalysis(detail.id); }}
                disabled={retryingReview === detail.id}
                className="text-xs text-white px-3 py-1.5 rounded bg-primary-600 hover:bg-primary-700 disabled:opacity-60 shrink-0"
              >
                {retryingReview === detail.id ? '重新派发中…' : '重新分析'}
              </button>
            </div>
            <div className="flex-1 min-h-0">
              <QAPanel detail={detail} loading={detailLoading} />
            </div>
          </div>
        );
      }
      return (
        <ReviewFailedState
          kind="upload"
          message={detail.error_message ?? null}
          retrying={retryingReview === detail.id}
          onRetry={() => { void retryUploadAnalysis(detail.id); }}
        />
      );
    }

    // Mock records always come pre-attached to a record and a running analysis —
    // they never need new uploads. While analysis is in flight, show a
    // dedicated progress card backed by the existing SSE runner (auto-spawned
    // below) instead of UploadCards.
    if (detail && (isAnalyzingStatus || isMockSource) && !hasContent) {
      // Runner registration moved into a dedicated useEffect above —
      // see "Auto-spawn an AnalysisRunner for the active record".
      // Here we just read the (possibly-still-loading) entry to
      // pass progress through.
      return <AnalyzingState progress={a?.state ?? null} sourceLabel={isMockSource ? '模拟面试' : '面试录音'} />;
    }

    if (!hasContent && !detailLoading) {
      return (
        <UploadCards
          key={activeId}
          initialTitle={activeRecord?.title}
          analysis={a?.state ?? null}
          onStart={(payload) => startAnalysis(activeId, payload)}
        />
      );
    }
    return <QAPanel detail={detail} loading={detailLoading} />;
  })();

  return (
    <div className="h-full flex">
      {/* Headless SSE runners — one per in-flight analysis, kept alive
       *  regardless of which session the user is currently looking at. */}
      {Object.entries(analyses).map(([id, a]) => (
        <AnalysisRunner
          key={id}
          recordId={a.record_id}
          onProgress={(p) => setAnalysisState(id, p)}
          onDone={() => onAnalysisDone(id)}
          onError={(m) => onAnalysisError(id, m)}
        />
      ))}

      <SessionList
        records={combined}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={onNew}
        onChanged={onRecordChanged}
        onDraftMutate={onDraftMutate}
        onDraftDelete={onDraftDelete}
        analyzingStates={analyzingStates}
        width={widths.left}
      />
      <Resizer
        value={widths.left}
        onChange={(v) => setWidths((w) => ({ ...w, left: v }))}
        min={200}
        max={420}
        direction="right"
      />
      <section className="flex-1 min-w-0 overflow-y-auto bg-cream-50">{middle}</section>
      <Resizer
        value={widths.right}
        onChange={(v) => setWidths((w) => ({ ...w, right: v }))}
        min={280}
        max={560}
        direction="left"
      />
      <ChatPanel
        interviewId={!isDraft(activeId ?? '') ? activeId : null}
        sessionTitle={activeRecord?.title ?? null}
        sessionType="debrief"
        width={widths.right}
      />
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
  /** mock = review generation failed; upload = analysis pipeline failed. */
  kind: 'mock' | 'upload';
}) {
  const copy = kind === 'mock'
    ? {
        header: '模拟面试 · 复盘生成失败',
        title: '复盘没有生成成功',
        hint: '生成过程中出现异常。面试问答内容已完整保留，可以直接重试。',
        button: '重试复盘',
      }
    : {
        header: '面试录音 · 分析失败',
        title: '分析没有完成',
        hint: '录音和已完成的中间结果都已保留，重新分析会从断点继续，不需要重新上传。',
        button: '重新分析',
      };
  return (
    <div className="max-w-3xl mx-auto p-10">
      <div className="bg-white border border-red-200 rounded-2xl shadow-sm p-10">
        <div className="text-xs text-stone-500 mb-2">{copy.header}</div>
        <div className="text-sm text-red-700 mb-1 font-medium">{copy.title}</div>
        <div className="text-xs text-stone-500 mb-6">
          {message || copy.hint}
        </div>
        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          className="text-sm text-white px-4 py-2 rounded-lg bg-primary-600 hover:bg-primary-700 disabled:opacity-60"
        >
          {retrying ? '重新派发中…' : copy.button}
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
    status === 'transcribing' ? '正在语音识别…'
    : status === 'extracting' ? '正在抽取 Q&A…'
    : status === 'analyzing' ? '正在逐题分析与综合…'
    : status === 'processing_review' ? '正在生成复盘…'
    : status === 'pending' ? '排队中…'
    : '建立 SSE 连接中…';
  return (
    <div className="max-w-3xl mx-auto p-10">
      <div className="bg-white border border-stone-200 rounded-2xl shadow-sm p-10">
        <div className="text-xs text-stone-500 mb-2">{sourceLabel} · 复盘生成中</div>
        <div className="flex items-center gap-3 mb-4">
          <div className="w-2 h-2 rounded-full bg-primary-500 animate-pulse" />
          <div className="text-sm text-primary-700 font-mono">● {phaseHint} {percent}%</div>
        </div>
        <div className="w-full h-2 bg-stone-100 rounded-full overflow-hidden mb-3">
          <div
            className="h-full bg-primary-500 transition-all duration-300 ease-out"
            style={{ width: `${percent}%` }}
          />
        </div>
        <div className="text-[11px] text-stone-400 mt-3">
          可以切到其他面试或对话页面，分析会继续在后台运行；完成后这里会自动切换到复盘视图。
        </div>
      </div>
    </div>
  );
}
