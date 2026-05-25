import { useEffect, useState } from 'react';
import { BarChart3, Lightbulb, AlertCircle, RefreshCw } from 'lucide-react';
import { EmptyState } from '@/components/ui/EmptyState';
import { Spinner } from '@/components/ui/Spinner';
import { Btn } from '@/components/ui/Btn';
import { toast } from '@/store/uiStore';
import { getAnalyticsReport, listInterviewRecords } from '@/api/interview';
import { useIsMounted } from '@/hooks/useIsMounted';

const MIN_SESSIONS = 3;

interface RadarAxis {
  k: string;
  v: number;
}

interface NormalizedReport {
  axes: RadarAxis[];
  overall: number;
  strengths: { topic: string; evidence: string }[];
  weaknesses: { topic: string; flaw: string; plan?: string }[];
}

function normalize(raw: unknown): NormalizedReport | { empty: true; message: string } {
  if (!raw || typeof raw !== 'object') return { empty: true, message: '无数据' };
  const obj = raw as Record<string, unknown>;
  if (obj.status === 'empty') {
    return { empty: true, message: typeof obj.message === 'string' ? obj.message : '暂无数据' };
  }

  // Try canonical shape from BACKEND_INTEGRATION.md
  let axes: RadarAxis[] = Array.isArray(obj.axes)
    ? (obj.axes as { k?: unknown; v?: unknown }[])
        .map((a) => ({ k: String(a.k ?? ''), v: Number(a.v ?? 0) }))
        .filter((a) => a.k)
    : [];

  // Fallback: skill_radar object → axes
  if (axes.length === 0 && obj.skill_radar && typeof obj.skill_radar === 'object') {
    axes = Object.entries(obj.skill_radar as Record<string, unknown>)
      .map(([k, v]) => ({ k, v: Number(v) || 0 }));
  }

  const overall = typeof obj.overall === 'number'
    ? (obj.overall as number)
    : axes.length > 0
    ? Math.round(axes.reduce((s, a) => s + a.v, 0) / axes.length)
    : 0;

  const strengths = Array.isArray(obj.strengths)
    ? (obj.strengths as Record<string, unknown>[]).map((s) => ({
        topic: String(s.topic ?? ''),
        evidence: String(s.evidence ?? ''),
      }))
    : [];

  const weaknesses = Array.isArray(obj.weaknesses)
    ? (obj.weaknesses as Record<string, unknown>[]).map((w) => ({
        topic: String(w.topic ?? w.k ?? ''),
        flaw: String(w.flaw ?? w.why ?? ''),
        plan: typeof w.plan === 'string' ? w.plan : undefined,
      }))
    : [];

  return { axes, overall, strengths, weaknesses };
}

