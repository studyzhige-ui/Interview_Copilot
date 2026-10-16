import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowRight, BriefcaseBusiness, Mic, UserRound } from 'lucide-react';
import { getNextActionAgenda } from '@/api/careerInsights';
import { getWorkspaceOverview } from '@/api/workspace';
import type { NextActionAgendaItem } from '@/types/career';
import { PendingConfirmations } from './PendingConfirmations';
import { isScheduledAction } from '@/lib/schedule';

function needsAttention(item: NextActionAgendaItem) {
  return item.overdue || item.bucket === 'today' || item.bucket === 'conflict';
}

function actionTime(item: NextActionAgendaItem) {
  const value = item.action.starts_at ?? item.action.due_at;
  if (!value) return '时间待定';
  return new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}

const workStatus = { running: '正在处理', pending: '等待执行', waiting: '等待你回复', blocked: '需要你处理', failed: '查看失败原因' };

export function TodayPage() {
  const [upcoming, setUpcoming] = useState(false);
  const workspace = useQuery({ queryKey: ['workspace'], queryFn: getWorkspaceOverview, retry: false, refetchInterval: 30000 });
  const agenda = useQuery({ queryKey: ['next-action-agenda'], queryFn: getNextActionAgenda, retry: false, refetchInterval: 30000 });
  const planned = (agenda.data?.items ?? []).filter((item) => isScheduledAction(item.action));
  const attention = planned.filter(needsAttention);
  const visible = upcoming ? planned.filter((item) => !needsAttention(item)) : attention;
  const ongoing = (workspace.data?.recent_work ?? []).filter((work) => work.status in workStatus).slice(0, 3);
  const todayInterviews = (workspace.data?.upcoming_interviews ?? []).filter((interview) => new Date(interview.starts_at).toDateString() === new Date().toDateString()).length;
  const intro = todayInterviews ? '今天有面试安排，请先检查时间与准备情况。'
    : agenda.isSuccess ? attention.length ? `${attention.length} 项安排需要处理，先完成最重要的一件。` : '今天没有紧急安排，可以继续准备下一次机会。'
      : '你的待办与进行中的协作，都在这里。';

  return <div className="today-page">
    <header className="today-heading">
      <div><p className="today-dateline">{new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}</p>
        <h1>今天</h1><p className="today-intro">{intro}</p>
      </div>
      <Link className="today-primary-link" to="/general-chat">开始新的协作 <ArrowRight size={16} /></Link>
    </header>
    <PendingConfirmations />
    <div className="today-layout">
      <section className="today-panel" aria-labelledby="agenda-heading">
        <div className="today-section-heading"><h2 id="agenda-heading">待办安排</h2><Link to="/career-calendar?view=actions">管理全部安排 <ArrowRight size={14} /></Link></div>
        <div className="today-filters" role="group" aria-label="筛选安排">
          <button type="button" aria-pressed={!upcoming} onClick={() => setUpcoming(false)}>今天与逾期{agenda.isSuccess && <span>{attention.length}</span>}</button>
          <button type="button" aria-pressed={upcoming} onClick={() => setUpcoming(true)}>接下来{agenda.isSuccess && <span>{planned.length - attention.length}</span>}</button>
        </div>
        {agenda.isPending ? <p className="today-loading" role="status">正在读取安排…</p>
          : agenda.isError ? <div className="today-empty" role="alert"><h3>安排暂时无法加载</h3><button onClick={() => { void agenda.refetch(); }}>重新加载</button></div>
          : visible.length ? <ul className="today-actions">{visible.slice(0, 6).map((item) => <li key={item.action.id}>
            <div className="today-action-time"><span>{actionTime(item)}</span>{item.overdue && <small className="today-overdue">已逾期</small>}{item.conflict_action_ids.length > 0 && <small className="today-overdue">时间冲突</small>}</div>
            <Link className="today-action-body" to={'/career-calendar?view=actions#action-' + encodeURIComponent(item.action.id)}><h3>{item.action.content}</h3><span>查看并处理 <ArrowRight size={13} /></span></Link>
          </li>)}</ul> : <div className="today-empty"><div className="today-empty-mark" aria-hidden="true">✓</div>
            <h3>{upcoming ? '还没有后续安排' : '没有需要处理的安排'}</h3><p>{upcoming ? '在求职进程中记录下一步，或与 Copilot 讨论计划。' : '可以练一次面试，或继续尚未完成的协作。'}</p>
            <Link to={upcoming ? '/career-process' : '/mock'}>{upcoming ? '记录求职进展' : '开始模拟面试'} <ArrowRight size={14} /></Link>
          </div>}
        {visible.length > 6 && <Link className="today-section-footer" to="/career-calendar?view=actions">另有 {visible.length - 6} 项安排 <ArrowRight size={14} /></Link>}
      </section>
      <aside className="today-side">
        {!!workspace.data?.upcoming_interviews.length && <section className="today-panel" aria-labelledby="interview-heading">
          <div className="today-section-heading"><h2 id="interview-heading">近期面试</h2><span className="text-xs text-stone-400">未来 30 天</span></div>
          <ul className="today-work">{workspace.data.upcoming_interviews.map((interview) => <li key={interview.id}><Link to={`/career-process?opportunity=${encodeURIComponent(interview.opportunity_id)}`}>
            <span><strong>{interview.company_name} · {interview.job_title}</strong><small>{new Date(interview.starts_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })}</small></span><ArrowRight size={15} />
          </Link></li>)}</ul>
        </section>}
        <section className="today-panel" aria-labelledby="continue-heading">
          <div className="today-section-heading"><h2 id="continue-heading">继续协作</h2><Link to="/history">历史记录 <ArrowRight size={14} /></Link></div>
          {workspace.isPending ? <p className="today-loading" role="status">正在读取协作…</p> : workspace.isError ? <div className="today-empty" role="alert"><p>协作暂时无法加载。</p><button onClick={() => { void workspace.refetch(); }}>重新加载</button></div>
            : ongoing.length ? <ul className="today-work">{ongoing.map((work) => <li key={work.session_id}><Link to={`/general-chat?session=${encodeURIComponent(work.session_id)}`}><span><strong>{work.title}</strong><small>{workStatus[work.status as keyof typeof workStatus]}</small></span><ArrowRight size={15} /></Link></li>)}</ul>
              : <p className="today-quiet">没有进行中的协作。</p>}
        </section>
        <section className="today-shortcuts" aria-label="常用入口">
          <Link to="/career-process"><BriefcaseBusiness size={18} /><span><strong>求职进展</strong><small>{workspace.isSuccess ? `${workspace.data.active_opportunities} 个岗位正在跟进` : '管理岗位与面试安排'}</small></span><ArrowRight size={15} /></Link>
          <Link to="/mock"><Mic size={18} /><span><strong>模拟面试</strong><small>选择练习目标，开始问答</small></span><ArrowRight size={15} /></Link>
          <Link to="/career-profile"><UserRound size={18} /><span><strong>个人档案</strong><small>维护已确认的经历与目标</small></span><ArrowRight size={15} /></Link>
        </section>
      </aside>
    </div>
  </div>;
}
