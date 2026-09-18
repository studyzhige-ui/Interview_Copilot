import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowRight, ArrowUpRight, CalendarDays, RefreshCw } from 'lucide-react';
import { getNextActionAgenda } from '@/api/careerInsights';
import { listJobOpportunities } from '@/api/careerProcess';
import { copilotObjectHandoffHref } from '@/lib/copilotObjectReference';
import type { NextActionAgendaItem } from '@/types/career';
import { getWorkspaceOverview } from '@/api/workspace';
import { GettingStarted } from './GettingStarted';

type View = 'attention' | 'upcoming' | 'suggested';
const views: Array<{ id: View; label: string }> = [
  { id: 'attention', label: '需要处理' }, { id: 'upcoming', label: '接下来' }, { id: 'suggested', label: '待采纳建议' },
];
const phases = { pending_application: '待投递', applied: '已投递', in_process: '推进中', offer: '收到 Offer' };

function agendaView(item: NextActionAgendaItem): View {
  if (item.action.status === 'suggested' || item.bucket === 'suggested') return 'suggested';
  if (item.overdue || item.bucket === 'today' || item.bucket === 'conflict') return 'attention';
  return 'upcoming';
}

function actionTime(item: NextActionAgendaItem) {
  const value = item.action.starts_at ?? item.action.due_at;
  if (!value) return '时间待定';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '时间待核对';
  return date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}

function LoadError({ subject, retry, pending }: { subject: string; retry: () => void; pending: boolean }) {
  return <div className="today-error" role="alert">
    <strong>暂时无法读取{subject}</strong>
    <p>请检查服务连接后重试。已有记录不会因此改变。</p>
    <button type="button" onClick={retry} disabled={pending}><RefreshCw size={14} />{pending ? '正在重试…' : '重新加载'}</button>
  </div>;
}

