import { useMemo, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { AlertTriangle, BriefcaseBusiness, ListChecks, UserRound } from 'lucide-react';

import { getCareerProfile } from '@/api/careerProfile';
import { listJobOpportunities, listNextActions } from '@/api/careerProcess';

/**
 * A deliberately thin read projection for the Copilot workspace.
 *
 * CareerProfile, JobOpportunity and NextAction remain owned by their domain
 * services. This component only reads those canonical APIs and derives a
 * bounded, refreshable summary; it is not a second CareerState store.
 */
export function CopilotStatusSummary() {
  const profile = useQuery({
    queryKey: ['career-profile'],
    queryFn: getCareerProfile,
    retry: false,
  });
  const opportunities = useQuery({
    queryKey: ['job-opportunities'],
    queryFn: () => listJobOpportunities(false),
  });
  const actions = useQuery({
    queryKey: ['next-actions'],
    queryFn: () => listNextActions(['suggested', 'planned']),
  });

  const summary = useMemo(() => {
    // Derive time-sensitive status at the newest authoritative query refresh.
    // This stays deterministic within a render and advances whenever any owner
    // projection is refreshed.
    const now = Math.max(
      profile.dataUpdatedAt,
      opportunities.dataUpdatedAt,
      actions.dataUpdatedAt,
    );
    const activeDirections = profile.data?.directions.filter(
      (direction) => direction.lifecycle === 'active',
    ).length ?? 0;
    const openOpportunities = opportunities.data?.filter(
      (opportunity) => !opportunity.outcome && !opportunity.archived_at,
    ).length ?? 0;
    const openActions = actions.data ?? [];
    const overdue = openActions.filter((action) => {
      const target = action.due_at ?? action.starts_at;
      return target ? new Date(target).getTime() < now : false;
    }).length;
    const blockers: string[] = [];
    if (profile.isSuccess && activeDirections === 0) {
      blockers.push('还没有启用的求职方向');
    }
    if (overdue > 0) blockers.push(`${overdue} 项行动已到期`);
    return { activeDirections, openOpportunities, openActions: openActions.length, blockers };
  }, [
    actions.data,
    actions.dataUpdatedAt,
    opportunities.data,
    opportunities.dataUpdatedAt,
    profile.data,
    profile.dataUpdatedAt,
    profile.isSuccess,
  ]);

  const loading = profile.isPending || opportunities.isPending || actions.isPending;
  const failed = profile.isError || opportunities.isError || actions.isError;

  return (
    <section
      aria-label="求职状态总览"
      className="border-b border-stone-100 bg-stone-50/70 px-3 py-3"
    >
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-stone-700">当前状态</h2>
        <Link to="/career-process" className="text-[11px] text-primary-600 hover:text-primary-700">
          查看进程
        </Link>
      </div>
      {loading ? (
        <p className="text-xs text-stone-400">正在读取最新求职状态…</p>
      ) : failed ? (
        <p className="text-xs text-danger-600">状态暂时无法读取，聊天仍可正常使用。</p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-1.5">
            <StatusLink
              to="/career-profile"
              icon={<UserRound size={13} />}
              value={summary.activeDirections}
              label="方向"
            />
            <StatusLink
              to="/career-process"
              icon={<BriefcaseBusiness size={13} />}
              value={summary.openOpportunities}
              label="机会"
            />
            <StatusLink
              to="/career-process"
              icon={<ListChecks size={13} />}
              value={summary.openActions}
              label="行动"
            />
          </div>
          <div className="mt-2">
            {summary.blockers.length ? (
              <Link
                to={summary.activeDirections === 0 ? '/career-profile' : '/career-process'}
                className="flex items-start gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] leading-4 text-amber-800"
              >
                <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                <span>{summary.blockers.join('；')}</span>
              </Link>
            ) : (
              <p className="text-[11px] text-stone-500">没有需要立即处理的阻塞项。</p>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function StatusLink({
  to,
  icon,
  value,
  label,
}: {
  to: string;
  icon: ReactNode;
  value: number;
  label: string;
}) {
  return (
    <Link
      to={to}
      className="rounded-lg border border-stone-200 bg-white px-2 py-1.5 text-stone-600 hover:border-primary-200 hover:text-primary-700"
    >
      <span className="flex items-center gap-1 text-[10px]">{icon}{label}</span>
      <strong className="mt-0.5 block text-sm font-semibold text-stone-800">{value}</strong>
    </Link>
  );
}
