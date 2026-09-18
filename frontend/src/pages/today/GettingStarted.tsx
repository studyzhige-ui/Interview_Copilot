import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { collaborationStarters } from '@/lib/collaborationStarters';
import type { WorkspaceOverview } from '@/api/workspace';

const workStatus = {
  not_started: '等待开始', pending: '等待执行', running: '正在处理',
  waiting: '需要你补充或确认', completed: '本轮已结束', failed: '执行未完成，查看原因',
  cancelled: '已停止', blocked: '需要调整后继续', unknown: '查看最新进展',
};

export function GettingStarted({ overview }: { overview: WorkspaceOverview }) {
  return <section className="getting-started" aria-label="开始与继续">
    <div className="getting-started-intro">
      <p className="today-dateline">{overview.recent_work.length ? '接着上次的进展' : '第一次使用，从一件具体的事开始'}</p>
      <h2>{overview.recent_work.length ? '继续一件事，或开始新的准备' : '你现在最想解决什么？'}</h2>
      <p>选一个目标，与 Copilot 一起完成。你可以先描述情况，再补充资料，不必先填完所有页面。</p>
    </div>
    {overview.recent_work.length > 0 && <div className="workspace-recent">
      <h3>最近的协作</h3>
      {overview.recent_work.map((work) => <Link key={work.session_id} to={`/general-chat?session=${encodeURIComponent(work.session_id)}`}>
        <span><strong>{work.title}</strong><small>{workStatus[work.status]}</small></span><ArrowRight size={17} />
      </Link>)}
    </div>}
    <div className="workspace-start-options">
      {Object.entries(collaborationStarters).map(([id, starter], index) => <Link key={id} to={`/general-chat?start=${id}`}>
        <span className="workspace-option-number">0{index + 1}</span>
        <span><strong>{starter.title}</strong><small>{starter.detail}</small></span><ArrowRight size={18} />
      </Link>)}
    </div>
    <p className="workspace-start-note">{overview.has_resume ? '已保存的简历可以在资料中查看和更新。' : '有简历或岗位描述的话，可以进入协作后通过附件提供。'} <Link to="/career-profile">查看我的资料</Link></p>
    <p className="workspace-start-note">协作过程会保留在对话中；保存的材料在「资料」，岗位进展在「求职」，练习与复盘在「面试」。</p>
  </section>;
}
