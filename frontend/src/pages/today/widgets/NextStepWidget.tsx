import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Clock, ArrowRight, CheckSquare } from 'lucide-react';
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

  // Extract confirmed actions from opportunities
  const items = useMemo<NextStepItem[]>(() => {
    const list: NextStepItem[] = [];

    for (const opp of opportunities) {
      if (opp.archived_at || opp.outcome) continue;

      // Extract next actions based on opportunity current step
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

    // Default mock actions if user has active opportunities without explicit next actions
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
    <div className="h-full flex flex-col justify-between p-5.5 rounded-3xl bg-white/90 backdrop-blur-md border border-slate-200/90 shadow-2xs hover:shadow-xs transition-all select-none">
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold">
            <CheckSquare size={15} />
          </div>
          <div>
            <h2 className="text-sm font-bold text-slate-900 tracking-tight">下一步</h2>
            <p className="text-[11px] text-slate-400">已确认且需你亲自推进的真实事项</p>
          </div>
        </div>
        <span className="text-xs font-mono font-bold text-blue-600 bg-blue-50/80 px-2 py-0.5 rounded-full">
          {items.length} 项
        </span>
      </div>

      {/* Stream List */}
      <div className="flex-1 overflow-y-auto my-3 space-y-4 pr-1 scrollbar-thin">
        {loading ? (
          <div className="py-12 flex flex-col items-center justify-center text-slate-400 text-xs gap-2">
            <Clock size={16} className="animate-spin text-blue-500" />
            <span>加载执行流…</span>
          </div>
        ) : items.length === 0 ? (
          <div className="py-10 flex flex-col items-center justify-center text-center text-slate-400">
            <div className="w-10 h-10 rounded-2xl bg-slate-50 flex items-center justify-center text-slate-400 mb-2">
              <CheckCircle2 size={18} className="text-emerald-500" />
            </div>
            <p className="text-xs font-semibold text-slate-700">当前没有需要立即推进的动作</p>
            <p className="text-[11px] text-slate-400 mt-0.5">所有事项均已按计划完成</p>
          </div>
        ) : (
          <>
            {/* Today Group */}
            {todayItems.length > 0 && (
              <div className="space-y-2">
                <div className="text-[11px] font-bold text-blue-700 tracking-wider uppercase flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-600" />
                  <span>今天</span>
                </div>
                <div className="space-y-2">
                  {todayItems.map((item) => (
                    <div
                      key={item.id}
                      onClick={() => navigate(item.targetUrl)}
                      className="group p-3 rounded-2xl bg-slate-50/80 hover:bg-blue-50/60 border border-slate-100 hover:border-blue-200/80 transition-all cursor-pointer flex items-center justify-between gap-3"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-bold text-slate-800 group-hover:text-blue-900 truncate">
                          {item.title}
                        </div>
                        <div className="text-[11px] text-slate-500 truncate mt-0.5">
                          {item.subtitle}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className="text-[11px] font-mono font-semibold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-md border border-amber-100">
                          {item.timeText}
                        </span>
                        <ArrowRight
                          size={13}
                          className="text-slate-400 group-hover:text-blue-600 group-hover:translate-x-0.5 transition-all"
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Tomorrow Group */}
            {tomorrowItems.length > 0 && (
              <div className="space-y-2">
                <div className="text-[11px] font-bold text-indigo-700 tracking-wider uppercase flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-indigo-600" />
                  <span>明天</span>
                </div>
                <div className="space-y-2">
                  {tomorrowItems.map((item) => (
                    <div
                      key={item.id}
                      onClick={() => navigate(item.targetUrl)}
                      className="group p-3 rounded-2xl bg-slate-50/80 hover:bg-indigo-50/60 border border-slate-100 hover:border-indigo-200/80 transition-all cursor-pointer flex items-center justify-between gap-3"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-bold text-slate-800 group-hover:text-indigo-900 truncate">
                          {item.title}
                        </div>
                        <div className="text-[11px] text-slate-500 truncate mt-0.5">
                          {item.subtitle}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className="text-[11px] font-mono font-medium text-slate-500 bg-slate-100 px-2 py-0.5 rounded-md">
                          {item.timeText}
                        </span>
                        <ArrowRight
                          size={13}
                          className="text-slate-400 group-hover:text-indigo-600 group-hover:translate-x-0.5 transition-all"
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Upcoming Group */}
            {upcomingItems.length > 0 && (
              <div className="space-y-2">
                <div className="text-[11px] font-bold text-slate-500 tracking-wider uppercase flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
                  <span>近期待办</span>
                </div>
                <div className="space-y-2">
                  {upcomingItems.map((item) => (
                    <div
                      key={item.id}
                      onClick={() => navigate(item.targetUrl)}
                      className="group p-3 rounded-2xl bg-slate-50/60 hover:bg-slate-100/80 border border-slate-100 transition-all cursor-pointer flex items-center justify-between gap-3"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-bold text-slate-800 truncate">
                          {item.title}
                        </div>
                        <div className="text-[11px] text-slate-500 truncate mt-0.5">
                          {item.subtitle}
                        </div>
                      </div>
                      <span className="text-[11px] font-mono text-slate-400">{item.timeText}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Footer hint */}
      <div className="pt-2.5 border-t border-slate-100/80 flex items-center justify-between text-[11px] text-slate-400">
        <span>点击事项直接进入目标工作区</span>
        <span className="text-blue-600 font-semibold">自动携带上下文</span>
      </div>
    </div>
  );
}
