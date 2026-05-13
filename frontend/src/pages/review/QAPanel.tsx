import { useEffect, useState } from 'react';
import { ChevronRight, FileText, Pencil } from 'lucide-react';
import { EmptyState } from '@/components/ui/EmptyState';
import { Pill } from '@/components/ui/Pill';
import { editInterviewQA } from '@/api/interview';
import { toast } from '@/store/uiStore';
import type {
  InterviewAnalysis,
  InterviewQA,
  InterviewRecordDetail,
} from '@/types/api';

type Tab = 'report' | 'qa';

interface Props {
  detail: InterviewRecordDetail | null;
  loading: boolean;
}

function asAnalysis(detail: InterviewRecordDetail | null): InterviewAnalysis | null {
  if (!detail) return null;
  const a = detail.analysis as InterviewAnalysis | null | undefined;
  return a && typeof a === 'object' ? a : null;
}

function extractQA(analysis: InterviewAnalysis | null): InterviewQA[] {
  if (!analysis) return [];
  if (Array.isArray(analysis.per_question) && analysis.per_question.length > 0) {
    return analysis.per_question.map((q, i) => ({
      index: typeof q.index === 'number' ? q.index : i + 1,
      phase: q.phase,
      question: q.question ?? '',
      answer: q.answer ?? '',
      score: typeof q.score === 'number' ? q.score : undefined,
      critique: q.critique,
      improved_answer: q.improved_answer,
      tags: Array.isArray(q.tags) ? q.tags : undefined,
    }));
  }
  if (Array.isArray(analysis.qa_history)) {
    return analysis.qa_history.map((h, i) => ({
      index: i + 1,
      phase: h.phase_id,
      question: h.question ?? '',
      answer: h.answer ?? '',
    }));
  }
  return [];
}

export function QAPanel({ detail, loading }: Props) {
  // Default to the report tab when content first lands; flip to QA only if the
  // user explicitly switches. This matches the design spec.
  const [tab, setTab] = useState<Tab>('report');
  useEffect(() => {
    setTab('report');
  }, [detail?.id]);

  if (loading) {
    return (
      <div className="flex-1 min-w-0 overflow-y-auto p-8">
        <div className="text-sm text-stone-500">载入中...</div>
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="flex-1 min-w-0 overflow-y-auto">
        <EmptyState
          icon={<FileText size={32} />}
          title="选择一条面试记录"
          description="左侧列表点击任意条目查看复盘内容。如果还没有记录，点 + 新建一条。"
        />
      </div>
    );
  }

  const analysis = asAnalysis(detail);
  const qa = extractQA(analysis);

  return (
    <div className="flex-1 min-w-0 overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto">
        <div className="mb-4">
          <h2 className="text-xl font-semibold text-stone-800">{detail.title || '未命名'}</h2>
          <div className="text-xs text-stone-500 mt-1">
            {detail.created_at?.slice(0, 19).replace('T', ' ')} · {detail.status}
            {detail.tag && (
              <span className="ml-2 inline-flex">
                <Pill tone="sand">{detail.tag}</Pill>
              </span>
            )}
          </div>
        </div>

        <ReportTabs tab={tab} onChange={setTab} />

        {tab === 'report'
          ? <ReportView analysis={analysis} transcript={detail.transcript} />
          : qa.length === 0
          ? <EmptyState icon={<FileText size={24} />} title="这条记录还没有结构化 QA" description="模型可能还在分析，或这条记录不输出 per_question 字段。" />
          : <div className="flex flex-col gap-4">
              {qa.map((q, i) => (
                <QAItem
                  key={i}
                  qa={q}
                  recordId={detail.id}
                />
              ))}
            </div>
        }
      </div>
    </div>
  );
}

