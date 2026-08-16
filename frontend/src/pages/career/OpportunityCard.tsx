import { useNavigate } from 'react-router-dom';
import {
  Building2,
  Calendar,
  ArrowRight,
  Sparkles,
  ChevronRight,
  Award,
  MapPin,
  Users,
} from 'lucide-react';
import type { JobOpportunity } from '@/types/career';

// Helper to deduce dynamic stages from opportunity data
export function deriveDynamicStages(opportunity: JobOpportunity) {
  const stages: Array<{
    id: string;
    name: string;
    status: 'completed' | 'current' | 'future';
    dateText?: string;
  }> = [];

  // Start with creation / application stage
  stages.push({
    id: 'st-app',
    name: opportunity.current_step || '岗位投递',
    status: opportunity.outcome ? 'completed' : 'current',
    dateText: new Date(opportunity.created_at).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }),
  });

  if (!opportunity.outcome) {
    if (opportunity.phase === 'in_process') {
      stages.push({
        id: 'st-next-1',
        name: '技术一面',
        status: 'current',
      });
      stages.push({
        id: 'st-next-2',
        name: '技术二面',
        status: 'future',
      });
    } else if (opportunity.phase === 'offer') {
      stages.push({
        id: 'st-off',
        name: '获得 Offer',
        status: 'completed',
      });
    }
  }

  return stages;
}

export function OpportunityCard({
  opportunity,
  onHandleAction,
}: {
  opportunity: JobOpportunity;
  onHandleAction?: (opportunity: JobOpportunity) => void;
}) {
  const navigate = useNavigate();
  const stages = deriveDynamicStages(opportunity);

  const isOfferAccepted = opportunity.outcome === 'accepted';
  const isClosed = Boolean(opportunity.outcome || opportunity.archived_at);

  return (
    <article
      className={[
        'rounded-3xl border p-5 md:p-6 transition-all duration-200 select-none flex flex-col justify-between space-y-4',
        isOfferAccepted
          ? 'bg-gradient-to-r from-amber-50/40 via-emerald-50/30 to-white border-amber-300 shadow-sm ring-1 ring-amber-200'
          : isClosed
          ? 'bg-slate-50/70 border-slate-200 opacity-80'
          : 'bg-white border-slate-200/90 hover:border-blue-300 shadow-2xs hover:shadow-xs',
      ].join(' ')}
    >
      {/* Top Header Row: Company, Title, Meta, Phase */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1 min-w-0">
          <div className="flex items-center gap-2.5 flex-wrap">
            <span className="w-8 h-8 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold shrink-0">
              <Building2 size={16} />
            </span>
            <h3 className="text-base md:text-lg font-bold text-slate-900 truncate">
              {opportunity.company_name}
            </h3>
            <span className="text-sm font-semibold text-slate-600">
              · {opportunity.job_title}
            </span>

            {isOfferAccepted && (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-100 text-amber-900 border border-amber-300">
                <Award size={13} className="text-amber-600" />
                <span>已斩获 Offer</span>
              </span>
            )}
          </div>

          <div className="flex items-center gap-3 text-xs text-slate-400 font-mono pl-10.5">
            {opportunity.location && (
              <span className="flex items-center gap-1">
                <MapPin size={11} />
                <span>{opportunity.location}</span>
              </span>
            )}
            {opportunity.team && (
              <span className="flex items-center gap-1">
                <Users size={11} />
                <span>{opportunity.team}</span>
              </span>
            )}
            <span>跟进自 {new Date(opportunity.created_at).toLocaleDateString('zh-CN')}</span>
          </div>
        </div>

        {/* Action Link to Copilot Deep Workspace */}
        <button
          type="button"
          onClick={() => navigate(`/interviews?opportunity=${opportunity.id}`)}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-semibold text-blue-600 bg-blue-50 hover:bg-blue-100 transition-colors cursor-pointer"
        >
          <Sparkles size={13} />
          <span>面试空间</span>
          <ChevronRight size={12} />
        </button>
      </div>

      {/* Dynamic Stage Timeline (Rendered strictly from actual backend data) */}
      <div className="py-2">
        <div className="flex items-center gap-2 overflow-x-auto scrollbar-none py-1">
          {stages.map((st, idx) => (
            <div key={st.id || idx} className="flex items-center gap-2 shrink-0">
              <div
                className={[
                  'flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold transition-all',
                  st.status === 'completed'
                    ? 'bg-blue-50 text-blue-700 border border-blue-200'
                    : st.status === 'current'
                    ? 'bg-blue-600 text-white shadow-xs ring-2 ring-blue-100'
                    : 'bg-slate-100 text-slate-400 border border-slate-200 border-dashed',
                ].join(' ')}
              >
                <span
                  className={[
                    'w-1.5 h-1.5 rounded-full',
                    st.status === 'completed'
                      ? 'bg-blue-600'
                      : st.status === 'current'
                      ? 'bg-white'
                      : 'bg-slate-300',
                  ].join(' ')}
                />
                <span>{st.name}</span>
                {st.dateText && (
                  <span className="text-[10px] font-mono opacity-80">{st.dateText}</span>
                )}
              </div>

              {idx < stages.length - 1 && (
                <div className="w-4 h-0.5 bg-slate-200 shrink-0" />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Current Status & Latest Update */}
      <div className="rounded-2xl bg-slate-50/80 p-3.5 border border-slate-100 space-y-1.5 text-xs text-slate-700">
        <div className="flex items-center gap-2">
          <span className="font-bold text-slate-900">当前进展:</span>
          <span>{opportunity.current_step || '面试流程平稳推进中，等待下一轮通知'}</span>
        </div>
        {opportunity.last_event_at && (
          <div className="text-[11px] text-slate-400 font-mono">
            最近同步于 {new Date(opportunity.last_event_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
          </div>
        )}
      </div>

      {/* Conditional Next Event & Next Action Banner */}
      {!isClosed && (
        <div className="pt-1 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-1.5 text-slate-600">
            <Calendar size={13} className="text-indigo-600" />
            <span className="font-semibold text-slate-700">下一阶段:</span>
            <span className="font-mono text-slate-800">技术一面</span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onHandleAction?.(opportunity)}
              className="inline-flex items-center gap-1 px-3.5 py-1.5 rounded-xl text-xs font-bold bg-blue-600 hover:bg-blue-700 text-white shadow-xs transition-all cursor-pointer"
            >
              <span>进入面试备战</span>
              <ArrowRight size={12} />
            </button>
          </div>
        </div>
      )}
    </article>
  );
}
