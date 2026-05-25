import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { SessionList } from './SessionList';
import { QAPanel } from './QAPanel';
import { ChatPanel } from './ChatPanel';
import { UploadCards, applyDraftMetadata } from './UploadCards';
import { AnalysisRunner, type AnalysisProgress } from './AnalysisRunner';
import { Resizer } from '@/components/ui/Resizer';
import { toast } from '@/store/uiStore';
import { cancelAnalyze, getInterviewRecord, listInterviewRecords } from '@/api/interview';
import type { InterviewRecordDetail, InterviewRecordListItem } from '@/types/api';
import { useIsMounted } from '@/hooks/useIsMounted';

const PANEL_KEY = 'review.panelWidths';

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
  const [search, setSearch] = useSearchParams();
  const [records, setRecords] = useState<InterviewRecordListItem[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<InterviewRecordDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [widths, setWidths] = useState(loadWidths);
  const [analyses, setAnalyses] = useState<Record<string, AnalysisEntry>>({});

  useEffect(() => {
    try { localStorage.setItem(PANEL_KEY, JSON.stringify(widths)); } catch { /* ignore */ }
  }, [widths]);

  const combined: InterviewRecordListItem[] = useMemo(
    () => [...drafts, ...records],
    [drafts, records],
  );

  useEffect(() => {
    let alive = true;
    listInterviewRecords(0, 50)
      .then((rows) => alive && setRecords(rows))
      .catch(() => alive && toast.error('面试记录加载失败'));
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (activeId) return;
    const wanted = search.get('id');
    if (wanted && records.some((r) => r.id === wanted)) setActiveId(wanted);
    else if (records.length > 0) setActiveId(records[0].id);
    else if (drafts.length > 0) setActiveId(drafts[0].id);
  }, [activeId, records, drafts, search]);

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

  const onAnalysisError = (_forActiveId: string, msg: string) => {
    toast.error(`分析失败：${msg}`);
    // Keep the entry so the user can see the error state; they can re-create
    // the draft to retry. (Removing here would silently send them back to the
    // upload cards without explanation.)
  };

  const activeRecord = combined.find((r) => r.id === activeId) ?? null;

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
    const isAnalyzingStatus = ['pending', 'transcribing', 'extracting', 'analyzing'].includes(status);
    const isMockSource = detail?.source === 'mock';
    const hasContent = !!detail && (!!detail.transcript || hasStructuredQA(detail));

    // Mock records always come pre-attached to a record and a running analysis —
    // they never need new uploads. While analysis is in flight, show a
    // dedicated progress card backed by the existing SSE runner (auto-spawned
    // below) instead of UploadCards.
    if (detail && (isAnalyzingStatus || isMockSource) && !hasContent) {
      // Spawn a runner if we don't already have one for this record. The
      // analyses map keys are activeIds; the AnalysisRunner subscribes once.
      if (!a && detail.id && isAnalyzingStatus) {
        // Lazy registration: use a microtask to avoid a setState-in-render.
        queueMicrotask(() => {
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
        });
      }
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
