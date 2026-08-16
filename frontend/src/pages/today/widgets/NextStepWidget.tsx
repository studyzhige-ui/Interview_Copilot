import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckSquare, CheckCircle2, Clock, ArrowRight } from 'lucide-react';
import type { JobOpportunity } from '@/types/career';

interface NextStepItem {
  id: string;
  title: string;
  subtitle: string;
  timeText: string;
  timeCategory: 'today' | 'tomorrow' | 'upcoming';
  targetUrl: string;
  actionKind: string;
}

export function NextStepWidget({
  opportunities = [],
  loading = false,
}: {
  opportunities: JobOpportunity[];
  loading?: boolean;
}) {
  const navigate = useNavigate();

  const items = useMemo<NextStepItem[]>(() => {
    const list: NextStepItem[] = [];

    for (const opp of opportunities) {
      if (opp.archived_at || opp.outcome) continue;

      if (opp.current_step) {
        list.push({
          id: `step-${opp.id}`,
          title: `推进 ${opp.current_step}`,
          subtitle: `${opp.company_name} · ${opp.job_title}`,
          timeText: '今天 23:59',
          timeCategory: 'today',
          targetUrl: `/career?opportunity=${opp.id}`,
          actionKind: 'progress_step',
        });
      }
    }

    if (list.length === 0 && opportunities.length > 0) {
      const firstActive = opportunities.find((o) => !o.archived_at && !o.outcome);
      if (firstActive) {
        list.push({
          id: 'default-mock-step-1',
          title: '完成技术一面在线测评',
          subtitle: `${firstActive.company_name} · ${firstActive.job_title}`,
          timeText: '截止 23:59',
          timeCategory: 'today',
          targetUrl: `/career?opportunity=${firstActive.id}`,
          actionKind: 'assessment',
        });
        list.push({
          id: 'default-mock-step-2',
          title: '参加系统设计专项模拟面试',
          subtitle: `${firstActive.company_name} · ${firstActive.job_title}`,
          timeText: '明天 10:30',
          timeCategory: 'tomorrow',
          targetUrl: `/interviews?tab=mock&opportunity=${firstActive.id}`,
          actionKind: 'mock_interview',
        });
      }
    }

    return list;
  }, [opportunities]);

  const todayItems = items.filter((i) => i.timeCategory === 'today');
  const tomorrowItems = items.filter((i) => i.timeCategory === 'tomorrow');
  const upcomingItems = items.filter((i) => i.timeCategory === 'upcoming');

  return (
    <div className="h-full flex flex-col justify-between select-none pr-3">
      {/* Sector Header */}
      <div className="flex items-center justify-between pb-2.5 mb-2 border-b border-slate-200/60">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center font-bold">
            <CheckSquare size={14} />
          </div>
          <div>
            <h2 className="text-xs font-bold text-slate-900 tracking-tight">下一步</h2>
            <p className="text-[10px] text-slate-400">已确认且需你推进的真实事项</p>
          </div>
        </div>
        <span className="text-[11px] font-mono font-bold text-blue-600 bg-blue-50/80 px-2 py-0.5 rounded-full">
          {items.length} 项待办
        </span>
      </div>

      {/* Stream List */}
      <div className="flex-1 overflow-y-auto pr-1 space-y-3 scrollbar-thin">
        {loading ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-400 text-xs gap-2">
            <Clock size={16} className="animate-spin text-blue-500" />
            <span>加载执行流…</span>
          </div>
        ) : items.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center text-slate-400">
            <div className="w-8 h-8 rounded-xl bg-slate-100 flex items-center justify-center text-slate-400 mb-1.5">
              <CheckCircle2 size={16} className="text-emerald-500" />
            </div>
            <p className="text-xs font-semibold text-slate-700">当前没有需要推进的动作</p>
            <p className="text-[10px] text-slate-400 mt-0.5">所有事项均已按计划完成</p>
          </div>
        ) : (
          <>
            {todayItems.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[10px] font-bold text-blue-700 uppercase flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-600" />
                  <span>今天</span>
                </div>
                {todayItems.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => navigate(item.targetUrl)}
                    className="group p-2.5 rounded-xl bg-white/70 hover:bg-white border border-slate-200/70 hover:border-blue-300 shadow-2xs hover:shadow-xs transition-all cursor-pointer flex items-center justify-between gap-2"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-bold text-slate-800 group-hover:text-blue-900 truncate">
                        {item.title}
                      </div>
                      <div className="text-[10px] text-slate-400 truncate mt-0.5">
                        {item.subtitle}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="text-[10px] font-mono font-semibold text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200/60">
                        {item.timeText}
                      </span>
                      <ArrowRight size={12} className="text-slate-400 group-hover:text-blue-600 group-hover:translate-x-0.5 transition-all" />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {tomorrowItems.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[10px] font-bold text-indigo-700 uppercase flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-indigo-600" />
                  <span>明天</span>
                </div>
                {tomorrowItems.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => navigate(item.targetUrl)}
                    className="group p-2.5 rounded-xl bg-white/70 hover:bg-white border border-slate-200/70 hover:border-indigo-300 shadow-2xs hover:shadow-xs transition-all cursor-pointer flex items-center justify-between gap-2"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-bold text-slate-800 group-hover:text-indigo-900 truncate">
                        {item.title}
                      </div>
                      <div className="text-[10px] text-slate-400 truncate mt-0.5">
                        {item.subtitle}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="text-[10px] font-mono text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded">
                        {item.timeText}
                      </span>
                      <ArrowRight size={12} className="text-slate-400 group-hover:text-indigo-600 group-hover:translate-x-0.5 transition-all" />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {upcomingItems.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[10px] font-bold text-slate-500 uppercase flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
                  <span>近期待办</span>
                </div>
                {upcomingItems.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => navigate(item.targetUrl)}
                    className="group p-2.5 rounded-xl bg-white/50 hover:bg-white border border-slate-200/60 transition-all cursor-pointer flex items-center justify-between gap-2"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-bold text-slate-800 truncate">{item.title}</div>
                      <div className="text-[10px] text-slate-400 truncate mt-0.5">{item.subtitle}</div>
                    </div>
                    <span className="text-[10px] font-mono text-slate-400">{item.timeText}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Subtle Footer */}
      <div className="pt-2 border-t border-slate-200/50 flex items-center justify-between text-[10px] text-slate-400">
        <span>点击直达目标工作区</span>
        <span className="text-blue-600 font-medium">带入岗位上下文</span>
      </div>
    </div>
  );
}
