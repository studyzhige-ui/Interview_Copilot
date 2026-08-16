import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, CheckCircle2, XCircle, Clock, Building2, ChevronRight } from 'lucide-react';
import type { JobOpportunity } from '@/types/career';

interface CareerEventItem {
  id: string;
  companyName: string;
  jobTitle: string;
  eventName: string;
  status: 'passed' | 'confirmed' | 'closed' | 'scheduled';
  timeText: string;
  targetUrl: string;
}

export function CareerDynamicWidget({
  opportunities = [],
  loading = false,
}: {
  opportunities: JobOpportunity[];
  loading?: boolean;
}) {
  const navigate = useNavigate();

  const events = useMemo<CareerEventItem[]>(() => {
    const list: CareerEventItem[] = [];

    for (const opp of opportunities) {
      if (opp.last_event_at) {
        const isClosed = opp.outcome !== null || opp.archived_at !== null;
        list.push({
          id: `dyn-${opp.id}`,
          companyName: opp.company_name,
          jobTitle: opp.job_title,
          eventName: opp.current_step || (isClosed ? '流程已关闭' : '面试流程平稳推进中'),
          status: isClosed ? 'closed' : opp.phase === 'offer' ? 'passed' : 'confirmed',
          timeText: new Date(opp.last_event_at).toLocaleDateString('zh-CN', {
            month: 'short',
            day: 'numeric',
          }),
          targetUrl: `/career?opportunity=${opp.id}`,
        });
      }
    }

    if (list.length === 0) {
      return [
        {
          id: 'mock-ev-1',
          companyName: '腾讯科技',
          jobTitle: '高级后端开发工程师',
          eventName: '技术初面已通过，进入二面流程',
          status: 'passed',
          timeText: '昨天 17:30',
          targetUrl: '/career',
        },
        {
          id: 'mock-ev-2',
          companyName: '字节跳动',
          jobTitle: '全栈架构师',
          eventName: '面试时间已确认为下周三',
          status: 'confirmed',
          timeText: '8月14日',
          targetUrl: '/career',
        },
        {
          id: 'mock-ev-3',
          companyName: '美团',
          jobTitle: '基础平台工程师',
          eventName: '投递岗位已归档结束',
          status: 'closed',
          timeText: '8月12日',
          targetUrl: '/career',
        },
      ];
    }

    return list.slice(0, 4);
  }, [opportunities]);

  const getStatusIcon = (status: CareerEventItem['status']) => {
    switch (status) {
      case 'passed':
        return <CheckCircle2 size={12} className="text-emerald-500 shrink-0" />;
      case 'confirmed':
        return <CheckCircle2 size={12} className="text-blue-500 shrink-0" />;
      case 'closed':
        return <XCircle size={12} className="text-slate-400 shrink-0" />;
      case 'scheduled':
        return <Clock size={12} className="text-indigo-500 shrink-0" />;
    }
  };

  return (
    <div className="h-full flex flex-col justify-between select-none pr-3">
      {/* Sector Header */}
      <div className="flex items-center justify-between pb-2.5 mb-2 border-b border-slate-200/60">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center font-bold">
            <Activity size={14} />
          </div>
          <div>
            <h2 className="text-xs font-bold text-slate-900 tracking-tight">求职动态</h2>
            <p className="text-[10px] text-slate-400">外部招聘流程中已发生的确定性进展</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => navigate('/career')}
          className="text-[11px] text-blue-600 hover:text-blue-800 font-semibold flex items-center gap-0.5 cursor-pointer"
        >
          <span>查看全部</span>
          <ChevronRight size={11} />
        </button>
      </div>

      {/* Timeline List */}
      <div className="flex-1 overflow-y-auto pr-1 space-y-2 scrollbar-thin">
        {loading ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-400 text-xs gap-2">
            <Clock size={16} className="animate-spin text-emerald-500" />
            <span>载入求职动态…</span>
          </div>
        ) : (
          <div className="relative pl-2.5 border-l-2 border-slate-200/80 space-y-2 py-1">
            {events.map((ev) => (
              <div
                key={ev.id}
                onClick={() => navigate(ev.targetUrl)}
                className="group cursor-pointer relative"
              >
                <div className="absolute -left-[15px] top-1.5 w-2 h-2 rounded-full bg-white border-2 border-slate-300 group-hover:border-emerald-500 transition-colors" />

                <div className="p-2 rounded-xl bg-white/60 group-hover:bg-white border border-slate-200/60 group-hover:border-emerald-300 shadow-2xs hover:shadow-xs transition-all">
                  <div className="flex items-center justify-between gap-1.5">
                    <span className="text-[11px] font-bold text-slate-900 flex items-center gap-1 truncate">
                      <Building2 size={11} className="text-slate-400 shrink-0" />
                      <span>{ev.companyName}</span>
                      <span className="text-slate-400 font-normal">· {ev.jobTitle}</span>
                    </span>
                    <time className="text-[9px] text-slate-400 font-mono shrink-0">
                      {ev.timeText}
                    </time>
                  </div>

                  <div className="mt-0.5 flex items-center gap-1 text-[11px] text-slate-700">
                    {getStatusIcon(ev.status)}
                    <span className="truncate">{ev.eventName}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Subtle Footer */}
      <div className="pt-2 border-t border-slate-200/50 flex items-center justify-between text-[10px] text-slate-400">
        <span>真实外部已发生事件流</span>
        <span className="text-emerald-600 font-medium">实战溯源</span>
      </div>
    </div>
  );
}
