import { useEffect, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { getInvitationHandoff, listInvitationHandoffs, type InvitationHandoff } from '@/api/interviewInvitations';
import { reportMockClientActionUiResult } from '@/api/clientActions';
import type { MockRouteActionState } from '@/types/clientAction';
import { ManualInvitationForm } from './ManualInvitationForm';

export function InterviewHubPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const action = (location.state as MockRouteActionState | null)?.mockClientAction;
  const payload = action?.action === 'interview.preparation.open'
    && action.payload.kind === 'interview_preparation_open' ? action.payload : null;
  const id = payload?.interview_id ?? params.get('interview');
  const handoff = useQuery({ queryKey: ['interview-handoff', id], queryFn: () => getInvitationHandoff(id!),
    enabled: !!id, retry: false, staleTime: 0 });
  const list = useQuery({ queryKey: ['interview-invitations'], queryFn: listInvitationHandoffs, retry: false });
  const acknowledged = useRef(new Set<string>());
  const matches = !!payload && !!handoff.data
    && handoff.data.interview.id === payload.interview_id
    && handoff.data.opportunity.id === payload.opportunity_id
    && handoff.data.interview.version === payload.expected_interview_version
    && handoff.data.opportunity.version === payload.expected_opportunity_version
    && handoff.data.verification.operation_id === payload.source_operation_id
    && ['verified', 'reconciled'].includes(handoff.data.verification.conclusion);
  useEffect(() => {
    if (!action || !payload || acknowledged.current.has(action.action_id) || handoff.isFetching) return;
    if (!handoff.isSuccess && !handoff.isError) return;
    acknowledged.current.add(action.action_id);
    reportMockClientActionUiResult(action.action_id, matches ? { outcome: 'acknowledged' }
      : { outcome: 'failed', reason: '面试交接已变化、不可用或尚未核实，请重新获取当前状态' });
    navigate(`/interviews?interview=${encodeURIComponent(payload.interview_id)}`, { replace: true, state: null });
  }, [action, payload, matches, handoff.isSuccess, handoff.isError, handoff.isFetching, navigate]);
  return <div className="mx-auto max-w-5xl space-y-6 p-6">
    <header><h1 className="text-2xl font-semibold">面试准备</h1><p>面试安排来自已确认事实；准备、模拟和复盘共用相关资料。</p></header>
    {id && <section aria-label="当前面试交接">
      {handoff.isPending || handoff.isFetching ? <p role="status">正在核实面试安排…</p>
        : handoff.isError ? <p role="alert">当前面试不可用或无权读取，请刷新后重试。</p>
        : handoff.data && (!payload || matches) ? <InterviewSummary row={handoff.data} />
          : <p role="alert">交接版本已发生变化，没有执行原页面动作。</p>}
    </section>}
    <ManualInvitationForm onConfirmed={(result) => {
      void queryClient.invalidateQueries();
      navigate(`/interviews?interview=${encodeURIComponent(result.interview.id)}`);
    }} />
    <section aria-label="已确认的面试"><h2 className="text-lg font-semibold">已确认的面试</h2>
      {list.isPending ? <p role="status">正在读取…</p> : list.isError ? <p role="alert">无法读取面试列表，不代表没有安排。</p>
        : !list.data?.length ? <p>还没有已确认的面试邀请。</p>
          : <div className="grid gap-4">{list.data.map((row) => <InterviewSummary key={row.interview.id} row={row} />)}</div>}
    </section>
  </div>;
}
function InterviewSummary({ row }: { row: InvitationHandoff }) {
  return <article className="space-y-2 rounded-xl border bg-white p-4">
    <h3 className="font-semibold">{row.company_name} · {row.job_title}</h3>
    <p>{row.original_time_text} · {row.source_timezone}</p>
    <p className="text-sm">{row.stage_label ?? '面试'} · 状态：{row.verification.conclusion === 'verified' ? '已核实' : row.verification.conclusion}</p>
    <div className="flex flex-wrap gap-4 text-sm">
      <Link to={`/career-process?opportunity=${encodeURIComponent(row.opportunity.id)}`}>查看机会与资料</Link>
      <Link to={`/general-chat?object_kind=interview_record&object_id=${encodeURIComponent(row.interview.id)}`}>与 Copilot 准备这场面试</Link>
      <Link to="/mock">选择资料并模拟</Link>
    </div>
  </article>;
}