export function TodayPage() {
  const [view, setView] = useState<View>('attention');
  const workspace = useQuery({ queryKey: ['workspace'], queryFn: getWorkspaceOverview, retry: false, refetchInterval: 15000 });
  const agenda = useQuery({ queryKey: ['next-action-agenda'], queryFn: getNextActionAgenda, retry: false });
  const jobs = useQuery({ queryKey: ['today-job-opportunities'], queryFn: () => listJobOpportunities(), retry: false });
  const items = (agenda.data?.items ?? []).filter((item) => item.action.status === 'planned' || item.action.status === 'suggested');
  const visibleItems = items.filter((item) => agendaView(item) === view);
  const activeJobs = (jobs.data ?? []).filter((job) => !job.outcome && !job.archived_at);
  const isStarting = workspace.isSuccess && workspace.data.active_opportunities === 0 && workspace.data.open_actions === 0
    && agenda.isSuccess && items.length === 0 && jobs.isSuccess && activeJobs.length === 0;
  return <div className="today-page">
    <header className="today-heading">
      <div>
        <p className="today-dateline">{new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}</p>
        <h1>今天，从这里开始。</h1>
        <p className="today-intro">明确目标、准备材料、练习面试，一次推进一件事。</p>
      </div>
      <Link className="today-primary-link" to="/career-process">管理求职机会 <ArrowUpRight size={16} /></Link>
    </header>
    {workspace.isPending ? <p role="status">正在读取你的准备进度…</p> : workspace.isError
      ? <LoadError subject="协作进度" pending={workspace.isFetching} retry={() => { void workspace.refetch(); }} />
      : <GettingStarted overview={workspace.data} />}
    {!isStarting && <div className="today-layout">
      <section className="today-agenda" aria-labelledby="agenda-heading">
        <div className="today-section-heading"><h2 id="agenda-heading">你的安排</h2><CalendarDays size={18} /></div>
        <div className="today-filters" role="group" aria-label="筛选安排">
          {views.map((tab) => <button key={tab.id} type="button" aria-pressed={view === tab.id} onClick={() => setView(tab.id)}>
            {tab.label}{agenda.isSuccess && <span>{items.filter((item) => agendaView(item) === tab.id).length}</span>}
          </button>)}
        </div>
        {agenda.isPending ? <p className="today-loading" role="status">正在读取安排…</p>
          : agenda.isError ? <LoadError subject="安排" pending={agenda.isFetching} retry={() => { void agenda.refetch(); }} />
          : visibleItems.length ? <ul className="today-actions">{visibleItems.map((item) => {
            const job = jobs.data?.find((candidate) => candidate.id === item.action.job_opportunity_id);
            return <li key={item.action.id}>
              <div className="today-action-time"><span>{actionTime(item)}</span>
                {item.overdue && <small className="today-overdue">已逾期</small>}
                {item.conflict_action_ids.length > 0 && <small className="today-overdue">时间冲突</small>}
              </div>
              <div className="today-action-body"><h3>{item.action.content}</h3>
                <p>{job ? `${job.company_name} · ${job.job_title}` : item.action.job_opportunity_id ? '关联求职机会' : '个人安排'}{view === 'suggested' ? ' · 尚未加入计划' : ''}</p>
                <Link to={copilotObjectHandoffHref('next_action', item.action.id, item.action.content)}>与 Copilot 讨论 <ArrowUpRight size={12} /></Link>
              </div>
              <Link to={'/career-insights#action-' + encodeURIComponent(item.action.id)} className="today-row-link" aria-label={`查看安排：${item.action.content}`}>查看 <ArrowRight size={14} /></Link>
            </li>;
          })}</ul> : <div className="today-empty">
            <span className="today-empty-rule" />
            <h3>{view === 'attention' ? '眼下没有需要处理的安排' : view === 'upcoming' ? '还没有后续安排' : '没有待采纳的建议'}</h3>
            <p>{view === 'attention' ? '可以继续准备面试，或看看正在跟进的机会。' : view === 'upcoming' ? '在求职进程中记录下一步，安排会显示在这里。' : '只有你采纳的建议，才会成为正式计划。'}</p>
            <Link to={view === 'attention' ? '/mock' : '/career-process'}>{view === 'attention' ? '开始一次模拟面试' : '前往求职进程'} <ArrowRight size={15} /></Link>
          </div>}
        <Link className="today-section-footer" to="/career-insights">查看全部行动与决策 <ArrowRight size={15} /></Link>
      </section>
      <aside className="today-opportunities" aria-labelledby="opportunities-heading">
        <div className="today-section-heading"><h2 id="opportunities-heading">正在跟进</h2>{jobs.isSuccess && <span>{activeJobs.length} 个机会</span>}</div>
        {jobs.isPending ? <p className="today-loading" role="status">正在读取机会…</p>
          : jobs.isError ? <LoadError subject="求职机会" pending={jobs.isFetching} retry={() => { void jobs.refetch(); }} />
          : !activeJobs.length ? <div className="today-empty today-empty-small"><h3>从一个心仪的岗位开始</h3><p>记下公司和岗位，后续进展、准备和材料就有了归处。</p><Link to="/career-process">添加求职机会 <ArrowRight size={15} /></Link></div>
          : <ul className="today-job-list">{activeJobs.slice(0, 5).map((job) => <li key={job.id}>
            <div><span className="today-company">{job.company_name}</span><small>{phases[job.phase]}</small></div>
            <Link to={`/career-process?opportunity=${encodeURIComponent(job.id)}`}>{job.job_title}<ArrowUpRight size={14} /></Link>
            {job.current_step && <p>{job.current_step}</p>}
          </li>)}</ul>}
        <Link className="today-section-footer" to="/career-process">全部求职机会 <ArrowRight size={15} /></Link>
      </aside>
    </div>}
    {!isStarting && <section className="today-next" aria-label="继续准备">
      <div><span className="today-dateline">每一次准备，都算数</span><h2>为下一次机会做好准备</h2></div>
      <Link to="/mock"><span><strong>练一次面试</strong><small>带着简历和岗位要求，进入模拟问答</small></span><ArrowUpRight size={19} /></Link>
      <Link to="/career-profile"><span><strong>整理个人档案</strong><small>把经历与优势，变成可复用的资料</small></span><ArrowUpRight size={19} /></Link>
    </section>}
  </div>;
}

