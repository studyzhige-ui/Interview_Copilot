import { useRef, useState } from 'react';
import {
  BookmarkCheck,
  BookmarkPlus,
  ChevronRight,
  FileText,
  MessageCircleQuestion,
  Pencil,
} from 'lucide-react';
import { EmptyState } from '@/components/ui/EmptyState';
import { Pill } from '@/components/ui/Pill';
import { editInterviewQA, saveQAToKnowledge, unsaveQAFromKnowledge } from '@/api/interview';
import { toast } from '@/store/uiStore';
import type {
  InterviewAnalysis,
  InterviewQA,
  InterviewRecordDetail,
  InterviewTranscriptStructure,
} from '@/types/api';
import { DebriefGuidanceControl } from './DebriefGuidanceControl';
import { InterviewOpportunityControl } from './InterviewOpportunityControl';

type Tab = 'report' | 'qa' | 'transcript';

interface Props {
  detail: InterviewRecordDetail | null;
  loading: boolean;
  reanalyzing?: boolean;
  onReanalyze?: (mode: 'report' | 'extract' | 'transcribe') => void;
  selectedQuestionIndexes?: number[];
  onToggleQuestion?: (index: number) => void;
}

function asAnalysis(detail: InterviewRecordDetail | null): InterviewAnalysis | null {
  if (!detail) return null;
  const a = detail.analysis as InterviewAnalysis | null | undefined;
  return a && typeof a === 'object' ? a : null;
}

/** Render an ISO timestamp from the API in the user's local timezone.
 *
 * The backend sends UTC ISO strings (e.g. ``2026-05-17T02:34:55``). The
 * previous code used ``slice(0,19).replace('T',' ')`` which kept the
 * UTC clock unchanged — visually wrong for any user outside UTC.
 * ``toLocaleString`` with ``zh-CN`` + the user's resolved timezone gives
 * a stable "YYYY/M/D HH:MM:SS" rendering.
 *
 * Invalid / missing input returns an empty string so the surrounding "·"
 * separator collapses to nothing instead of "Invalid Date".
 */
function formatLocal(iso: string | null | undefined): string {
  if (!iso) return '';
  // FastAPI emits naive UTC strings without a Z suffix. Force-mark UTC so
  // the Date constructor doesn't interpret it as local time on Windows /
  // Safari (which would shift the clock twice).
  const stamp = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z';
  const d = new Date(stamp);
  if (isNaN(d.getTime())) return iso.slice(0, 19);
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false,
  });
}