export function AnalyticsPage() {
  const [sessionCount, setSessionCount] = useState<number | null>(null);
  const [report, setReport] = useState<ReturnType<typeof normalize> | null>(null);
  const [loading, setLoading] = useState(true);

  const isMounted = useIsMounted();
  const refresh = async () => {
    setLoading(true);
    try {
      const records = await listInterviewRecords(0, 50);
      if (!isMounted.current) return;
      setSessionCount(records.length);
      if (records.length >= MIN_SESSIONS) {
        const raw = await getAnalyticsReport();
        if (!isMounted.current) return;
        setReport(normalize(raw));
      } else {
        setReport(null);
      }
    } catch {
      if (isMounted.current) toast.error('能力分析加载失败');
    } finally {
      if (isMounted.current) setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <div className="p-6 flex items-center gap-2 text-stone-500 text-sm">
        <Spinner size={14} /> 载入中...
      </div>
    );
  }

  if ((sessionCount ?? 0) < MIN_SESSIONS) {
    return (
      <div className="p-6">
        <EmptyState
          icon={<BarChart3 size={32} />}
          title={`完成 ${MIN_SESSIONS} 次面试后解锁能力分析`}
          description={`当前 ${sessionCount ?? 0} 次。完成更多场次后，这里会出现六维雷达 + 薄弱点诊断。`}
        />
      </div>
    );
  }

  if (report && 'empty' in report && report.empty) {
    return (
      <div className="p-6">
        <EmptyState
          icon={<BarChart3 size={32} />}
          title="后端尚未生成能力报告"
          description={report.message}
          action={
            <Btn icon={<RefreshCw size={14} />} onClick={refresh}>重新尝试</Btn>
          }
        />
      </div>
    );
  }

  const r = report as NormalizedReport;

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center gap-3 mb-5">
        <h2 className="text-xl font-semibold text-stone-800">能力分析</h2>
        <button
          onClick={refresh}
          className="p-1.5 rounded text-stone-500 hover:bg-stone-100"
          title="刷新"
        >
          <RefreshCw size={14} />
        </button>
      </div>

      <div className="bg-white rounded-xl border border-stone-200 p-5 shadow-xs flex items-center gap-8">
        <OverallCircle score={r.overall} />
        {r.axes.length > 0 ? (
          <Radar axes={r.axes} />
        ) : (
          <div className="text-sm text-stone-500">
            后端未返回结构化能力维度（axes / skill_radar）—— 等待 P2 后端字段对齐。
          </div>
        )}
      </div>

      {r.strengths.length > 0 && (
        <div className="mt-5">
          <h3 className="text-sm font-semibold text-stone-800 mb-2 flex items-center gap-2">
            <Lightbulb size={14} className="text-accent-700" /> 强项
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {r.strengths.map((s, i) => (
              <div key={i} className="bg-white rounded-lg border border-stone-200 p-4 shadow-xs">
                <div className="text-sm font-medium text-stone-800">{s.topic}</div>
                <div className="text-xs text-stone-600 mt-1 leading-relaxed">{s.evidence}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {r.weaknesses.length > 0 && (
        <div className="mt-5">
          <h3 className="text-sm font-semibold text-stone-800 mb-2 flex items-center gap-2">
            <AlertCircle size={14} className="text-warning-500" /> 薄弱点
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {r.weaknesses.map((w, i) => (
              <div key={i} className="bg-white rounded-lg border border-stone-200 p-4 shadow-xs">
                <div className="text-sm font-medium text-stone-800">{w.topic}</div>
                <div className="text-xs text-stone-600 mt-1 leading-relaxed">{w.flaw}</div>
                {w.plan && (
                  <div className="text-xs text-primary-700 mt-2 bg-primary-50 rounded px-2 py-1 leading-relaxed">
                    建议：{w.plan}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function OverallCircle({ score }: { score: number }) {
  const clamped = Math.max(0, Math.min(100, Math.round(score)));
  const r = 56;
  const c = 2 * Math.PI * r;
  const off = c - (clamped / 100) * c;
  return (
    <div className="relative w-[140px] h-[140px] shrink-0">
      <svg width={140} height={140}>
        <circle cx={70} cy={70} r={r} fill="none" stroke="var(--color-stone-100)" strokeWidth={10} />
        <circle
          cx={70} cy={70} r={r}
          fill="none"
          stroke="var(--color-primary-500)"
          strokeWidth={10}
          strokeDasharray={c}
          strokeDashoffset={off}
          strokeLinecap="round"
          transform="rotate(-90 70 70)"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="text-2xl font-semibold text-stone-800">{clamped}</div>
        <div className="text-[11px] text-stone-500">综合分</div>
      </div>
    </div>
  );
}

function Radar({ axes }: { axes: RadarAxis[] }) {
  const n = axes.length;
  const radius = 90;
  const cx = 120;
  const cy = 120;
  const pts = axes.map((a, i) => {
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
    const v = Math.max(0, Math.min(100, a.v)) / 100;
    return {
      x: cx + Math.cos(angle) * radius * v,
      y: cy + Math.sin(angle) * radius * v,
      lx: cx + Math.cos(angle) * (radius + 14),
      ly: cy + Math.sin(angle) * (radius + 14),
      label: a.k,
    };
  });
  const grid = [0.25, 0.5, 0.75, 1].map((scale) => {
    const ringPts = axes.map((_, i) => {
      const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
      return `${cx + Math.cos(angle) * radius * scale},${cy + Math.sin(angle) * radius * scale}`;
    });
    return ringPts.join(' ');
  });

  return (
    <svg width={240} height={240} className="flex-1">
      {grid.map((g, i) => (
        <polygon key={i} points={g} fill="none" stroke="var(--color-stone-200)" strokeWidth={1} />
      ))}
      {axes.map((_, i) => {
        const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
        return (
          <line
            key={i}
            x1={cx} y1={cy}
            x2={cx + Math.cos(angle) * radius}
            y2={cy + Math.sin(angle) * radius}
            stroke="var(--color-stone-200)"
            strokeWidth={1}
          />
        );
      })}
      <polygon
        points={pts.map((p) => `${p.x},${p.y}`).join(' ')}
        fill="var(--color-primary-500)"
        fillOpacity={0.25}
        stroke="var(--color-primary-500)"
        strokeWidth={1.5}
      />
      {pts.map((p, i) => (
        <text
          key={i}
          x={p.lx}
          y={p.ly}
          fontSize={11}
          fill="var(--color-stone-600)"
          textAnchor="middle"
          dominantBaseline="middle"
        >
          {p.label}
        </text>
      ))}
    </svg>
  );
}
