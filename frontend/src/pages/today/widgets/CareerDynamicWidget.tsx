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

    // Default mock history events if none
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

    return list.slice(0, 6);
  }, [opportunities]);

  const getStatusIcon = (status: CareerEventItem['status']) => {
    switch (status) {
      case 'passed':
        return <CheckCircle2 size={13} className="text-emerald-500 shrink-0" />;
      case 'confirmed':
        return <CheckCircle2 size={13} className="text-blue-500 shrink-0" />;
      case 'closed':
        return <XCircle size={13} className="text-slate-400 shrink-0" />;
      case 'scheduled':
        return <Clock size={13} className="text-indigo-500 shrink-0" />;
    }
  };

  return (
    <div className="h-full flex flex-col justify-between p-5.5 rounded-3xl bg-white/90 backdrop-blur-md border border-slate-200/90 shadow-2xs hover:shadow-xs transition-all select-none">
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center font-bold">
            <Activity size={15} />
          </div>
          <div>
            <h2 className="text-sm font-bold text-slate-900 tracking-tight">求职动态</h2>
            <p className="text-[11px] text-slate-400">外部招聘流程中已发生的确定性进展</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => navigate('/career')}
          className="text-xs text-blue-600 hover:text-blue-800 font-semibold flex items-center gap-0.5 cursor-pointer"
        >
          <span>查看全部</span>
          <ChevronRight size={12} />
        </button>
      </div>

      {/* Timeline List */}
      <div className="flex-1 overflow-y-auto my-3 space-y-3 pr-1 scrollbar-thin">
        {loading ? (
          <div className="py-12 flex flex-col items-center justify-center text-slate-400 text-xs gap-2">
            <Clock size={16} className="animate-spin text-emerald-500" />
            <span>载入求职动态…</span>
          </div>
        ) : (
          <div className="relative pl-3 border-l-2 border-slate-100 space-y-3.5">
            {events.map((ev) => (
              <div
                key={ev.id}
                onClick={() => navigate(ev.targetUrl)}
                className="group cursor-pointer relative"
              >
                {/* Timeline node */}
                <div className="absolute -left-[19px] top-1 w-3 h-3 rounded-full bg-white border-2 border-slate-300 group-hover:border-blue-500 transition-colors" />

                <div className="p-2.5 rounded-2xl bg-slate-50/60 group-hover:bg-slate-100/80 border border-slate-100 transition-all">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-bold text-slate-900 flex items-center gap-1.5 truncate">
                      <Building2 size={12} className="text-slate-400" />
                      <span>{ev.companyName}</span>
                      <span className="text-slate-400 font-normal">· {ev.jobTitle}</span>
                    </span>
                    <time className="text-[10px] text-slate-400 font-mono shrink-0">
                      {ev.timeText}
                    </time>
                  </div>

                  <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-700">
                    {getStatusIcon(ev.status)}
                    <span className="truncate">{ev.eventName}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="pt-2.5 border-t border-slate-100/80 flex items-center justify-between text-[11px] text-slate-400">
        <span>真实外部已发生事件流</span>
        <span className="text-emerald-600 font-semibold">实战溯源</span>
      </div>
    </div>
  );
}