export function QAPanel({
  detail,
  loading,
  reanalyzing = false,
  onReanalyze,
  selectedQuestionIndexes = [],
  onToggleQuestion,
}: Props) {
  // Default to the report tab when content first lands; flip to QA only if the
  // user explicitly switches. This matches the design spec.
  const [tab, setTab] = useState<Tab>('report');
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
  const qa = detail.qa ?? [];

  return (
    <div className="flex-1 min-w-0 overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto">
        <div className="mb-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <h2 className="text-xl font-semibold text-stone-800">{detail.title || '未命名'}</h2>
            <DebriefGuidanceControl interviewId={detail.id} />
          </div>
          <div className="text-xs text-stone-500 mt-1">
            {formatLocal(detail.created_at)} · {detail.status}
            {detail.tag && (
              <span className="ml-2 inline-flex">
                <Pill tone="sand">{detail.tag}</Pill>
              </span>
            )}
          </div>
          <InterviewOpportunityControl
            key={`${detail.id}:${detail.job_opportunity_id ?? ''}`}
            interviewId={detail.id}
            initialJobOpportunityId={detail.job_opportunity_id}
          />
        </div>

        <ReportTabs tab={tab} onChange={setTab} hasTranscript={!!detail.transcript} />

        {tab === 'report' && (
          <ReportView
            analysis={analysis}
            transcript={detail.transcript}
            qaCount={qa.length}
            reanalyzing={reanalyzing}
            onReanalyze={onReanalyze}
          />
        )}
        {tab === 'qa' && (
          qa.length === 0
          ? <EmptyState icon={<FileText size={24} />} title="这条记录还没有结构化 QA" description="模型可能还在分析，或这条记录不输出 per_question 字段。" />
          : <div className="flex flex-col gap-4">
              {detail.transcript_quality && (
                <div className="rounded-xl border border-primary-100 bg-primary-50/70 px-4 py-3 text-sm text-stone-700">
                  <div className="font-medium text-stone-800">词级证据整理</div>
                  <div className="mt-1 leading-6">
                    候选人原回答覆盖 {Math.round(detail.transcript_quality.candidate_substantive_word_coverage * 100)}%
                    {' · '}问题覆盖 {Math.round(detail.transcript_quality.question_word_coverage * 100)}%
                    {' · '}隐藏 {Math.round(detail.transcript_quality.hidden_word_ratio * 100)}% 的明确停顿、杂音或紧邻重复词。
                    正文由原始词级证据重建，不是摘要或改写。
                  </div>
                </div>
              )}
              {qa.map((q) => (
                <QAItem
                  key={`${q.id}:${q.question}:${q.answer}:${q.saved_document_id ?? ''}`}
                  qa={q}
                  recordId={detail.id}
                  selected={selectedQuestionIndexes.includes(q.order_idx + 1)}
                  onToggleQuestion={onToggleQuestion}
                />
              ))}
            </div>
        )}
        {tab === 'transcript' && (
          detail.transcript
            ? (
                <TranscriptView
                  transcript={detail.transcript}
                  structure={detail.transcript_structure}
                />
              )
            : <EmptyState icon={<FileText size={24} />} title="暂无转录文本" description="该面试尚未完成语音转录。" />
        )}
      </div>
    </div>
  );
}

function ReportTabs({ tab, onChange, hasTranscript }: { tab: Tab; onChange: (t: Tab) => void; hasTranscript: boolean }) {
  const tabs: Array<{ k: Tab; l: string }> = [
    { k: 'report', l: '分析报告' },
    { k: 'qa', l: 'QA 对' },
  ];
  if (hasTranscript) tabs.push({ k: 'transcript', l: '原始转录' });

  const activeIdx = tabs.findIndex((t) => t.k === tab);
  const pct = 100 / tabs.length;

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
          left: `calc(${activeIdx * pct}% + 4px)`,
          width: `calc(${pct}% - 4px)`,
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

// ── Raw transcript view ─────────────────────────────────────────────────

interface SpeakerLine {
  speaker: string;
  text: string;
  side: 'interviewer' | 'candidate' | 'unknown';
}

function parseLine(
  line: string,
  roleBySpeaker: ReadonlyMap<string, SpeakerLine['side']>,
): SpeakerLine | null {
  // WhisperX/Pyannote ASR: `**[SPEAKER_01]**: text`
  const asrMatch = line.match(/^\*\*\[([^\]]+)\]\*\*:\s*(.*)$/);
  if (asrMatch) {
    const speaker = asrMatch[1];
    const semanticLabel = speaker.toLowerCase();
    const side = roleBySpeaker.get(speaker)
      ?? (semanticLabel.includes('interviewer')
        ? 'interviewer'
        : semanticLabel.includes('candidate')
          ? 'candidate'
          : 'unknown');
    return {
      speaker,
      text: asrMatch[2],
      side,
    };
  }
  // Mock composed transcript: `面试官: text` / `候选人: text`
  const mockMatch = line.match(/^(面试官|候选人|Interviewer|Candidate)\s*[:：]\s*(.*)$/i);
  if (mockMatch) {
    const role = mockMatch[1];
    const isInterviewer = role === '面试官' || role.toLowerCase() === 'interviewer';
    return {
      speaker: role,
      text: mockMatch[2],
      side: isInterviewer ? 'interviewer' : 'candidate',
    };
  }
  return null;
}

