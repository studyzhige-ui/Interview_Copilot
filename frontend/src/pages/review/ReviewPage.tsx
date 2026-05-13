import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { SessionList } from './SessionList';
import { QAPanel } from './QAPanel';
import { ChatPanel } from './ChatPanel';
import { UploadCards, applyDraftMetadata } from './UploadCards';
import { Resizer } from '@/components/ui/Resizer';
import { toast } from '@/store/uiStore';
import { getInterviewRecord, listInterviewRecords } from '@/api/interview';
import type { InterviewRecordDetail, InterviewRecordListItem } from '@/types/api';

const PANEL_KEY = 'review.panelWidths';

function loadWidths(): { left: number; right: number } {
  try {
    const raw = localStorage.getItem(PANEL_KEY);
    if (!raw) return { left: 260, right: 360 };
    const v = JSON.parse(raw);
    return {
      left: typeof v.left === 'number' ? v.left : 260,
      right: typeof v.right === 'number' ? v.right : 360,
    };
  } catch {
    return { left: 260, right: 360 };
  }
}

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

export function ReviewPage() {
  const [search, setSearch] = useSearchParams();
  const [records, setRecords] = useState<InterviewRecordListItem[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<InterviewRecordDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [widths, setWidths] = useState(loadWidths);

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
    let alive = true;
    setDetailLoading(true);
    getInterviewRecord(activeId)
      .then((d) => alive && setDetail(d))
      .catch(() => alive && toast.error('记录详情加载失败'))
      .finally(() => alive && setDetailLoading(false));
    return () => { alive = false; };
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
    setDrafts((arr) => arr.filter((d) => d.id !== id));
    if (activeId === id) {
      setActiveId(null);
      setDetail(null);
    }
  };

  const onRecordChanged = async () => {
    // Triggered after a rename / delete / tag-change of a REAL record.
    // Re-fetch the list, and if the currently-active record has disappeared
    // (deleted), promote the first remaining record (or null) so the middle
    // pane and ChatPanel don't keep showing stale content.
    try {
      const rows = await listInterviewRecords(0, 50);
      setRecords(rows);
      if (activeId && !isDraft(activeId) && !rows.some((r) => r.id === activeId)) {
        const next = rows[0]?.id ?? null;
        setActiveId(next);
        setDetail(null);
        if (next) setSearch({ id: next }, { replace: true });
        else setSearch({}, { replace: true });
      }
    } catch {
      toast.error('刷新记录列表失败');
    }
  };

  const onAnalyzed = async (recordTitle: string, recordTag?: string) => {
    try {
      const rows = await listInterviewRecords(0, 50);
      setRecords(rows);
      const newest = rows[0];
      if (newest) {
        // Apply the user's chosen title/tag to the freshly-created record.
        await applyDraftMetadata(newest.id, { title: recordTitle, tag: recordTag });
        // Refetch list once more so the renamed row is visible everywhere.
        const refreshed = await listInterviewRecords(0, 50);
        setRecords(refreshed);
        setActiveId(newest.id);
        // Discard the corresponding draft.
        setDrafts([]);
        setSearch({ id: newest.id }, { replace: true });
      }
    } catch {
      toast.error('刷新记录失败');
    }
  };

  const activeRecord = combined.find((r) => r.id === activeId) ?? null;

  const middle = (() => {
    if (!activeId) return <QAPanel detail={null} loading={false} />;
    if (isDraft(activeId)) {
      const draft = drafts.find((d) => d.id === activeId);
      return (
        <UploadCards
          initialTitle={draft?.title}
          onAnalyzed={onAnalyzed}
        />
      );
    }
    const hasContent = !!detail && (!!detail.transcript || hasStructuredQA(detail));
    if (!hasContent && !detailLoading) {
      return <UploadCards initialTitle={activeRecord?.title} onAnalyzed={onAnalyzed} />;
    }
    return <QAPanel detail={detail} loading={detailLoading} />;
  })();

  return (
    <div className="h-full flex">
      <SessionList
        records={combined}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={onNew}
        onChanged={onRecordChanged}
        onDraftMutate={onDraftMutate}
        onDraftDelete={onDraftDelete}
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
        interviewTitle={activeRecord?.title ?? null}
        width={widths.right}
      />
    </div>
  );
}

function hasStructuredQA(detail: InterviewRecordDetail): boolean {
  const a = detail.analysis as
    | undefined
    | null
    | { per_question?: unknown; qa_history?: unknown };
  if (!a || typeof a !== 'object') return false;
  return (
    (Array.isArray(a.per_question) && a.per_question.length > 0) ||
    (Array.isArray(a.qa_history) && a.qa_history.length > 0)
  );
}
