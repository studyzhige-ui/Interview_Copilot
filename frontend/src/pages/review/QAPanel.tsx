import { useRef, useState } from 'react';
import {
  BookmarkCheck,
  BookmarkPlus,
  ChevronRight,
  FileText,
  MessageCircleQuestion,
  Pencil,
  Sparkles,
  AlertTriangle,
  Copy,
  Check,
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

function formatLocal(iso: string | null | undefined): string {
  if (!iso) return '';
  const stamp = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z';
  const d = new Date(stamp);
  if (isNaN(d.getTime())) return iso.slice(0, 19);
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
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
  const [tab, setTab] = useState<Tab>('report');

  if (loading) {
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
      <div className="flex-1 min-w-0 overflow-y-auto p-8">
        <EmptyState
          icon={<Sparkles size={32} />}
          title="选择或新建一条面试记录"
          description="点击左侧列表查看过往复盘报告，或点击「新建」上传录音与简历开启智能诊断。"
        />
      </div>
    );
  }

  const analysis = asAnalysis(detail);
  const qa = detail.qa ?? [];

  return (
    <div className="flex-1 min-w-0 overflow-y-auto p-4 md:p-8">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Header Title & Actions */}
        <div className="bg-white/80 backdrop-blur-md rounded-3xl border border-slate-200/80 p-6 shadow-xs flex flex-col gap-3">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                {detail.tag && <Pill tone="sparkle">{detail.tag}</Pill>}
                <span className="text-xs text-slate-400 font-mono">
                  {formatLocal(detail.created_at)}
                </span>
              </div>
              <h2 className="text-xl md:text-2xl font-bold text-slate-900 tracking-tight">
                {detail.title || '未命名面试'}
              </h2>
            </div>
            <DebriefGuidanceControl interviewId={detail.id} />
          </div>

          <InterviewOpportunityControl
            key={`${detail.id}:${detail.job_opportunity_id ?? ''}`}
            interviewId={detail.id}
            initialJobOpportunityId={detail.job_opportunity_id}
          />
        </div>

        {/* Gemini Segmented Tab Bar */}
        <ReportTabs tab={tab} onChange={setTab} hasTranscript={!!detail.transcript} />

        {/* Tab 1: Comprehensive Diagnosis Report */}
        {tab === 'report' && (
          <ReportView
            analysis={analysis}
            transcript={detail.transcript}
            qaCount={qa.length}
            reanalyzing={reanalyzing}
            onReanalyze={onReanalyze}
          />
        )}

        {/* Tab 2: Question-by-Question STAR Breakdown */}
        {tab === 'qa' && (
          qa.length === 0 ? (
            <EmptyState
              icon={<FileText size={28} />}
              title="暂无结构化 QA 对"
              description="模型可能还在分析中，或者本场面试未包含问答拆解。"
            />
          ) : (
            <div className="space-y-4">
              {detail.transcript_quality && (
                <div className="rounded-2xl border border-blue-100 bg-blue-50/70 p-4 text-xs text-slate-700 leading-relaxed">
                  <div className="font-semibold text-blue-900 flex items-center gap-1.5 mb-1">
                    <Sparkles size={14} className="text-blue-600" />
                    <span>词级原声证据整理</span>
                  </div>
                  <div>
                    候选人原回答覆盖率 {Math.round(detail.transcript_quality.candidate_substantive_word_coverage * 100)}%
                    {' · '}问题覆盖率 {Math.round(detail.transcript_quality.question_word_coverage * 100)}%
                    {' · '}过滤 {Math.round(detail.transcript_quality.hidden_word_ratio * 100)}% 语气停顿与杂音。正文严格基于原声事实重建。
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
          )
        )}

        {/* Tab 3: Full Time-synced Transcript */}
        {tab === 'transcript' && (
          detail.transcript ? (
            <TranscriptView
              transcript={detail.transcript}
              structure={detail.transcript_structure}
            />
          ) : (
            <EmptyState
              icon={<FileText size={28} />}
              title="暂无原始逐字稿"
              description="该面试录音尚未完成语音转录。"
            />
          )
        )}
      </div>
    </div>
  );
}

function ReportTabs({
  tab,
  onChange,
  hasTranscript,
}: {
  tab: Tab;
  onChange: (t: Tab) => void;
  hasTranscript: boolean;
}) {
  const tabs: Array<{ k: Tab; l: string }> = [
    { k: 'report', l: '分析报告' },
    { k: 'qa', l: 'QA 对' },
  ];
  if (hasTranscript) tabs.push({ k: 'transcript', l: '原始转录' });

  return (
    <div className="inline-flex p-1 rounded-full bg-slate-100/90 border border-slate-200 shadow-inner">
      {tabs.map((t) => (
        <button
          key={t.k}
          type="button"
          onClick={() => onChange(t.k)}
          className={`px-5 py-2 text-xs md:text-sm font-semibold rounded-full transition-all duration-200 cursor-pointer ${
            tab === t.k
              ? 'bg-white text-blue-700 shadow-sm'
              : 'text-slate-600 hover:text-slate-900'
          }`}
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
    return { speaker, text: asrMatch[2], side };
  }
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
    <div className="space-y-3">
      <div className="text-xs text-slate-500 mb-2">
        原始语音识别与说话人分离文稿（已按时间戳对齐）：
      </div>
      {lines.map((line, i) => {
        const parsed = parseLine(line, roleBySpeaker);
        if (parsed) {
          const isInterviewer = parsed.side === 'interviewer';
          return (
            <div
              key={i}
              className={`rounded-2xl p-4 border transition-all ${
                isInterviewer
                  ? 'bg-blue-50/40 border-blue-100 text-slate-800'
                  : 'bg-emerald-50/30 border-emerald-100 text-slate-800'
              }`}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <span
                  className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${
                    isInterviewer
                      ? 'bg-blue-100 text-blue-700'
                      : 'bg-emerald-100 text-emerald-700'
                  }`}
                >
                  {transcriptSpeakerLabel(parsed)}
                </span>
              </div>
              <p className="text-sm leading-relaxed whitespace-pre-wrap">{parsed.text}</p>
            </div>
          );
        }
        return (
          <div key={i} className="text-xs text-slate-500 leading-relaxed px-2">
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
        <div className="bg-white rounded-3xl border border-slate-200 p-6 shadow-xs">
          <div className="text-xs font-semibold text-slate-500 mb-2">原始转录文稿</div>
          <div className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap font-mono">
            {transcript}
          </div>
        </div>
      );
    }
    return (
      <EmptyState
        icon={<Sparkles size={28} />}
        title="分析报告生成中或暂无内容"
        description="系统仍在处理，完成后将展示完整的诊断指标。"
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

  return (
    <div className="space-y-5">
      {/* Partial Generation Alert */}
      {generationStatus !== 'complete' && (
        <div className="rounded-3xl border border-amber-200 bg-amber-50/80 p-5 shadow-xs" role="alert">
          <div className="text-sm font-bold text-amber-900 flex items-center gap-2">
            <AlertTriangle size={16} className="text-amber-600" />
            <span>这份复盘只生成了部分结果</span>
          </div>
          <p className="mt-1 text-xs text-slate-600 leading-relaxed">
            {warnings[0] || '逐题结果已成功保留，但综合雷达图或部分评分未能生成完整。'}
          </p>
          {onReanalyze && (
            <div className="mt-4 flex flex-wrap gap-2.5">
              <button
                type="button"
                disabled={reanalyzing}
                onClick={() => onReanalyze('report')}
                className="px-3.5 py-1.5 rounded-full bg-blue-600 text-white text-xs font-semibold hover:bg-blue-700 transition-all shadow-xs disabled:opacity-50"
              >
                {reanalyzing ? '重新分析中…' : '重新生成报告'}
              </button>
              <button
                type="button"
                disabled={reanalyzing}
                onClick={() => onReanalyze('extract')}
                className="px-3.5 py-1.5 rounded-full border border-amber-300 bg-white text-amber-800 text-xs font-semibold hover:bg-amber-50 transition-all disabled:opacity-50"
              >
                QA 有错位？重新整理 QA 与报告
              </button>
              <button
                type="button"
                disabled={reanalyzing}
                onClick={() => onReanalyze('transcribe')}
                className="px-3.5 py-1.5 rounded-full border border-slate-300 bg-white text-slate-700 text-xs font-semibold hover:bg-slate-50 transition-all disabled:opacity-50"
              >
                源转写混乱？从录音重新转写
              </button>
            </div>
          )}
        </div>
      )}

      {/* Hero Score & Executive Summary Card */}
      <div className="grid grid-cols-1 md:grid-cols-[220px_1fr] gap-6 bg-white rounded-3xl border border-slate-200/90 p-6 md:p-8 shadow-xs">
        <div className="flex flex-col items-center justify-center bg-gradient-to-b from-blue-50/70 via-indigo-50/40 to-white rounded-2xl p-6 border border-blue-100/80 text-center">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
            综合表现指数
          </span>
          <div className="text-5xl font-extrabold text-blue-600 leading-none my-3 tracking-tight">
            {score100 === null ? '待评' : score100}
          </div>
          {score100 !== null && (
            <span className="text-[11.5px] font-medium text-slate-400">/ 100 · 评估基准分</span>
          )}
        </div>

        <div className="flex flex-col justify-center gap-2.5">
          <div className="text-xs font-bold text-slate-400 uppercase tracking-wider">
            AI 综合诊断结论
          </div>
          <div className="text-sm md:text-[15px] text-slate-700 leading-relaxed">
            {summary || '已根据面试问答深度完成综合诊断与评分。'}
          </div>
        </div>
      </div>

      {/* Strengths and Next Steps Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <BulletList tone="success" title="✨ 表现亮点与核心优势" items={strengths} />
        <BulletList tone="warn" title="💡 下次可重点突破的方向" items={weaknesses} />
      </div>

      {/* Phase Summaries */}
      {phases.length > 0 && (
        <div className="bg-white rounded-3xl border border-slate-200/90 p-6 shadow-xs">
          <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-4">
            分阶段面试表现
          </div>
          <div className="space-y-3">
            {phases.map((phase) => (
              <div key={phase.phase} className="rounded-2xl bg-slate-50/80 p-4 border border-slate-100">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-bold text-slate-800">{phase.phase_name}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-400">{phase.question_count} 题</span>
                    <span className="text-sm font-mono font-bold text-blue-600">
                      {typeof phase.score === 'number' ? `${Math.round(phase.score * 10)}分` : '未评分'}
                    </span>
                  </div>
                </div>
                {phase.summary && (
                  <p className="text-xs text-slate-600 mt-2 leading-relaxed">{phase.summary}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Ability Radar */}
      {radar.length > 0 && (
        <div className="bg-white rounded-3xl border border-slate-200/90 p-6 shadow-xs">
          <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-4">
            能力维度与考核雷达
          </div>
          <AbilityRadarChart values={radar} />
        </div>
      )}

      {/* Next Growth Action Plan */}
      {plan.length > 0 && (
        <div className="bg-white rounded-3xl border border-slate-200/90 p-6 shadow-xs">
          <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">
            🎯 下一步针对性提分计划
          </div>
          <ul className="space-y-2.5">
            {plan.map((p, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-slate-700 leading-relaxed">
                <span className="text-blue-600 font-bold mt-0.5">→</span>
                <span>{p}</span>
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
    <div className="grid items-center gap-6 md:grid-cols-[minmax(300px,1fr)_240px]">
      <svg role="img" aria-label="能力雷达图" viewBox="0 0 360 300" className="mx-auto w-full max-w-[400px]">
        {[0.2, 0.4, 0.6, 0.8, 1].map((scale) => (
          <polygon
            key={scale}
            points={polygon(scale)}
            fill="none"
            stroke={scale === 1 ? '#cbd5e1' : '#e2e8f0'}
            strokeWidth="1"
          />
        ))}
        {dimensions.map(([dimension], index) => {
          const axis = pointAt(index, 1);
          const label = pointAt(index, 1.28);
          const anchor = Math.abs(label.x - centerX) < 8 ? 'middle' : label.x > centerX ? 'start' : 'end';
          return (
            <g key={dimension}>
              <line x1={centerX} y1={centerY} x2={axis.x} y2={axis.y} stroke="#e2e8f0" strokeWidth="1" />
              <text x={label.x} y={label.y} textAnchor={anchor} dominantBaseline="middle" className="fill-slate-600 text-[11px] font-medium">
                {dimension}
              </text>
            </g>
          );
        })}
        {hasMeasuredValue && (
          <>
            <polygon points={dataPolygon} fill="rgba(66,133,244,0.18)" stroke="#2563eb" strokeWidth="2.5" />
            {dimensions.map(([dimension, value], index) => {
              if (typeof value !== 'number') return null;
              const point = pointAt(index, Math.max(0, Math.min(10, value)) / 10);
              return <circle key={dimension} cx={point.x} cy={point.y} r="4" fill="#1d4ed8" />;
            })}
          </>
        )}
      </svg>

      <div className="space-y-2">
        {dimensions.map(([dimension, value]) => (
          <div key={dimension} className="flex items-center justify-between rounded-xl bg-slate-50 px-3.5 py-2 text-xs font-medium">
            <span className="text-slate-700">{dimension}</span>
            <span className="font-mono font-bold text-blue-600">
              {typeof value === 'number' ? `${Math.round(value * 10)}分` : '未考察'}
            </span>
          </div>
        ))}
        <p className="text-[11px] text-slate-400 pt-1 leading-normal">
          * 仅展示本次问答中有直接证据的维度；“未考察”不代表能力缺失。
        </p>
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
    <div className="bg-white rounded-3xl border border-slate-200/90 p-6 shadow-xs">
      <div className={`text-sm font-bold mb-3 ${tone === 'success' ? 'text-emerald-700' : 'text-amber-800'}`}>
        {title}
      </div>
      {items.length === 0 ? (
        <div className="text-xs text-slate-400">暂无具体归纳</div>
      ) : (
        <ul className="space-y-2.5">
          {items.map((it, i) => (
            <li key={i} className="flex items-start gap-2.5 text-sm text-slate-700 leading-relaxed">
              <span className={`font-bold text-base leading-none ${tone === 'success' ? 'text-emerald-500' : 'text-amber-500'}`}>•</span>
              <span>{it}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── QAItem Component ─────────────────────────────────────────────────────

function scoreColor(score: number | undefined): string {
  if (typeof score !== 'number') return 'text-slate-400';
  const s100 = score * 10;
  if (s100 >= 80) return 'text-emerald-600';
  if (s100 >= 60) return 'text-amber-600';
  return 'text-red-500';
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
  const [copied, setCopied] = useState(false);
  const savedQuestion = useRef(qa.question);
  const savedAnswer = useRef(qa.answer);

  const saveQ = async () => {
    setEditingQ(false);
    if (question === savedQuestion.current) return;
    try {
      await editInterviewQA(recordId, qa.id, { question });
      savedQuestion.current = question;
      toast.success('问题已保存');
    } catch {
      toast.error('保存失败');
      setQuestion(savedQuestion.current);
    }
  };

  const saveA = async () => {
    setEditingA(false);
    if (answer === savedAnswer.current) return;
    try {
      await editInterviewQA(recordId, qa.id, { answer });
      savedAnswer.current = answer;
      toast.success('答案已保存');
    } catch {
      toast.error('保存失败');
      setAnswer(savedAnswer.current);
    }
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

  const handleCopyImproved = () => {
    if (!qa.improved_answer) return;
    navigator.clipboard.writeText(qa.improved_answer);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const hasImproved = !!qa.improved_answer && qa.improved_answer.trim().length > 0;
  const score = qa.score ?? undefined;
  const phaseLabel = qa.phase_label || qa.phase;

  return (
    <article className="bg-white rounded-3xl p-6 border border-slate-200/90 shadow-xs hover:border-slate-300 transition-all">
      {/* Question Header */}
      <div className="flex items-center gap-2.5 mb-3 flex-wrap">
        <Pill tone="primary">Q{qa.order_idx + 1}</Pill>
        {qa.is_follow_up && <Pill tone="warn">追问</Pill>}
        {phaseLabel && <span className="text-xs text-slate-500 font-medium">{phaseLabel}</span>}
        {qa.source_provenance?.manual_override && <Pill tone="sand">用户已编辑</Pill>}

        <div className="ml-auto flex items-center gap-3">
          <span className={`text-sm font-mono font-bold ${scoreColor(score)}`}>
            {typeof score === 'number'
              ? `${Math.round(score * 10)}分`
              : qa.critique
              ? '未评分'
              : ''}
          </span>
          <button
            type="button"
            onClick={() => setEditingQ((v) => !v)}
            title="编辑问题"
            className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
          >
            <Pencil size={13} />
          </button>
        </div>
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
          className="w-full p-3 text-sm font-semibold bg-slate-50 border border-blue-300 rounded-2xl outline-none resize-y mb-4"
        />
      ) : (
        <h3
          onDoubleClick={() => setEditingQ(true)}
          className="text-base font-bold text-slate-900 leading-snug mb-4 cursor-text"
        >
          {question}
        </h3>
      )}

      {/* Candidate Answer Box */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs text-slate-500">
          <div className="flex items-center gap-1.5">
            <span className="font-bold text-slate-700">候选人现场作答</span>
            {qa.answer_audio_url && (
              <audio
                controls
                preload="none"
                src={qa.answer_audio_url}
                className="h-6 max-w-[200px] ml-2"
              />
            )}
          </div>
          <button
            type="button"
            onClick={() => setEditingA((v) => !v)}
            title="编辑回答文本"
            className="text-blue-600 hover:underline inline-flex items-center gap-1"
          >
            <Pencil size={11} />
            <span>编辑回答</span>
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
            className="w-full p-4 text-xs md:text-sm font-mono bg-slate-50 border border-blue-300 rounded-2xl outline-none resize-y leading-relaxed"
          />
        ) : (
          <div
            onDoubleClick={() => setEditingA(true)}
            className="text-xs md:text-sm text-slate-700 leading-relaxed bg-slate-50/90 border border-slate-100 p-4 rounded-2xl cursor-text whitespace-pre-wrap font-sans"
          >
            {answer || <span className="text-slate-400 italic">（录音中未检测到清晰作答）</span>}
          </div>
        )}
      </div>

      {/* Critique / Review Feedback */}
      {qa.critique && (
        <div className="mt-3.5 p-3.5 rounded-2xl bg-amber-50/60 border border-amber-100 text-xs text-slate-700 leading-relaxed">
          <span className="font-bold text-amber-800 mr-1.5">💡 表现点评：</span>
          {qa.critique}
        </div>
      )}

      {/* Action Toolbar */}
      <div className="mt-4 pt-3.5 border-t border-slate-100 flex flex-wrap items-center justify-between gap-3">
        {/* Toggle Improved Answer Button */}
        <button
          type="button"
          onClick={() => setOpenS((v) => !v)}
          className="inline-flex items-center gap-1.5 text-xs font-bold text-blue-600 hover:text-blue-700 transition-colors cursor-pointer"
        >
          <Sparkles size={14} className="text-blue-600" />
          <span>🎯 查看 AI STAR 优化范式回答</span>
          <ChevronRight
            size={14}
            className={`transition-transform duration-200 ${openS ? 'rotate-90' : ''}`}
          />
        </button>

        {onToggleQuestion && (
          <button
            type="button"
            onClick={() => onToggleQuestion(qa.order_idx + 1)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-all ${
              selected
                ? 'bg-blue-100 text-blue-800'
                : 'bg-slate-100 text-slate-600 hover:bg-blue-50 hover:text-blue-700'
            }`}
          >
            <MessageCircleQuestion size={13} />
            <span>{selected ? '已加入追问' : '追问本题'}</span>
          </button>
        )}
      </div>

      {/* Collapsible Improved Answer Box */}
      {openS && (
        <div className="mt-3 p-5 rounded-2xl bg-gradient-to-b from-blue-50/50 via-purple-50/30 to-slate-50/50 border border-blue-200/80 animate-in fade-in duration-200">
          <div className="flex items-center justify-between mb-2.5">
            <span className="text-xs font-bold text-purple-900 flex items-center gap-1.5">
              <Sparkles size={14} className="text-purple-600" />
              <span>STAR 优化回答方案 (Situation · Task · Action · Result)</span>
            </span>
            <button
              type="button"
              onClick={handleCopyImproved}
              className="text-xs font-medium text-slate-500 hover:text-purple-700 inline-flex items-center gap-1"
            >
              {copied ? <Check size={12} className="text-emerald-600" /> : <Copy size={12} />}
              <span>{copied ? '已复制' : '复制范式'}</span>
            </button>
          </div>

          <div className="text-xs md:text-sm text-slate-800 leading-relaxed whitespace-pre-wrap font-sans">
            {hasImproved ? qa.improved_answer : (
              <span className="text-slate-400 italic">LLM 深度优化回答生成中…</span>
            )}
          </div>

          {hasImproved && (
            <div className="mt-4 pt-3 border-t border-purple-100 flex items-center justify-end">
              <button
                type="button"
                onClick={toggleKb}
                disabled={savingKb}
                className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold transition-all ${
                  savedDocId
                    ? 'bg-emerald-100 text-emerald-800 hover:bg-emerald-200'
                    : 'bg-white border border-purple-200 text-purple-800 hover:bg-purple-50 shadow-xs'
                }`}
              >
                {savedDocId ? <BookmarkCheck size={13} /> : <BookmarkPlus size={13} />}
                <span>{savedDocId ? '已沉淀至个人知识库 · 点击移除' : '沉淀至知识库'}</span>
              </button>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
