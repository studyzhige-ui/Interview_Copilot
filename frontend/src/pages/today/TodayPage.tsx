import { useState } from 'react';
import {
  Sparkles,
  Send,
  CheckCircle2,
  ChevronRight,
  ArrowUpRight,
  Check,
  Building2,
  Cpu,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { listJobOpportunities } from '@/api/careerProcess';
import { listPersistentTasks } from '@/api/persistentTasks';
import { toast } from '@/store/uiStore';

interface TaskConfirmation {
  id: number;
  category: string;
  title: string;
  desc: string;
  copilotTip: string;
}

const INITIAL_TASKS: TaskConfirmation[] = [
  {
    id: 1,
    category: '外部动作审批',
    title: '腾讯 HR 邮件：确认技术一面面试时间',
    desc: '收到腾讯招聘团队发来的面试邀约，建议面试时间为下周二（8月19日）上午 10:30。',
    copilotTip: 'Copilot 已检测到该时间段你的日历暂无冲突，是否授权 Copilot 发送确认回信？',
  },
  {
    id: 2,
    category: '进展事实确认',
    title: '字节跳动：更新应聘进展至「二面通过」',
    desc: '系统检测到面试反馈邮件，确认将状态推进至 HR 面与 Offer 阶段。',
    copilotTip: '是否同步更新应聘状态库并拉取 HR 面考点？',
  },
  {
    id: 3,
    category: '档案更新确认',
    title: '求职档案：同步在面试中确证的项目亮点',
    desc: '根据最新复盘录音提炼并确证了「高并发网关链路优化与熔断降级」技术事实。',
    copilotTip: '是否将该项已确证的经历沉淀到个人核心档案？',
  },
];

function getGreetingText() {
  const hour = new Date().getHours();
  if (hour < 6) return '夜深了';
  if (hour < 11) return '早上好';
  if (hour < 14) return '中午好';
  if (hour < 18) return '下午好';
  return '晚上好';
}

export function TodayPage() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<TaskConfirmation[]>(INITIAL_TASKS);
  const [comment, setComment] = useState('');
  const [dismissingId, setDismissingId] = useState<number | null>(null);
  const [promptText, setPromptText] = useState('');

  const opportunitiesQuery = useQuery({
    queryKey: ['today-opportunities'],
    queryFn: () => listJobOpportunities(false),
  });

  const tasksQuery = useQuery({
    queryKey: ['today-persistent-tasks'],
    queryFn: () => listPersistentTasks(),
  });

  const greeting = getGreetingText();
  const opportunities = (opportunitiesQuery.data ?? []).filter((o) => !o.archived_at && !o.outcome);
  const runningTasks = (tasksQuery.data ?? []).filter((t) => t.state === 'active');

  const handleConfirm = (id: number) => {
    setDismissingId(id);
    setTimeout(() => {
      setTasks((prev) => prev.filter((t) => t.id !== id));
      setDismissingId(null);
      setComment('');
      toast.success('已确认并由 Agent 执行下一步');
    }, 280);
  };

  const handleStartCopilot = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!promptText.trim()) {
      navigate('/general-chat');
      return;
    }
    navigate(`/general-chat?prompt=${encodeURIComponent(promptText.trim())}`);
  };

  return (
    <div className="relative w-full h-full bg-[#F8FAFC] overflow-hidden flex flex-col font-sans select-none">
      {/* 主画布区域 */}
      <main className="relative flex-1 w-full h-full">
        {/* 背景内凹流体曲面分割线（SVG 路径精确还原草图） */}
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none z-0"
          xmlns="http://www.w3.org/2000/svg"
        >
          {/* 四向内凹流体曲线向中心收拢 */}
          <path
            d="M 50% 0 C 50% 30% 30% 45% 20% 50%"
            stroke="#E2E8F0"
            strokeWidth="1.5"
            fill="none"
          />
          <path
            d="M 50% 0 C 50% 30% 70% 45% 80% 50%"
            stroke="#E2E8F0"
            strokeWidth="1.5"
            fill="none"
          />
          <path
            d="M 50% 100% C 50% 70% 30% 55% 20% 50%"
            stroke="#E2E8F0"
            strokeWidth="1.5"
            fill="none"
          />
          <path
            d="M 50% 100% C 50% 70% 70% 55% 80% 50%"
            stroke="#E2E8F0"
            strokeWidth="1.5"
            fill="none"
          />
        </svg>

        {/* 四象限内容层（自然贴合，主动向外推开以避让中心 Copilot 岛） */}
        <div className="relative w-full h-full grid grid-cols-2 grid-rows-2 p-8 lg:p-10 z-10">
          
          {/* 象限 1: 左上「下一步」 */}
          <div className="flex flex-col pr-24 pb-16 justify-between">
            <div>
              <div className="flex items-center gap-2 text-slate-900 font-bold text-base md:text-lg mb-1">
                <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                下一步
              </div>
              <p className="text-xs text-slate-400">已确认且需你亲自推进的真实事项</p>
            </div>

            {opportunities.length > 0 ? (
              <div className="flex-1 flex flex-col justify-center space-y-2 py-2">
                {opportunities.slice(0, 2).map((opp) => (
                  <div
                    key={opp.id}
                    onClick={() => navigate(`/career?opportunity=${opp.id}`)}
                    className="p-2.5 rounded-xl bg-white/70 hover:bg-white border border-slate-200/70 hover:border-blue-300 shadow-2xs hover:shadow-xs transition-all cursor-pointer flex items-center justify-between gap-2 group"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-bold text-slate-800 group-hover:text-blue-600 truncate">
                        推进 {opp.current_step || '面试'} · {opp.company_name}
                      </div>
                      <div className="text-[10px] text-slate-400 truncate mt-0.5">
                        {opp.job_title} · 微信事业群
                      </div>
                    </div>
                    <span className="text-[10px] font-mono font-semibold text-amber-700 bg-amber-50 px-2 py-0.5 rounded border border-amber-200/60 shrink-0">
                      今天 23:59
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center flex-1 text-center py-4">
                <CheckCircle2 className="w-8 h-8 text-emerald-500 mb-2 stroke-[1.5]" />
                <p className="text-sm font-medium text-slate-700">当前没有需要立即推进的动作</p>
                <p className="text-xs text-slate-400 mt-0.5">所有事项均已按计划完成</p>
              </div>
            )}

            <div className="text-[10px] text-slate-400 pt-1 border-t border-slate-100/80 flex items-center justify-between">
              <span>点击直达工作区</span>
              <span className="text-blue-600 font-medium">带入岗位上下文</span>
            </div>
          </div>

          {/* 象限 2: 右上「待我确认」（手风琴堆叠消除交互） */}
          <div className="flex flex-col pl-24 pb-16 justify-between">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-base md:text-lg">
                <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                待我确认
              </div>
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-100/80 text-amber-700">
                {tasks.length} 待决
              </span>
            </div>

            {/* 堆叠队列 */}
            <div className="relative flex-1 flex flex-col justify-center py-1">
              {tasks.length > 0 ? (
                <div className="space-y-2">
                  {/* 最顶层：完全展开 */}
                  {tasks[0] && (
                    <div
                      className={[
                        'bg-white/90 backdrop-blur-sm border border-slate-200/80 rounded-2xl p-4 shadow-2xs space-y-2 transition-all duration-300 transform',
                        dismissingId === tasks[0].id
                          ? 'translate-x-16 opacity-0 scale-95 pointer-events-none'
                          : 'translate-x-0 opacity-100 scale-100',
                      ].join(' ')}
                    >
                      <div className="text-[10px] font-medium text-amber-600 bg-amber-50 inline-block px-2 py-0.5 rounded">
                        {tasks[0].category}
                      </div>
                      <h3 className="text-xs font-bold text-slate-800 leading-snug">{tasks[0].title}</h3>
                      <p className="text-[11px] text-slate-600 leading-relaxed">{tasks[0].desc}</p>
                      <div className="bg-amber-50/60 border border-amber-100/80 rounded-lg p-2 text-[10px] text-amber-800">
                        💡 {tasks[0].copilotTip}
                      </div>
                      <div className="flex gap-2 pt-1">
                        <input
                          type="text"
                          value={comment}
                          onChange={(e) => setComment(e.target.value)}
                          placeholder="补充意见或修改建议..."
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleConfirm(tasks[0].id);
                          }}
                          className="flex-1 text-[11px] bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-1.5 outline-none focus:border-blue-400 transition-colors"
                        />
                        <button
                          type="button"
                          onClick={() => handleConfirm(tasks[0].id)}
                          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 active:scale-95 text-white text-[11px] font-medium rounded-lg transition-all whitespace-nowrap shadow-xs cursor-pointer flex items-center gap-1 shrink-0"
                        >
                          <Check size={12} />
                          <span>确认并执行</span>
                        </button>
                      </div>
                    </div>
                  )}

                  {/* 下方折叠队列项 */}
                  {tasks.slice(1).map((task) => (
                    <div
                      key={task.id}
                      onClick={() => {
                        const remaining = tasks.filter((t) => t.id !== task.id);
                        setTasks([task, ...remaining]);
                      }}
                      className="bg-white/60 border border-slate-200/60 rounded-xl px-3 py-1.5 flex items-center justify-between text-[11px] text-slate-600 hover:bg-white/90 cursor-pointer transition-all shadow-2xs"
                    >
                      <span className="truncate">{task.title}</span>
                      <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center text-xs text-slate-400">
                  <CheckCircle2 size={20} className="text-emerald-500 mb-1" />
                  <span>已全部处理完毕</span>
                </div>
              )}
            </div>

            <div className="text-[10px] text-slate-400 pt-1 border-t border-slate-100/80 flex items-center justify-between">
              <span>单焦点决策流转</span>
              <span className="text-amber-800 font-semibold">无静默越权</span>
            </div>
          </div>

          {/* 象限 3: 左下「求职动态」 */}
          <div className="flex flex-col pr-24 pt-16 border-t border-slate-100/60 justify-between">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-sm">
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                求职动态
              </div>
              <span
                onClick={() => navigate('/career')}
                className="text-xs text-slate-400 hover:text-blue-600 cursor-pointer flex items-center gap-0.5"
              >
                查看全部 <ArrowUpRight className="w-3 h-3" />
              </span>
            </div>
            <div className="space-y-1.5 text-xs text-slate-600 flex-1 flex flex-col justify-center">
              <div className="flex items-center justify-between py-1.5 border-b border-slate-100">
                <span className="font-medium text-slate-700 flex items-center gap-1">
                  <Building2 size={12} className="text-slate-400" />
                  <span>腾讯科技 · 高级后端开发工程师</span>
                </span>
                <span className="text-emerald-600 font-medium">技术初面已通过</span>
              </div>
              <div className="flex items-center justify-between py-1.5 border-b border-slate-100">
                <span className="font-medium text-slate-700 flex items-center gap-1">
                  <Building2 size={12} className="text-slate-400" />
                  <span>字节跳动 · 全栈架构师</span>
                </span>
                <span className="text-blue-600 font-medium">面试已预约下周三</span>
              </div>
            </div>
            <div className="text-[10px] text-slate-400 pt-1 flex items-center justify-between">
              <span>真实外部事件流</span>
              <span className="text-emerald-600 font-medium">实战溯源</span>
            </div>
          </div>

          {/* 象限 4: 右下「Copilot 工作」 */}
          <div className="flex flex-col pl-24 pt-16 border-t border-slate-100/60 justify-between">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-sm">
                <span className="w-2 h-2 rounded-full bg-purple-500" />
                Copilot 工作
              </div>
              <span
                onClick={() => navigate('/activities')}
                className="text-xs text-slate-400 hover:text-blue-600 cursor-pointer flex items-center gap-0.5"
              >
                活动中心 <ArrowUpRight className="w-3 h-3" />
              </span>
            </div>
            <div className="space-y-2 text-xs flex-1 flex flex-col justify-center">
              <div
                onClick={() => navigate('/activities')}
                className="bg-white/70 hover:bg-white border border-slate-200/60 rounded-xl p-2.5 flex items-center justify-between cursor-pointer transition-all shadow-2xs"
              >
                <div className="truncate pr-2">
                  <div className="font-medium text-slate-700 flex items-center gap-1">
                    <Cpu size={12} className="text-purple-600" />
                    <span>岗位机会与 JD 匹配度深度分析</span>
                  </div>
                  <div className="text-[11px] text-slate-400 mt-0.5">正在对比腾讯后端要求与经历事实库</div>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 text-[10px] font-semibold shrink-0">
                  {runningTasks.length > 0 ? '运行中' : '运行中'}
                </span>
              </div>
            </div>
            <div className="text-[10px] text-slate-400 pt-1 flex items-center justify-between">
              <span>全流程自主代理工作台</span>
              <span className="text-purple-600 font-medium">透明可控</span>
            </div>
          </div>

        </div>

        {/* 核心锚点：中央 Copilot 胶囊浮岛（完美嵌合在四个内凹弧线中心） */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center pointer-events-auto">
          <div className="w-[380px] md:w-[420px] bg-white/95 backdrop-blur-xl border border-blue-200/80 shadow-xl shadow-blue-500/10 rounded-2xl p-4 flex flex-col items-center gap-2.5 ring-4 ring-blue-50/50">
            <div className="text-center">
              <h2 className="text-base font-bold text-slate-800">{greeting}</h2>
              <p className="text-xs text-slate-500">
                今天有 <span className="text-blue-600 font-semibold">{tasks.length}</span> 件事项需要推进
              </p>
            </div>
            <form onSubmit={handleStartCopilot} className="w-full flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-xl px-3 py-1.5">
              <Sparkles className="w-4 h-4 text-blue-500 shrink-0" />
              <input
                type="text"
                value={promptText}
                onChange={(e) => setPromptText(e.target.value)}
                placeholder="向 Copilot 提问、指派任务或开启对话…"
                className="flex-1 bg-transparent text-xs outline-none text-slate-700 placeholder-slate-400"
              />
              <button
                type="submit"
                className="px-2.5 py-1.5 bg-blue-600 hover:bg-blue-700 active:scale-95 text-white text-xs font-medium rounded-lg transition-colors cursor-pointer flex items-center gap-1 shrink-0"
              >
                <Send className="w-3.5 h-3.5" />
                <span>发送</span>
              </button>
            </form>
          </div>
        </div>
      </main>
    </div>
  );
}