function transcriptSpeakerLabel(line: SpeakerLine): string {
  const roleLabel = line.side === 'interviewer'
    ? '面试官'
    : line.side === 'candidate'
      ? '候选人'
      : '角色未确认';
  const normalizedSpeaker = line.speaker.toLowerCase();
  if (
    normalizedSpeaker === '面试官'
    || normalizedSpeaker === '候选人'
    || normalizedSpeaker === 'interviewer'
    || normalizedSpeaker === 'candidate'
  ) {
    return roleLabel;
  }
  return `${roleLabel} · ${line.speaker}`;
}

function TranscriptView({
  transcript,
  structure,
}: {
  transcript: string;
  structure?: InterviewTranscriptStructure | null;
}) {
  const lines = transcript.split('\n').filter((l) => l.trim());
  const roleBySpeaker = new Map(
    (structure?.speaker_roles ?? []).map((entry) => [entry.speaker_id, entry.role]),
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-stone-500 mb-1">
        原始对话文稿（mock 来源为结构化 Q&A 拼接；upload 来源为 ASR + 声纹分离输出）
      </div>
      {lines.map((line, i) => {
        const parsed = parseLine(line, roleBySpeaker);
        if (parsed) {
          const colorCls =
            parsed.side === 'interviewer'
              ? 'bg-blue-100 text-blue-700'
              : parsed.side === 'candidate'
              ? 'bg-emerald-100 text-emerald-700'
              : 'bg-stone-100 text-stone-600';
          return (
            <div key={i} className="bg-white rounded-xl border border-stone-200 p-4 shadow-xs">
              <span
                className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full mr-2 ${colorCls}`}
              >
                {transcriptSpeakerLabel(parsed)}
              </span>
              <span className="text-sm text-stone-700 leading-[1.7]">{parsed.text}</span>
            </div>
          );
        }
        return (
          <div key={i} className="text-sm text-stone-500 leading-[1.7] px-1">
            {line}
          </div>
        );
      })}
    </div>
  );
}

// ── Report view (overall score + strengths/weaknesses + summary) ────────

function ReportView({
  analysis,
  transcript,
  qaCount,
  reanalyzing,
  onReanalyze,
}: {
  analysis: InterviewAnalysis | null;
  transcript: string | null;
  qaCount: number;
  reanalyzing: boolean;
  onReanalyze?: (mode: 'report' | 'extract' | 'transcribe') => void;
}) {
  const overall = analysis?.overall;
  const has = analysis && (overall || qaCount > 0);
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

  const score100 = typeof overall?.score === 'number' ? Math.round(overall.score * 10) : null;
  const summary = overall?.summary || '';
  const strengths = overall?.strengths ?? [];
  const weaknesses = overall?.weaknesses ?? [];
  const plan = (overall?.key_growth_areas ?? []).map((item) => {
    const area = item.area?.trim() ?? '';
    const nextStep = item.next_step?.trim() ?? '';
    return area && nextStep ? `${area}：${nextStep}` : area || nextStep;
  }).filter(Boolean);
  const phases = analysis?.phase_summary ?? [];
  const radar = Object.entries(analysis?.skill_radar ?? {});
  const legacyPartial = /生成失败|调用都失败/.test(summary);
  const generationStatus = analysis?.generation_status ?? (legacyPartial ? 'partial' : 'complete');
  const warnings = analysis?.generation_warnings ?? (legacyPartial ? [summary] : []);

  // We're a study companion, not a gatekeeper: do NOT render verdict / grade /
  // any pass-fail framing. Score is kept as a self-benchmark only.
  return (
    <div className="flex flex-col gap-4">
      {generationStatus !== 'complete' && (
        <div className="rounded-2xl border border-warning-200 bg-warning-50 p-4" role="alert">
          <div className="text-sm font-medium text-warning-800">这份复盘只生成了部分结果</div>
          <div className="mt-1 text-xs leading-relaxed text-stone-600">
            {warnings[0] || '逐题结果已保留，但综合报告或部分评分没有成功生成。'}
          </div>
          {onReanalyze && (
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={reanalyzing}
                onClick={() => onReanalyze('report')}
                className="rounded-lg bg-primary-600 px-3 py-2 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-60"
              >
                {reanalyzing ? '重新分析中…' : '重新生成报告'}
              </button>
              <button
                type="button"
                disabled={reanalyzing}
                onClick={() => onReanalyze('extract')}
                className="rounded-lg border border-warning-300 bg-white px-3 py-2 text-xs font-medium text-warning-800 hover:bg-warning-100 disabled:opacity-60"
              >
                QA 有错位？重新整理 QA 与报告
              </button>
              <button
                type="button"
                disabled={reanalyzing}
                onClick={() => onReanalyze('transcribe')}
                className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs font-medium text-stone-700 hover:bg-stone-50 disabled:opacity-60"
              >
                源转写混乱？从录音重新转写
              </button>
            </div>
          )}
        </div>
      )}
      <div className="grid grid-cols-[200px_1fr] gap-5 bg-white border border-stone-200 rounded-2xl p-6 shadow-xs">
        <div className="flex flex-col items-center justify-center bg-cream-50 rounded-xl p-5">
          <div className="text-xs text-stone-500 uppercase tracking-wider">本次表现</div>
          <div className={`${score100 === null ? 'text-2xl' : 'text-[52px]'} font-bold text-primary-600 leading-none mt-2`}>
            {score100 === null ? '未评分' : score100}
          </div>
          {score100 !== null && (
            <div className="text-xs text-stone-500 mt-1">/ 100 · 进步基准线</div>
          )}
        </div>
        <div className="flex flex-col gap-3 justify-center">
          {summary && (
            <div className="text-sm text-stone-600 leading-[1.7]">{summary}</div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <BulletList tone="success" title="做得不错的地方" items={strengths} />
        <BulletList tone="warn" title="下次可以更好的方向" items={weaknesses} />
      </div>

      {phases.length > 0 && (
        <div className="bg-white rounded-2xl border border-stone-200 p-6 shadow-xs">
          <div className="text-xs uppercase tracking-wider text-stone-500 mb-3">阶段表现</div>
          <div className="space-y-3">
            {phases.map((phase) => (
              <div key={phase.phase} className="rounded-xl bg-stone-50 px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-stone-800">{phase.phase_name}</span>
                  <span className="text-xs text-stone-400">{phase.question_count} 题</span>
                  <span className="ml-auto text-sm font-mono font-semibold text-primary-600">
                    {typeof phase.score === 'number' ? `${Math.round(phase.score * 10)}分` : '未评分'}
                  </span>
                </div>
                {phase.summary && (
                  <div className="text-sm text-stone-600 leading-[1.7] mt-1.5">{phase.summary}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {radar.length > 0 && (
        <div className="bg-white rounded-2xl border border-stone-200 p-6 shadow-xs">
          <div className="text-xs uppercase tracking-wider text-stone-500 mb-3">能力维度</div>
          <AbilityRadarChart values={radar} />
        </div>
      )}

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

function AbilityRadarChart({ values }: { values: Array<[string, number | null]> }) {
  const dimensions = values.slice(0, 8);
  const count = dimensions.length;
  const centerX = 180;
  const centerY = 145;
  const radius = 92;
  const pointAt = (index: number, scale: number) => {
    const angle = -Math.PI / 2 + (index * Math.PI * 2) / count;
    return {
      x: centerX + Math.cos(angle) * radius * scale,
      y: centerY + Math.sin(angle) * radius * scale,
    };
  };
  const polygon = (scale: number) => dimensions
    .map((_, index) => {
      const point = pointAt(index, scale);
      return `${point.x.toFixed(1)},${point.y.toFixed(1)}`;
    })
    .join(' ');
  const dataPolygon = dimensions
    .map(([, value], index) => {
      const point = pointAt(index, typeof value === 'number' ? Math.max(0, Math.min(10, value)) / 10 : 0);
      return `${point.x.toFixed(1)},${point.y.toFixed(1)}`;
    })
    .join(' ');
  const hasMeasuredValue = dimensions.some(([, value]) => typeof value === 'number');

  return (
    <div className="grid items-center gap-5 md:grid-cols-[minmax(300px,1fr)_220px]">
      <svg
        role="img"
        aria-label="能力雷达图"
        viewBox="0 0 360 300"
        className="mx-auto w-full max-w-[420px]"
      >
        {[0.2, 0.4, 0.6, 0.8, 1].map((scale) => (
          <polygon
            key={scale}
            points={polygon(scale)}
            fill="none"
            stroke={scale === 1 ? '#cbd5e1' : '#e7e5e4'}
            strokeWidth="1"
          />
        ))}
        {dimensions.map(([dimension], index) => {
          const axis = pointAt(index, 1);
          const label = pointAt(index, 1.28);
          const anchor = Math.abs(label.x - centerX) < 8 ? 'middle' : label.x > centerX ? 'start' : 'end';
          return (
            <g key={dimension}>
              <line x1={centerX} y1={centerY} x2={axis.x} y2={axis.y} stroke="#e7e5e4" strokeWidth="1" />
              <text x={label.x} y={label.y} textAnchor={anchor} dominantBaseline="middle" className="fill-stone-600 text-[11px]">
                {dimension}
              </text>
            </g>
          );
        })}
        {hasMeasuredValue && (
          <>
            <polygon points={dataPolygon} fill="rgba(59,130,246,0.18)" stroke="#3b82f6" strokeWidth="2" />
            {dimensions.map(([dimension, value], index) => {
              if (typeof value !== 'number') return null;
              const point = pointAt(index, Math.max(0, Math.min(10, value)) / 10);
              return <circle key={dimension} cx={point.x} cy={point.y} r="3.5" fill="#2563eb" />;
            })}
          </>
        )}
      </svg>
      <div className="space-y-2">
        {dimensions.map(([dimension, value]) => (
          <div key={dimension} className="flex items-center justify-between rounded-lg bg-stone-50 px-3 py-2 text-sm">
            <span className="text-stone-700">{dimension}</span>
            <span className="font-mono text-stone-500">
              {typeof value === 'number' ? `${Math.round(value * 10)}分` : '未考察'}
            </span>
          </div>
        ))}
        <p className="text-[11px] leading-relaxed text-stone-400">仅展示本次问答中有直接证据的维度；“未考察”不等于能力不足。</p>
      </div>
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

function QAItem({
  qa,
  recordId,
  selected,
  onToggleQuestion,
}: {
  qa: InterviewQA;
  recordId: string;
  selected: boolean;
  onToggleQuestion?: (index: number) => void;
}) {
  const [openS, setOpenS] = useState(false);
  const [editingQ, setEditingQ] = useState(false);
  const [editingA, setEditingA] = useState(false);
  const [question, setQuestion] = useState(qa.question);
  const [answer, setAnswer] = useState(qa.answer);
  const [savedDocId, setSavedDocId] = useState<string | null>(qa.saved_document_id ?? null);
  const [savingKb, setSavingKb] = useState(false);
  const savedQuestion = useRef(qa.question);
  const savedAnswer = useRef(qa.answer);

  const saveQ = async () => {
    setEditingQ(false);
    if (question === savedQuestion.current) return;
    try {
      await editInterviewQA(recordId, qa.id, { question });
      savedQuestion.current = question;
      toast.success('问题已保存');
    } catch { toast.error('保存失败'); setQuestion(savedQuestion.current); }
  };
  const saveA = async () => {
    setEditingA(false);
    if (answer === savedAnswer.current) return;
    try {
      await editInterviewQA(recordId, qa.id, { answer });
      savedAnswer.current = answer;
      toast.success('答案已保存');
    } catch { toast.error('保存失败'); setAnswer(savedAnswer.current); }
  };

  const toggleKb = async () => {
    setSavingKb(true);
    try {
      if (savedDocId) {
        await unsaveQAFromKnowledge(recordId, qa.id);
        setSavedDocId(null);
        toast.success('已从知识库移除');
      } else {
        const r = await saveQAToKnowledge(recordId, qa.id);
        setSavedDocId(r.saved_document_id);
        toast.success('已保存到知识库');
      }
    } catch {
      toast.error(savedDocId ? '移除失败' : '保存到知识库失败');
    } finally {
      setSavingKb(false);
    }
  };

  const hasImproved = !!qa.improved_answer && qa.improved_answer.trim().length > 0;
  const score = qa.score ?? undefined;
  const phaseLabel = qa.phase_label || qa.phase;

  return (
    <article className="bg-white rounded-2xl p-5 border border-stone-200 shadow-xs">
      {/* Q-row */}
      <div className="flex items-center gap-2 mb-2">
        <Pill tone="primary">Q{qa.order_idx + 1}</Pill>
        {qa.is_follow_up && <Pill tone="sand">追问</Pill>}
        <span className="text-xs text-stone-500">{phaseLabel}</span>
        {qa.source_provenance?.manual_override && <Pill tone="sand">用户已编辑</Pill>}
        <span className={`ml-auto text-sm font-mono font-semibold ${scoreColor(score)}`}>
          {typeof score === 'number'
            ? `${Math.round(score * 10)}分`
            : qa.critique
              ? '未评分'  /* grading was attempted but the model call failed (ANA-6) */
              : ''}
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
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) e.currentTarget.blur();
          }}
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
        {qa.answer_audio_url && (
          // MOCK-7: voice answers keep their original clip — presigned URL
          // minted by the backend per detail read.
          <audio
            controls
            preload="none"
            src={qa.answer_audio_url}
            className="h-7 max-w-[220px]"
          />
        )}
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
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) e.currentTarget.blur();
          }}
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

      {qa.source_provenance && (
        <details className="mt-3 text-xs text-stone-500">
          <summary className="cursor-pointer select-none hover:text-stone-700">
            查看原词整理记录
          </summary>
          <div className="mt-2 rounded-lg bg-stone-50 px-3 py-2 leading-5">
            {qa.source_provenance.manual_override
              ? '当前正文包含用户明确编辑；下列词级引用保留编辑前来源。'
              : `回答引用 ${qa.source_provenance.answer_word_ids.length} 个原始词。`}
            {' '}
            保留 {qa.source_provenance.crossing_utterance_ids.length} 次交叉插话，
            隐藏 {qa.source_provenance.hidden_words.length} 个可审计的非语义词；
            结构置信度 {Math.round(qa.source_provenance.confidence * 100)}%。
          </div>
        </details>
      )}

      {qa.critique && (
        <div className="mt-3.5 text-sm text-stone-600 leading-[1.7]">
          <span className="text-warning-700 font-semibold">回顾：</span>
          {qa.critique}
        </div>
      )}

      {onToggleQuestion && (
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={() => onToggleQuestion(qa.order_idx + 1)}
            className={[
              'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors',
              selected
                ? 'bg-primary-100 text-primary-800 hover:bg-primary-200'
                : 'bg-stone-100 text-stone-600 hover:bg-primary-50 hover:text-primary-700',
            ].join(' ')}
          >
            <MessageCircleQuestion size={14} />
            {selected ? '已加入追问' : '追问本题'}
          </button>
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
          <>
            <div className="mt-3 p-4 rounded-xl bg-primary-50 border border-primary-100 text-stone-800 text-sm leading-[1.75] whitespace-pre-wrap">
              {hasImproved ? qa.improved_answer : (
                <span className="text-stone-500 italic">LLM 优化回答尚未生成</span>
              )}
            </div>
            {hasImproved && (
              <button
                type="button"
                onClick={toggleKb}
                disabled={savingKb}
                className={[
                  'mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[13px] transition-colors',
                  savedDocId
                    ? 'bg-success-50 text-success-700 hover:bg-success-100'
                    : 'bg-primary-50 text-primary-700 hover:bg-primary-100',
                  savingKb ? 'opacity-60 cursor-wait' : '',
                ].join(' ')}
              >
                {savedDocId ? <BookmarkCheck size={14} /> : <BookmarkPlus size={14} />}
                {savedDocId ? '已保存到知识库 · 点击移除' : '保存到知识库'}
              </button>
            )}
          </>
        )}
      </div>
    </article>
  );
}
