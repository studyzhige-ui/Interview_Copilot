import { useQuery } from '@tanstack/react-query';
import { BarChart3, Lightbulb, AlertCircle, RefreshCw } from 'lucide-react';
import { getAnalyticsReport } from '@/api/interview';
import { formatScore, scoreFraction } from '@/lib/scoring';
import { EmptyState } from '@/components/ui/EmptyState';
import { Spinner } from '@/components/ui/Spinner';
import { Btn } from '@/components/ui/Btn';
import { AbilityEvidence } from './AbilityEvidence';

const confidenceLabels = { none: '尚无评分依据', low: '证据较少', medium: '证据一般', high: '证据充分' };

export function AnalyticsPage() {
  const query = useQuery({ queryKey: ['analytics-report'], queryFn: getAnalyticsReport });
  const report = query.data;
  return <div className="workspace-page">
    <header className="mb-5 flex items-start justify-between gap-3">
      <div><h1 className="text-2xl font-semibold text-stone-800">能力成长</h1><p className="mt-2 text-sm text-stone-500">按实际面试主题汇总表现，找到下一次练习的重点。</p></div>
      <Btn kind="ghost" size="sm" icon={<RefreshCw size={14} />} aria-label="刷新能力分析" onClick={() => query.refetch()}>刷新</Btn>
    </header>
    {query.isPending ? <p className="flex items-center gap-2 text-sm text-stone-500" role="status"><Spinner size={14} />正在读取能力分析…</p>
      : query.isError ? <div role="alert"><EmptyState title="能力分析暂时无法加载" action={<Btn onClick={() => query.refetch()}>重试</Btn>} /></div>
        : report?.status === 'empty' ? <EmptyState icon={<BarChart3 size={32} />} title="暂无能力分析" description={report.message} />
          : report?.status === 'success' && <>
            <section className="rounded-xl border border-stone-200 bg-white p-5">
              <div className="mb-5 flex flex-wrap items-baseline gap-x-4 gap-y-2">
                <h2 className="font-semibold text-stone-800">近期表现</h2>
                <span className="text-xl font-semibold text-primary-700">{formatScore(report.overall)}</span>
                <span className="text-xs text-stone-500">{report.totals.scored_topics} 个已评分主题 · {report.totals.assessment_count} 次表现判断</span>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">{report.axes.map((axis) => <div key={axis.k}>
                <div className="flex items-center justify-between gap-3"><h3 className="text-sm font-medium text-stone-700">{axis.k}</h3><span className="text-sm text-stone-600">{formatScore(axis.v)}</span></div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-stone-100">{axis.v !== null && <div className="h-full bg-primary-500" style={{ width: `${scoreFraction(axis.v) * 100}%` }} />}</div>
                <p className="mt-1.5 text-xs text-stone-400">{confidenceLabels[axis.confidence]}{axis.assessment_count > 0 && ` · ${axis.assessment_count} 次判断 · ${axis.evidence_count} 条依据`}</p>
              </div>)}</div>
              <p className="mt-5 text-xs leading-5 text-stone-400">同一主题先取多次表现的平均值，再汇总各主题；未评分主题不计入。{report.score_scale.meaning}。</p>
            </section>
            <div className="mt-5 grid items-start gap-5 md:grid-cols-2">
              {!!report.strengths.length && <section className="rounded-xl border border-stone-200 bg-white p-5">
                <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-stone-800"><Lightbulb size={15} />表现较好的主题</h2>
                <ul className="divide-y divide-stone-100">{report.strengths.map((item) => <li key={item.topic} className="py-3 first:pt-0"><div className="flex justify-between gap-3"><h3 className="text-sm font-medium">{item.topic}</h3><span className="text-sm text-primary-700">{formatScore(item.score)}</span></div><p className="mt-2 text-xs leading-6 text-stone-500">最近依据：{item.evidence}</p></li>)}</ul>
              </section>}
              {!!report.weaknesses.length && <section className="rounded-xl border border-stone-200 bg-white p-5">
                <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-stone-800"><AlertCircle size={15} />下次优先练习</h2>
                <ul className="divide-y divide-stone-100">{report.weaknesses.map((item) => <li key={item.topic} className="py-3 first:pt-0"><div className="flex justify-between gap-3"><h3 className="text-sm font-medium">{item.topic}</h3><span className="text-sm text-stone-600">{formatScore(item.score)}</span></div><p className="mt-2 text-xs leading-6 text-stone-500">最近依据：{item.flaw}</p><p className="mt-2 text-xs leading-6 text-primary-700">{item.plan}</p></li>)}</ul>
              </section>}
            </div>
          </>}
    <AbilityEvidence />
  </div>;
}