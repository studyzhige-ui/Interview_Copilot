import { useState } from 'react';
import { Archive, ChevronDown, ChevronUp, Award } from 'lucide-react';
import type { JobOpportunity } from '@/types/career';
import { OpportunityCard } from './OpportunityCard';

export function ClosedOpportunitiesStack({
  opportunities = [],
}: {
  opportunities: JobOpportunity[];
}) {
  const [expanded, setExpanded] = useState(false);

  if (opportunities.length === 0) return null;

  const acceptedCount = opportunities.filter((o) => o.outcome === 'accepted').length;

  return (
    <div className="rounded-3xl border border-slate-200/90 bg-white/70 backdrop-blur-md p-5 shadow-2xs space-y-4 transition-all">
      {/* Stack Header Trigger */}
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="w-full flex items-center justify-between text-left cursor-pointer group"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-slate-100 text-slate-500 group-hover:bg-blue-50 group-hover:text-blue-600 flex items-center justify-center transition-colors">
            <Archive size={16} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-800 group-hover:text-blue-900 transition-colors">
                已关闭应聘记录
              </h3>
              <span className="text-xs font-mono font-bold text-slate-500 bg-slate-100 px-2 py-0.5 rounded-full">
                {opportunities.length}
              </span>
              {acceptedCount > 0 && (
                <span className="inline-flex items-center gap-1 text-xs font-bold text-amber-800 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200">
                  <Award size={12} className="text-amber-600" />
                  <span>{acceptedCount} 个 Offer 达成</span>
                </span>
              )}
            </div>
            <p className="text-[11px] text-slate-400 mt-0.5">已结束、斩获 Offer 或自主退出的历史求职进程</p>
          </div>
        </div>

        <div className="flex items-center gap-1 text-xs font-semibold text-slate-400 group-hover:text-blue-600 transition-colors">
          <span>{expanded ? '收起记录' : '展开查看'}</span>
          {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        </div>
      </button>

      {/* Expanded Opportunities List */}
      {expanded && (
        <div className="space-y-4 pt-2 border-t border-slate-100 animate-in fade-in duration-200">
          {opportunities.map((opp) => (
            <OpportunityCard key={opp.id} opportunity={opp} />
          ))}
        </div>
      )}
    </div>
  );
}
