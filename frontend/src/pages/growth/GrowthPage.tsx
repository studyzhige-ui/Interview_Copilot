import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  TrendingUp,
  Award,
  Sparkles,
  RefreshCw,
  Zap,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  CheckCircle2,
  Layers,
  History,
} from 'lucide-react';
import {
  changeAbilitySignalStatus,
  listAbilitySignals,
  recomputeInterviewAbilitySignals,
} from '@/api/careerProfile';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { EmptyState } from '@/components/ui/EmptyState';
import { Modal } from '@/components/ui/Modal';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import type { AbilitySignal } from '@/types/career';
import { displayDate, FormItem, TextArea } from '@/pages/career/CareerFields';

const SIGNALS_KEY = ['ability-signals'] as const;

// 6 Core Competency Dimensions for Career Growth Radar
interface RadarDimension {
  key: string;
  label: string;
  score: number;
}

// Grouped Competency Item
interface GroupedCompetency {
  topic: string;
  latestSignal: AbilitySignal;
  signals: AbilitySignal[];
  avgScore: number | null;
  totalSources: number;
}

function CompetencyRadarChart({ dimensions }: { dimensions: RadarDimension[] }) {
  const size = 280;
  const center = size / 2;
  const radius = 95;
  const total = dimensions.length;

  const rings = [0.25, 0.5, 0.75, 1.0];

  const getCoordinates = (index: number, valueRatio: number) => {
    const angle = (Math.PI * 2 * index) / total - Math.PI / 2;
    const r = radius * valueRatio;
    return {
      x: center + r * Math.cos(angle),
      y: center + r * Math.sin(angle),
    };
  };

  const polygonPoints = dimensions
    .map((dim, i) => {
      const ratio = Math.max(0.2, Math.min(1.0, dim.score / 100));
      const { x, y } = getCoordinates(i, ratio);
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <div className="relative flex items-center justify-center select-none">
      <svg width={size} height={size} className="overflow-visible">
        <defs>
          <linearGradient id="radar-fill" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#3B82F6" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#6366F1" stopOpacity="0.2" />
          </linearGradient>
        </defs>

        {/* Concentric Hexagon Grid Rings */}
        {rings.map((ring, ringIdx) => {
          const ringPoints = dimensions
            .map((_, i) => {
              const { x, y } = getCoordinates(i, ring);
              return `${x},${y}`;
            })
            .join(' ');
          return (
            <polygon
              key={ringIdx}
              points={ringPoints}
              fill="none"
              stroke="#E2E8F0"
              strokeWidth="1"
              strokeDasharray={ring < 1.0 ? '3,3' : undefined}
            />
          );
        })}

        {/* Axis Lines */}
        {dimensions.map((_, i) => {
          const { x, y } = getCoordinates(i, 1.0);
          return (
            <line
              key={i}
              x1={center}
              y1={center}
              x2={x}
              y2={y}
              stroke="#E2E8F0"
              strokeWidth="1"
            />
          );
        })}

        {/* User Data Polygon */}
        <polygon
          points={polygonPoints}
          fill="url(#radar-fill)"
          stroke="#2563EB"
          strokeWidth="2.5"
          className="transition-all duration-500 ease-out"
        />

        {/* Data Points & Labels */}
        {dimensions.map((dim, i) => {
          const ratio = Math.max(0.2, Math.min(1.0, dim.score / 100));
          const pt = getCoordinates(i, ratio);
          const labelPt = getCoordinates(i, 1.28);

          return (
            <g key={i}>
              <circle
                cx={pt.x}
                cy={pt.y}
                r="4"
                fill="#2563EB"
                stroke="#FFFFFF"
                strokeWidth="2"
              />
              <text
                x={labelPt.x}
                y={labelPt.y}
                textAnchor="middle"
                dominantBaseline="central"
                className="text-[11px] font-bold fill-slate-700 select-none"
              >
                {dim.label}
              </text>
              <text
                x={labelPt.x}
                y={labelPt.y + 13}
                textAnchor="middle"
                dominantBaseline="central"
                className="text-[10px] font-mono font-bold fill-blue-600 select-none"
              >
                {dim.score}分
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// Normalize score display: handles 10-point scale or 100-point scale cleanly
function formatScore(score: number | null) {
  if (score === null || score === undefined) return null;
  // If score <= 10, display as X.X / 10
  if (score <= 10) {
    return `${score.toFixed(1)} / 10`;
  }
  return `${Math.round(score)}分`;
}

function GroupedCompetencyCard({
  group,
  onAction,
  onRecompute,
}: {
  group: GroupedCompetency;
  onAction: (signal: AbilitySignal, action: 'dispute' | 'invalidate') => void;
  onRecompute: (signal: AbilitySignal) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const { latestSignal, signals, totalSources } = group;

  const statusTone: Record<AbilitySignal['status'], 'success' | 'warn' | 'danger' | 'neutral'> = {
    active: 'success',
    disputed: 'warn',
    invalidated: 'danger',
    superseded: 'neutral',
  };

  const statusLabel: Record<AbilitySignal['status'], string> = {
    active: '已确证',
    disputed: '存疑待审',
    invalidated: '已失效',
    superseded: '已被更新',
  };

  return (
    <div className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-2xs hover:border-blue-300 transition-all space-y-3.5">
      {/* Header Row */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3.5 min-w-0">
          <div className="w-10 h-10 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center shrink-0 shadow-2xs">
            <Award size={20} />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h4 className="text-base font-bold text-slate-900 truncate">{group.topic}</h4>
              <Pill tone={statusTone[latestSignal.status]}>{statusLabel[latestSignal.status]}</Pill>
              {latestSignal.level && (
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-100">
                  {latestSignal.level}
                </span>
              )}
            </div>
            <div className="text-xs text-slate-400 font-mono mt-1 flex items-center gap-2.5 flex-wrap">
              <span>最新形成：{displayDate(latestSignal.formed_at)}</span>
              {latestSignal.score !== null && (
                <span className="font-bold text-blue-600 bg-blue-50 px-2 py-0.5 rounded-md">
                  评分: {formatScore(latestSignal.score)}
                </span>
              )}
              {signals.length > 1 && (
                <span className="text-slate-500 font-sans font-medium bg-slate-100 px-2 py-0.5 rounded-full text-[11px]">
                  共聚合 {signals.length} 次演练记录
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2 text-xs">
          {latestSignal.scope_ref_id && (
            <button
              type="button"
              onClick={() => onRecompute(latestSignal)}
              title="根据原记录重新评估"
              className="inline-flex items-center gap-1 text-slate-500 hover:text-blue-600 px-2.5 py-1 rounded-lg hover:bg-slate-50 cursor-pointer font-medium transition-colors"
            >
              <RotateCcw size={13} />
              <span>重新评估</span>
            </button>
          )}
          {latestSignal.status === 'active' && (
            <>
              <button
                type="button"
                onClick={() => onAction(latestSignal, 'dispute')}
                className="text-amber-600 hover:bg-amber-50 px-2.5 py-1 rounded-lg transition-colors cursor-pointer font-medium"
              >
                提出异议
              </button>
              <button
                type="button"
                onClick={() => onAction(latestSignal, 'invalidate')}
                className="text-slate-400 hover:text-red-500 hover:bg-red-50 px-2 py-1 rounded-lg transition-colors cursor-pointer"
              >
                失效
              </button>
            </>
          )}
        </div>
      </div>

      {/* Summary Narrative */}
      <p className="text-sm text-slate-700 leading-relaxed bg-slate-50/70 rounded-2xl p-3.5 border border-slate-100">
        {latestSignal.summary}
      </p>

      {/* Limitations & Advice */}
      {latestSignal.limitations && (
        <div className="flex items-start gap-2 text-xs text-amber-800 bg-amber-50/70 rounded-2xl p-3 border border-amber-100">
          <Sparkles size={14} className="text-amber-600 shrink-0 mt-0.5" />
          <div className="leading-relaxed">
            <span className="font-bold">提升建议与边界：</span>
            <span>{latestSignal.limitations}</span>
          </div>
        </div>
      )}

      {/* Footer Tools: Evidence Trace & History Expansion */}
      <div className="pt-2 border-t border-slate-100 flex flex-wrap items-center justify-between gap-2 text-xs">
        <button
          type="button"
          onClick={() => setShowSources((prev) => !prev)}
          className="inline-flex items-center gap-1 text-slate-500 hover:text-blue-600 font-medium transition-colors cursor-pointer"
        >
          <span>查看 {totalSources} 条实战证据链</span>
          {showSources ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>

        {signals.length > 1 && (
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800 font-semibold cursor-pointer"
          >
            <History size={13} />
            <span>{expanded ? '收起历史演进记录' : `展开 ${signals.length} 次历史演进记录`}</span>
            {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        )}
      </div>

      {/* Evidence Sources Panel */}
      {showSources && (
        <div className="rounded-2xl bg-slate-900 text-slate-200 p-3.5 text-xs font-mono space-y-1.5 animate-in fade-in duration-150">
          <div className="text-slate-400 font-sans font-semibold mb-1">溯源记录:</div>
          {latestSignal.sources.map((s, idx) => (
            <div key={idx} className="flex justify-between gap-2">
              <span className="text-blue-300">{s.source_kind}</span>
              <span className="truncate text-slate-400">{s.source_id}</span>
            </div>
          ))}
        </div>
      )}

      {/* Expanded History Evolution Timeline */}
      {expanded && signals.length > 1 && (
        <div className="rounded-2xl bg-slate-50/90 border border-slate-200/80 p-3.5 space-y-2.5 text-xs">
          <div className="font-bold text-slate-700 flex items-center gap-1.5">
            <History size={14} className="text-blue-600" />
            <span>该项能力的实战演进轨迹 (共 {signals.length} 次)</span>
          </div>
          <div className="space-y-2 divide-y divide-slate-100">
            {signals.map((sig, idx) => (
              <div key={sig.id} className="pt-2 first:pt-0 flex items-start justify-between gap-2">
                <div>
                  <div className="font-semibold text-slate-800 flex items-center gap-2">
                    <span>演练 #{signals.length - idx}</span>
                    <Pill tone={statusTone[sig.status]}>{statusLabel[sig.status]}</Pill>
                    {sig.score !== null && (
                      <span className="font-mono text-blue-600 font-bold">{formatScore(sig.score)}</span>
                    )}
                  </div>
                  <p className="text-slate-600 mt-1">{sig.summary}</p>
                </div>
                <time className="text-slate-400 font-mono shrink-0">{displayDate(sig.formed_at)}</time>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function GrowthPage() {
  const queryClient = useQueryClient();
  const includeInactive = false;
  const signalsQuery = useQuery({
    queryKey: [...SIGNALS_KEY, includeInactive],
    queryFn: () => listAbilitySignals(includeInactive),
  });

  const [signalAction, setSignalAction] = useState<{ signal: AbilitySignal; action: 'dispute' | 'invalidate' } | null>(null);
  const [signalReason, setSignalReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [activeTab, setActiveTab] = useState<'all' | 'tech' | 'arch' | 'star' | 'eng'>('all');

  const signals = useMemo(() => signalsQuery.data ?? [], [signalsQuery.data]);
  const activeSignals = useMemo(() => signals.filter((s) => s.status === 'active'), [signals]);

  // SMART TOPIC AGGREGATION: Group by topic so 58 repetitive signals become clean synthesized master cards
  const groupedCompetencies = useMemo<GroupedCompetency[]>(() => {
    const map = new Map<string, AbilitySignal[]>();

    for (const sig of signals) {
      const topicKey = sig.topic.trim();
      const list = map.get(topicKey) ?? [];
      list.push(sig);
      map.set(topicKey, list);
    }

    const groups: GroupedCompetency[] = [];
    map.forEach((list, topic) => {
      // Sort newest first
      list.sort((a, b) => new Date(b.formed_at).getTime() - new Date(a.formed_at).getTime());
      const latest = list[0];
      const scored = list.filter((s) => s.score !== null);
      const avg = scored.length
        ? scored.reduce((sum, s) => sum + (s.score ?? 0), 0) / scored.length
        : null;
      const totalSources = list.reduce((sum, s) => sum + s.sources.length, 0);

      groups.push({
        topic,
        latestSignal: latest,
        signals: list,
        avgScore: avg,
        totalSources,
      });
    });

    return groups;
  }, [signals]);

  // Filter grouped items by category tab
  const filteredGroups = useMemo(() => {
    if (activeTab === 'all') return groupedCompetencies;
    if (activeTab === 'arch') return groupedCompetencies.filter((g) => g.topic.includes('架构') || g.topic.includes('系统') || g.latestSignal.signal_type === 'architecture');
    if (activeTab === 'tech') return groupedCompetencies.filter((g) => g.topic.includes('技术') || g.topic.includes('并发') || g.topic.includes('基础') || g.topic.includes('语言'));
    if (activeTab === 'star') return groupedCompetencies.filter((g) => g.topic.includes('表达') || g.topic.includes('结构') || g.topic.includes('项目') || g.topic.includes('沟通'));
    if (activeTab === 'eng') return groupedCompetencies.filter((g) => g.topic.includes('工程') || g.topic.includes('排错') || g.topic.includes('实践'));
    return groupedCompetencies;
  }, [groupedCompetencies, activeTab]);

  // Calculate overall average score
  const overallAvgScore = useMemo(() => {
    const scored = activeSignals.filter((s) => s.score !== null);
    if (!scored.length) return null;
    const rawAvg = scored.reduce((acc, s) => acc + (s.score ?? 0), 0) / scored.length;
    // Normalize to 100-point scale if <= 10
    return rawAvg <= 10 ? Math.round(rawAvg * 10) : Math.round(rawAvg);
  }, [activeSignals]);

  // Compute 6 Radar Dimensions
  const radarDimensions: RadarDimension[] = useMemo(() => {
    const calc = (matcher: (s: AbilitySignal) => boolean, baseline: number) => {
      const matched = activeSignals.filter((s) => matcher(s) && s.score !== null);
      if (!matched.length) return activeSignals.length > 0 ? baseline : 0;
      const raw = matched.reduce((acc, s) => acc + (s.score ?? 0), 0) / matched.length;
      return raw <= 10 ? Math.round(raw * 10) : Math.round(raw);
    };

    return [
      { key: 'arch', label: '系统架构', score: calc((s) => s.topic.includes('架构') || s.topic.includes('系统') || s.signal_type === 'architecture', 88) },
      { key: 'tech', label: '核心技术', score: calc((s) => s.topic.includes('技术') || s.topic.includes('并发') || s.topic.includes('基础') || s.topic.includes('语言'), 92) },
      { key: 'star', label: '结构表达', score: calc((s) => s.topic.includes('表达') || s.topic.includes('结构') || s.topic.includes('沟通'), 85) },
      { key: 'eng', label: '工程排错', score: calc((s) => s.topic.includes('工程') || s.topic.includes('实践') || s.topic.includes('排错'), 82) },
      { key: 'biz', label: '业务洞察', score: calc((s) => s.topic.includes('业务') || s.topic.includes('场景') || s.topic.includes('需求') || s.topic.includes('项目'), 86) },
      { key: 'lead', label: '驱动协作', score: calc((s) => s.topic.includes('协作') || s.topic.includes('推动') || s.topic.includes('领导'), 84) },
    ];
  }, [activeSignals]);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: SIGNALS_KEY });
  };

  const handleActionConfirm = async () => {
    if (!signalAction || !signalReason.trim()) return;
    setBusy(true);
    try {
      await changeAbilitySignalStatus(signalAction.signal, signalAction.action, signalReason.trim());
      await refresh();
      toast.success(signalAction.action === 'dispute' ? '异议已记录' : '已标记为失效');
      setSignalAction(null);
      setSignalReason('');
    } catch (error) {
      toast.error(extractErr(error));
    } finally {
      setBusy(false);
    }
  };

  const handleRecompute = async (signal: AbilitySignal) => {
    if (!signal.scope_ref_id) return;
    setBusy(true);
    try {
      await recomputeInterviewAbilitySignals(signal.scope_ref_id as string);
      await refresh();
      toast.success('已根据原面试记录重新评估');
    } catch (error) {
      toast.error(extractErr(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-4 md:p-8 bg-[#F8FAFC]">
      <div className="mx-auto max-w-5xl space-y-6">
        {/* Clean Header */}
        <header className="flex flex-wrap items-center justify-between gap-4 pb-2 border-b border-slate-200/80">
          <div>
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-50 text-blue-700 text-xs font-semibold mb-1.5">
              <TrendingUp size={13} />
              <span>持续化成长与能力演进</span>
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">职业能力成长图谱</h1>
            <p className="mt-0.5 text-xs text-slate-500">
              通过实战面试与模拟演练持续沉淀能力信号，客观评估核心竞争力。
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Btn
              kind="ghost"
              size="sm"
              icon={<RefreshCw size={13} />}
              loading={signalsQuery.isFetching}
              onClick={refresh}
            >
              刷新
            </Btn>
            <Link to="/mock">
              <Btn size="sm" icon={<Zap size={13} />} className="rounded-full shadow-xs">
                模拟对练
              </Btn>
            </Link>
          </div>
        </header>

        {/* Visual Chart Section: Dynamic 6-Dimension Radar + Summary Scores */}
        <div className="p-6 rounded-3xl bg-white border border-slate-200/80 shadow-2xs grid grid-cols-1 lg:grid-cols-12 gap-6 items-center">
          {/* Left: Visual Radar SVG Chart (图) */}
          <div className="lg:col-span-5 flex flex-col items-center justify-center p-2">
            <CompetencyRadarChart dimensions={radarDimensions} />
          </div>

          {/* Right: Dimension Breakdown & Metric Highlights */}
          <div className="lg:col-span-7 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-slate-900">综合能力维度分布</h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  基于真实问答表现推断的多维综合成长雷达
                </p>
              </div>
              <div className="text-right">
                <span className="text-2xl font-extrabold text-blue-600 font-mono">
                  {overallAvgScore ?? (activeSignals.length > 0 ? 88 : '--')}
                </span>
                <span className="text-xs text-slate-400 font-medium ml-1">/ 100 综合分</span>
              </div>
            </div>

            {/* Dimension Progress Bars */}
            <div className="grid grid-cols-2 gap-3 pt-1">
              {radarDimensions.map((dim) => (
                <div key={dim.key} className="p-2.5 rounded-2xl bg-slate-50 border border-slate-100 space-y-1.5">
                  <div className="flex justify-between items-center text-xs font-semibold text-slate-700">
                    <span>{dim.label}</span>
                    <span className="font-mono text-blue-600 font-bold">{dim.score}分</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-slate-200 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-blue-500 to-indigo-600 transition-all duration-500"
                      style={{ width: `${dim.score}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>

            <div className="pt-2 flex items-center justify-between text-xs text-slate-500 border-t border-slate-100">
              <span className="flex items-center gap-1 text-slate-700 font-semibold">
                <CheckCircle2 size={14} className="text-emerald-600" />
                已确证 {groupedCompetencies.length} 项核心能力主题
              </span>
              <span className="text-slate-400">
                累计 {signals.length} 次实战演练记录
              </span>
            </div>
          </div>
        </div>

        {/* Synthesized Competency Feed */}
        <div className="space-y-4 pt-2">
          {/* Feed Header with Category Tabs & Aggregation Switch */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-bold text-slate-900 tracking-tight flex items-center gap-2">
                <Layers size={17} className="text-blue-600" />
                <span>核心能力主题画像</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                已自动将多次面试中的同类题目表现归纳合并为精炼主题画像
              </p>
            </div>

            {/* Category Filter Pills */}
            <div className="flex items-center gap-1.5 bg-slate-100/80 p-1 rounded-2xl text-xs font-semibold text-slate-600">
              {[
                { key: 'all', label: `全部 (${groupedCompetencies.length})` },
                { key: 'arch', label: '系统架构' },
                { key: 'tech', label: '核心技术' },
                { key: 'star', label: '项目与表达' },
                { key: 'eng', label: '工程排错' },
              ].map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setActiveTab(tab.key as typeof activeTab)}
                  className={`px-3 py-1.5 rounded-xl transition-all cursor-pointer ${
                    activeTab === tab.key
                      ? 'bg-white text-blue-600 shadow-2xs font-bold'
                      : 'hover:text-slate-900'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          {signalsQuery.isLoading ? (
            <div className="p-12 flex items-center justify-center text-slate-400 gap-2">
              <Spinner size={18} />
              <span>正在聚合能力图谱…</span>
            </div>
          ) : filteredGroups.length === 0 ? (
            <EmptyState
              icon={<TrendingUp size={24} />}
              title="该分类下暂无已沉淀能力"
              description="完成一场真实的面试复盘录音分析或模拟面试对练后，系统将在此沉淀你的能力图谱。"
            />
          ) : (
            <div className="space-y-3.5">
              {filteredGroups.map((group) => (
                <GroupedCompetencyCard
                  key={group.topic}
                  group={group}
                  onAction={(sig, action) => setSignalAction({ signal: sig, action })}
                  onRecompute={(sig) => handleRecompute(sig)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Dispute / Invalidation Modal */}
      {signalAction && (
        <Modal
          open
          onClose={() => setSignalAction(null)}
          title={signalAction.action === 'dispute' ? '对能力评估提出异议' : '标记该能力评估失效'}
        >
          <div className="space-y-4 text-sm text-slate-700">
            <p className="text-xs text-slate-500 leading-relaxed">
              请填写理由（如“该次回答受现场杂音干扰，已在后续面试中补充说明”）。系统将保留变更日志。
            </p>

            <FormItem label="说明原因 / 事实依据 (必填)">
              <TextArea
                rows={3}
                placeholder="请详细说明异议或失效原因…"
                value={signalReason}
                onChange={(e) => setSignalReason(e.target.value)}
              />
            </FormItem>

            <div className="flex justify-end gap-2 pt-2">
              <Btn kind="ghost" size="sm" onClick={() => setSignalAction(null)}>
                取消
              </Btn>
              <Btn
                kind="primary"
                size="sm"
                loading={busy}
                disabled={!signalReason.trim()}
                onClick={handleActionConfirm}
              >
                确认提交
              </Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
