import { useNavigate } from 'react-router-dom';
import { Bot, Clock, CheckCircle2, ChevronRight, Cpu } from 'lucide-react';
import type { PersistentTask } from '@/types/persistentTask';

interface AgentTaskSummary {
  id: string;
  kind: 'running' | 'scheduled' | 'completed';
  title: string;
  detail: string;
  timeInfo: string;
}

export function CopilotDynamicWidget({
  tasks = [],
  loading = false,
}: {
  tasks?: PersistentTask[];
  loading?: boolean;
}) {
  const navigate = useNavigate();

  const summaries: AgentTaskSummary[] = tasks.length > 0
    ? tasks.map((t) => ({
        id: t.id,
        kind: (t.state === 'active' ? 'running' : t.trigger_kind === 'scheduled' ? 'scheduled' : 'completed') as AgentTaskSummary['kind'],
        title: t.title,
        detail: t.instruction,
        timeInfo: t.state === 'active' ? '运行中' : t.trigger_kind === 'scheduled' ? '定时计划' : '已就绪',
      }))
    : [
        {
          id: 'agent-act-1',
          kind: 'running',
          title: '岗位机会与 JD 匹配度深度分析',
          detail: '正在对比腾讯后端开发要求与你当前的经历事实库',
          timeInfo: '运行中 · 42s',
        },
        {
          id: 'agent-act-2',
          kind: 'scheduled',
          title: '每日求职邮件与面试邀约自动巡检',
          detail: '将在有新的 HR 来信或面试通知时主动生成待确认卡片',
          timeInfo: '每天 09:00',
        },
        {
          id: 'agent-act-3',
          kind: 'completed',
          title: '已生成字节二面高频考点针对性速查',
          detail: '包含 5 个分布式事务与缓存一致性核心追问应对方案',
          timeInfo: '15 分钟前',
        },
      ];

  const getKindBadge = (kind: AgentTaskSummary['kind']) => {
    switch (kind) {
      case 'running':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-blue-50 text-blue-700 border border-blue-200">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-600 animate-pulse" />
            <span>运行中</span>
          </span>
        );
      case 'scheduled':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-purple-50 text-purple-700 border border-purple-200">
            <Clock size={9} />
            <span>计划调度</span>
          </span>
        );
      case 'completed':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
            <CheckCircle2 size={9} />
            <span>已就绪</span>
          </span>
        );
    }
  };

  return (
    <div className="h-full flex flex-col justify-between select-none pl-3">
      {/* Sector Header */}
      <div className="flex items-center justify-between pb-2.5 mb-2 border-b border-slate-200/60">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-purple-50 text-purple-600 flex items-center justify-center font-bold">
            <Bot size={14} />
          </div>
          <div>
            <h2 className="text-xs font-bold text-slate-900 tracking-tight">Copilot 工作</h2>
            <p className="text-[10px] text-slate-400">Agent 正在为你执行的后台任务与调度</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => navigate('/activities')}
          className="text-[11px] text-blue-600 hover:text-blue-800 font-semibold flex items-center gap-0.5 cursor-pointer"
        >
          <span>活动中心</span>
          <ChevronRight size={11} />
        </button>
      </div>

      {/* Task List */}
      <div className="flex-1 overflow-y-auto pr-1 space-y-1.5 scrollbar-thin">
        {loading ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-400 text-xs gap-2">
            <Cpu size={16} className="animate-spin text-purple-500" />
            <span>正在连接 Copilot 工作流…</span>
          </div>
        ) : (
          summaries.slice(0, 3).map((item) => (
            <div
              key={item.id}
              onClick={() => navigate('/activities')}
              className="group p-2 rounded-xl bg-white/60 hover:bg-white border border-slate-200/60 hover:border-purple-300 shadow-2xs hover:shadow-xs transition-all cursor-pointer"
            >
              <div className="flex items-center justify-between gap-1.5">
                <span className="text-[11px] font-bold text-slate-800 group-hover:text-purple-900 truncate">
                  {item.title}
                </span>
                {getKindBadge(item.kind)}
              </div>

              <p className="text-[10px] text-slate-500 mt-0.5 line-clamp-1">
                {item.detail}
              </p>

              <div className="mt-1 flex items-center justify-between text-[9px] text-slate-400 font-mono">
                <span>{item.timeInfo}</span>
                <span className="text-purple-600 font-sans font-semibold group-hover:underline">
                  控制台 →
                </span>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Subtle Footer */}
      <div className="pt-2 border-t border-slate-200/50 flex items-center justify-between text-[10px] text-slate-400">
        <span>全流程自主代理工作台</span>
        <span className="text-purple-600 font-medium">透明可控</span>
      </div>
    </div>
  );
}