function ReportTabs({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  const tabs: Array<{ k: Tab; l: string }> = [
    { k: 'report', l: '分析报告' },
    { k: 'qa', l: 'QA 对' },
  ];
  return (
    <div
      className="relative inline-flex p-1 mb-5 rounded-full border border-stone-200 shadow-xs"
      style={{
        background: 'rgba(255,255,255,0.62)',
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
      }}
    >
      <div
        className="absolute top-1 bottom-1 bg-white rounded-full shadow-xs transition-[left] duration-[280ms]"
        style={{
          left: tab === 'report' ? 4 : 'calc(50% + 0px)',
          width: 'calc(50% - 4px)',
          transitionTimingFunction: 'var(--ease-soft)',
        }}
      />
      {tabs.map((t) => (
        <button
          key={t.k}
          onClick={() => onChange(t.k)}
          className={[
            'relative z-10 px-[22px] py-[7px] text-[13px] font-medium',
            tab === t.k ? 'text-primary-700' : 'text-stone-600',
          ].join(' ')}
        >
          {t.l}
        </button>
      ))}
    </div>
  );
}

// ── Report view (overall score + strengths/weaknesses + feedback) ────────

function ReportView({
  analysis,
  transcript,
}: {
  analysis: InterviewAnalysis | null;
  transcript: string | null;
}) {
  const overall = analysis?.overall;
  const has = analysis && (overall || (analysis.per_question && analysis.per_question.length > 0));
  if (!has) {
    if (transcript) {
      return (
        <div className="bg-white rounded-2xl border border-stone-200 p-5 shadow-xs">
          <div className="text-xs text-stone-500 mb-2">原始转录</div>
          <div className="text-sm text-stone-700 leading-relaxed whitespace-pre-wrap font-mono">
            {transcript}
          </div>
        </div>
      );
    }
    return (
      <EmptyState
        icon={<FileText size={24} />}
        title="这条记录还没有分析报告"
        description="模型可能仍在生成。完成后请刷新本页查看。"
      />
    );
  }

  const score10 = typeof overall?.score === 'number' ? overall.score : 0;
  const score100 = Math.round(score10 * 10);
  const feedback = overall?.feedback ?? '';
  const strengths = overall?.strengths ?? [];
  const weaknesses = overall?.weaknesses ?? [];
  const plan = overall?.improvement_plan ?? [];

  // We're a study companion, not a gatekeeper: do NOT render verdict / grade /
  // any pass-fail framing. Score is kept as a self-benchmark only.
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-[200px_1fr] gap-5 bg-white border border-stone-200 rounded-2xl p-6 shadow-xs">
        <div className="flex flex-col items-center justify-center bg-cream-50 rounded-xl p-5">
          <div className="text-xs text-stone-500 uppercase tracking-wider">本次表现</div>
          <div className="text-[52px] font-bold text-primary-600 leading-none mt-2">
            {score100}
          </div>
          <div className="text-xs text-stone-500 mt-1">/ 100 · 进步基准线</div>
        </div>
        <div className="flex flex-col gap-3 justify-center">
          {feedback && (
            <div className="text-sm text-stone-600 leading-[1.7]">{feedback}</div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <BulletList tone="success" title="做得不错的地方" items={strengths} />
        <BulletList tone="warn" title="下次可以更好的方向" items={weaknesses} />
      </div>

      {plan.length > 0 && (
        <div className="bg-white rounded-2xl border border-stone-200 p-6 shadow-xs">
          <div className="text-xs uppercase tracking-wider text-stone-500 mb-2.5">下一步行动</div>
          <ul className="space-y-2">
            {plan.map((p, i) => (
              <li key={i} className="text-sm text-stone-700 leading-[1.7]">
                <span className="text-primary-500 mr-2">→</span>
                {p}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function BulletList({
  tone,
  title,
  items,
}: {
  tone: 'success' | 'warn';
  title: string;
  items: string[];
}) {
  return (
    <div className="bg-white rounded-2xl border border-stone-200 p-5 shadow-xs">
      <div className={`text-sm font-semibold mb-2.5 ${tone === 'success' ? 'text-success-700' : 'text-warning-700'}`}>
        {title}
      </div>
      {items.length === 0 ? (
        <div className="text-sm text-stone-400">暂无内容</div>
      ) : (
        <ul className="space-y-2">
          {items.map((it, i) => (
            <li key={i} className="text-sm text-stone-700 leading-[1.7]">
              <span className={tone === 'success' ? 'text-success-500 mr-2' : 'text-warning-500 mr-2'}>·</span>
              {it}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── QAItem (per spec) ────────────────────────────────────────────────────

function scoreColor(score: number | undefined): string {
  if (typeof score !== 'number') return 'text-stone-400';
  const s100 = score * 10;
  if (s100 >= 80) return 'text-success-700';
  if (s100 >= 60) return 'text-warning-700';
  return 'text-danger-500';
}

function QAItem({ qa, recordId }: { qa: InterviewQA; recordId: string }) {
  const [openS, setOpenS] = useState(false);
  const [editingQ, setEditingQ] = useState(false);
  const [editingA, setEditingA] = useState(false);
  const [question, setQuestion] = useState(qa.question);
  const [answer, setAnswer] = useState(qa.answer);

  const saveQ = async () => {
    setEditingQ(false);
    if (question === qa.question) return;
    try {
      await editInterviewQA(recordId, qa.index - 1, { question });
      toast.success('问题已保存');
    } catch { toast.error('保存失败'); setQuestion(qa.question); }
  };
  const saveA = async () => {
    setEditingA(false);
    if (answer === qa.answer) return;
    try {
      await editInterviewQA(recordId, qa.index - 1, { answer });
      toast.success('答案已保存');
    } catch { toast.error('保存失败'); setAnswer(qa.answer); }
  };

  const hasImproved = !!qa.improved_answer && qa.improved_answer.trim().length > 0;

  return (
    <article className="bg-white rounded-2xl p-5 border border-stone-200 shadow-xs">
      {/* Q-row */}
      <div className="flex items-center gap-2 mb-2">
        <Pill tone="primary">Q{qa.index}</Pill>
        <span className="text-xs text-stone-500">面试官</span>
        {qa.tags && qa.tags.slice(0, 3).map((t, i) => (
          <Pill key={i} tone="sand">{t}</Pill>
        ))}
        <span className={`ml-auto text-sm font-mono font-semibold ${scoreColor(qa.score)}`}>
          {typeof qa.score === 'number' ? `${Math.round(qa.score * 10)}分` : ''}
        </span>
        <button
          onClick={() => setEditingQ((v) => !v)}
          title="编辑问题"
          className="w-6 h-6 rounded text-stone-400 hover:text-stone-600 hover:bg-stone-100 flex items-center justify-center"
        >
          <Pencil size={12} />
        </button>
      </div>
      {editingQ ? (
        <textarea
          autoFocus
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onBlur={saveQ}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) saveQ(); }}
          rows={2}
          className="w-full p-3 text-base font-medium bg-stone-50 border border-primary-200 rounded-lg outline-none resize-y mb-4"
        />
      ) : (
        <div
          onDoubleClick={() => setEditingQ(true)}
          className="text-base font-medium text-stone-800 leading-[1.6] mb-4 cursor-text"
        >
          {question}
        </div>
      )}

      {/* A-row */}
      <div className="flex items-center gap-2 mb-2">
        <Pill tone="success">A</Pill>
        <span className="text-xs text-stone-500">你的回答 · 可编辑</span>
        <button
          onClick={() => setEditingA((v) => !v)}
          title="编辑回答"
          className="ml-auto w-6 h-6 rounded text-stone-400 hover:text-stone-600 hover:bg-stone-100 flex items-center justify-center"
        >
          <Pencil size={12} />
        </button>
      </div>
      {editingA ? (
        <textarea
          autoFocus
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onBlur={saveA}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) saveA(); }}
          rows={4}
          className="w-full p-3.5 text-[15px] font-mono bg-stone-50 border border-primary-200 rounded-lg outline-none resize-y leading-[1.7]"
        />
      ) : (
        <div
          onDoubleClick={() => setEditingA(true)}
          className="text-[15px] font-mono text-stone-700 leading-[1.7] bg-stone-50 p-3.5 rounded-lg cursor-text whitespace-pre-wrap"
        >
          {answer || <span className="text-stone-400 font-sans">（未作答）</span>}
        </div>
      )}

      {qa.critique && (
        <div className="mt-3.5 text-sm text-stone-600 leading-[1.7]">
          <span className="text-warning-700 font-semibold">回顾：</span>
          {qa.critique}
        </div>
      )}

      {/* Collapsible "优化回答" */}
      <div className="mt-4 border-t border-stone-100 pt-3.5">
        <button
          onClick={() => setOpenS((v) => !v)}
          className="flex items-center gap-2 w-full text-left text-sm font-medium text-primary-700"
        >
          <ChevronRight
            size={15}
            className="transition-transform duration-[180ms]"
            style={{ transform: openS ? 'rotate(90deg)' : 'rotate(0deg)' }}
          />
          <span>优化回答</span>
          {!openS && (
            <span className="text-xs text-stone-400 font-normal">· 点击展开</span>
          )}
        </button>
        {openS && (
          <div className="mt-3 p-4 rounded-xl bg-primary-50 border border-primary-100 text-stone-800 text-sm leading-[1.75] whitespace-pre-wrap">
            {hasImproved ? qa.improved_answer : (
              <span className="text-stone-500 italic">LLM 优化回答尚未生成</span>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
