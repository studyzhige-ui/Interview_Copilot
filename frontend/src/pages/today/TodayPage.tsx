import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Sparkles,
  Send,
  CheckCircle2,
  ChevronRight,
  ArrowUpRight,
} from 'lucide-react';
import { listJobOpportunities } from '@/api/careerProcess';
import { listPersistentTasks } from '@/api/persistentTasks';
import { toast } from '@/store/uiStore';

function getGreetingTimeText() {
  const hour = new Date().getHours();
  if (hour < 6) return '夜深了';
  if (hour < 11) return '早上好';
  if (hour < 14) return '中午好';
  if (hour < 18) return '下午好';
  return '晚上好';
}

interface ConfirmTask {
  id: number;
  title: string;
  desc: string;
  copilotTip: string;
  badge: string;
}

const SEED_TASKS: ConfirmTask[] = [
  {
    id: 1,
    title: '腾讯 HR 邮件：确认技术一面面试时间',
    desc: '收到腾讯招聘团队发来的面试邀约，建议面试时间为下周二（8月19日）上午 10:30。',
    copilotTip: 'Copilot 已检测到该时间段你的日历暂无冲突，是否授权 Copilot 发送确认回信？',
    badge: '外部动作审批',
  },
  {
    id: 2,
    title: '字节跳动：更新应聘进展至「二面通过」',
    desc: '系统检测到邮件更新，确认更新状态库。',
    copilotTip: '是否将该应聘机会当前阶段同步推进至「HR 面 / Offer 沟通」？',
    badge: '进展事实确认',
  },
  {
    id: 3,
    title: '求职档案：同步在面试中确证的项目亮点',
    desc: '根据最新复盘录音提炼的项目经验沉淀。',
    copilotTip: '是否将该项已确证的工程经历提炼并沉淀到你的个人核心档案中？',
    badge: '档案更新确认',
  },
];

export function TodayPage() {
  const navigate = useNavigate();
  const [inputText, setInputText] = useState('');
  const [tasks, setTasks] = useState<ConfirmTask[]>(SEED_TASKS);

  const opportunitiesQuery = useQuery({
    queryKey: ['today-opportunities'],
    queryFn: () => listJobOpportunities(false),
  });

  const persistentTasksQuery = useQuery({
    queryKey: ['today-persistent-tasks'],
    queryFn: () => listPersistentTasks(),
  });

  const greeting = getGreetingTimeText();
  const opportunities = opportunitiesQuery.data ?? [];

  // Derive next-step items from real data
  const nextStepItems = useMemo(() => {
    const active = opportunities.filter((o) => !o.outcome && !o.archived_at);
    return active.slice(0, 3).map((o) => ({
      id: o.id,
      company: o.company_name,
      title: o.job_title,
      step: o.current_step || '推进中',
    }));
  }, [opportunities]);

  // Derive career dynamic events
  const careerEvents = useMemo(() => {
    const withEvents = opportunities.filter((o) => o.last_event_at);
    if (withEvents.length > 0) {
      return withEvents.slice(0, 3).map((o) => ({
        id: o.id,
        company: o.company_name,
        title: o.job_title,
        step: o.current_step || '进展中',
        isClosed: !!(o.outcome || o.archived_at),
      }));
    }
    // Mock data for demo preview
    return [
      { id: 'm1', company: '腾讯科技', title: '高级后端开发工程师', step: '技术初面已通过', isClosed: false },
      { id: 'm2', company: '字节跳动', title: '全栈架构师', step: '面试已预约下周三', isClosed: false },
    ];
  }, [opportunities]);

  // Derive copilot work items
  const copilotWork = useMemo(() => {
    const pts = persistentTasksQuery.data ?? [];
    if (pts.length > 0) {
      return pts.slice(0, 2).map((t) => ({
        id: t.id,
        title: t.title,
        detail: t.instruction,
        state: t.state,
      }));
    }
    return [
      { id: 'cw1', title: '岗位机会与 JD 匹配度深度分析', detail: '正在对比腾讯后端要求与事实库', state: 'active' as const },
      { id: 'cw2', title: '每日求职邮件与面试邀约自动巡检', detail: '将在有新的 HR 来信时主动生成待确认卡片', state: 'paused' as const },
    ];
  }, [persistentTasksQuery.data]);

  const handleConfirm = (id: number) => {
    toast.success('已确认并执行');
    setTasks((prev) => prev.filter((t) => t.id !== id));
  };

  const handleStartCopilot = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!inputText.trim()) {
      navigate('/general-chat');
      return;
    }
    navigate(`/general-chat?prompt=${encodeURIComponent(inputText.trim())}`);
  };

  return (
    <div className="relative w-full h-full bg-[#F8FAFC] overflow-hidden flex flex-col font-sans select-none">
      {/* Main Canvas */}
      <main className="relative flex-1 w-full h-full">
        {/* Background: Organic Astroid Concave Fluid Seams (SVG) */}
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none z-0"
          viewBox="0 0 1000 700"
          preserveAspectRatio="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          {/* 4 inner-concave bezier curves radiating from edges toward center island */}
          {/* Top-left to center */}
          <path d="M 500 0 C 500 210 300 315 140 350" stroke="#E2E8F0" strokeWidth="1.5" fill="none" strokeOpacity="0.8" />
          {/* Top-right to center */}
          <path d="M 500 0 C 500 210 700 315 860 350" stroke="#E2E8F0" strokeWidth="1.5" fill="none" strokeOpacity="0.8" />
          {/* Bottom-left to center */}
          <path d="M 500 700 C 500 490 300 385 140 350" stroke="#E2E8F0" strokeWidth="1.5" fill="none" strokeOpacity="0.8" />
          {/* Bottom-right to center */}
          <path d="M 500 700 C 500 490 700 385 860 350" stroke="#E2E8F0" strokeWidth="1.5" fill="none" strokeOpacity="0.8" />

          {/* Center ambient glow */}
          <defs>
            <radialGradient id="center-glow" cx="50%" cy="50%" r="25%">
              <stop offset="0%" stopColor="#DBEAFE" stopOpacity="0.5" />
              <stop offset="100%" stopColor="#F8FAFC" stopOpacity="0" />
            </radialGradient>
          </defs>
          <circle cx="500" cy="350" r="180" fill="url(#center-glow)" />
        </svg>

        {/* Four Quadrant Content Layer — directly on canvas, no card boxes */}
        <div className="relative w-full h-full grid grid-cols-2 grid-rows-2 p-8 lg:p-10 z-10">

          {/* ─── Quadrant 1 (Top-Left): 下一步 ─── */}
          <div className="flex flex-col pr-28 pb-20">
            <div className="mb-3">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-base mb-0.5">
                <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                下一步
              </div>
              <p className="text-[11px] text-slate-400">已确认且需你亲自推进的真实事项</p>
            </div>

            {nextStepItems.length === 0 ? (
              <div className="flex flex-col items-center justify-center flex-1 text-center">
                <CheckCircle2 className="w-7 h-7 text-emerald-500 mb-1.5 stroke-[1.5]" />
                <p className="text-sm font-medium text-slate-700">当前没有需要推进的动作</p>
                <p className="text-[11px] text-slate-400 mt-0.5">所有事项均已按计划完成</p>
              </div>
            ) : (
              <div className="space-y-2 flex-1">
                {nextStepItems.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => navigate(`/career?opportunity=${item.id}`)}
                    className="flex items-center justify-between py-2 border-b border-slate-100/80 cursor-pointer group"
                  >
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-slate-800 group-hover:text-blue-700 truncate">
                        推进 {item.step}
                      </div>
                      <div className="text-[11px] text-slate-400 truncate">{item.company} · {item.title}</div>
                    </div>
                    <ArrowUpRight size={13} className="text-slate-400 group-hover:text-blue-600 shrink-0 ml-2" />
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ─── Quadrant 2 (Top-Right): 待我确认 ─── */}
          <div className="flex flex-col pl-28 pb-20">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-base">
                <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                待我确认
              </div>
              <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-amber-100/80 text-amber-700">
                {tasks.length} 待决
              </span>
            </div>

            {/* Stacked Queue with Framer Motion */}
            <div className="relative flex-1 flex flex-col justify-start overflow-hidden">
              <AnimatePresence mode="popLayout">
                {tasks.length > 0 ? (
                  tasks.map((task, idx) => {
                    if (idx === 0) {
                      // Top expanded item
                      return (
                        <motion.div
                          key={task.id}
                          layout
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, x: 120 }}
                          transition={{ duration: 0.25 }}
                          className="bg-white/80 backdrop-blur-sm border border-slate-200/70 rounded-2xl p-4 shadow-xs space-y-2.5 mb-2.5 z-10"
                        >
                          <div className="text-[10px] font-semibold text-amber-700 bg-amber-50 inline-block px-2 py-0.5 rounded-full border border-amber-200">
                            {task.badge}
                          </div>
                          <h3 className="text-xs font-bold text-slate-900 leading-snug">{task.title}</h3>
                          <p className="text-[11px] text-slate-600 leading-relaxed">{task.desc}</p>
                          <div className="bg-amber-50/70 border border-amber-100 rounded-lg p-2 text-[10px] text-amber-800 leading-snug flex items-start gap-1">
                            <Sparkles size={11} className="text-amber-600 shrink-0 mt-0.5" />
                            <span>{task.copilotTip}</span>
                          </div>
                          <div className="flex gap-2 pt-0.5">
                            <input
                              type="text"
                              placeholder="补充意见或修改建议…"
                              className="flex-1 text-[11px] bg-slate-50 border border-slate-200 rounded-lg px-3 py-1.5 outline-none focus:border-blue-400 transition-colors"
                            />
                            <button
                              type="button"
                              onClick={() => handleConfirm(task.id)}
                              className="px-3.5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-[11px] font-semibold rounded-lg transition-colors whitespace-nowrap shadow-xs shadow-blue-500/20 cursor-pointer active:scale-95"
                            >
                              确认并执行
                            </button>
                          </div>
                        </motion.div>
                      );
                    }
                    // Collapsed strip
                    return (
                      <motion.div
                        key={task.id}
                        layout
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0, x: 80 }}
                        transition={{ duration: 0.2 }}
                        onClick={() => {
                          // Promote to top
                          setTasks((prev) => {
                            const target = prev.find((t) => t.id === task.id);
                            if (!target) return prev;
                            return [target, ...prev.filter((t) => t.id !== task.id)];
                          });
                        }}
                        className="bg-white/50 border border-slate-200/50 rounded-xl px-3.5 py-2 mb-1.5 flex items-center justify-between text-[11px] text-slate-600 hover:bg-white/80 cursor-pointer transition-all select-none"
                      >
                        <span className="truncate">{task.title}</span>
                        <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                      </motion.div>
                    );
                  })
                ) : (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="flex-1 flex flex-col items-center justify-center text-center"
                  >
                    <CheckCircle2 className="w-7 h-7 text-emerald-500 mb-1.5 stroke-[1.5]" />
                    <p className="text-xs font-semibold text-slate-800">🎉 全部处理完毕</p>
                    <p className="text-[10px] text-slate-400 mt-0.5">当前无待确认事项</p>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>

          {/* ─── Quadrant 3 (Bottom-Left): 求职动态 ─── */}
          <div className="flex flex-col pr-28 pt-20">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-sm">
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                求职动态
              </div>
              <button
                type="button"
                onClick={() => navigate('/career')}
                className="text-[11px] text-slate-400 hover:text-blue-600 cursor-pointer flex items-center gap-0.5 font-medium transition-colors"
              >
                查看全部 <ArrowUpRight className="w-3 h-3" />
              </button>
            </div>
            <div className="space-y-0 text-xs text-slate-600 flex-1">
              {careerEvents.map((ev) => (
                <div
                  key={ev.id}
                  onClick={() => navigate('/career')}
                  className="flex justify-between py-2 border-b border-slate-100/80 cursor-pointer group"
                >
                  <span className="font-medium text-slate-700 group-hover:text-emerald-700 truncate">
                    {ev.company} · {ev.title}
                  </span>
                  <span className={`font-medium shrink-0 ml-2 ${ev.isClosed ? 'text-slate-400' : 'text-emerald-600'}`}>
                    {ev.step}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* ─── Quadrant 4 (Bottom-Right): Copilot 工作 ─── */}
          <div className="flex flex-col pl-28 pt-20">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-sm">
                <span className="w-2 h-2 rounded-full bg-purple-500" />
                Copilot 工作
              </div>
              <button
                type="button"
                onClick={() => navigate('/activities')}
                className="text-[11px] text-slate-400 hover:text-blue-600 cursor-pointer flex items-center gap-0.5 font-medium transition-colors"
              >
                活动中心 <ArrowUpRight className="w-3 h-3" />
              </button>
            </div>
            <div className="space-y-2 text-xs flex-1">
              {copilotWork.map((item) => (
                <div
                  key={item.id}
                  onClick={() => navigate('/activities')}
                  className="bg-slate-50/60 rounded-lg p-2.5 flex items-center justify-between cursor-pointer group hover:bg-slate-100/70 transition-colors"
                >
                  <div className="truncate pr-2 min-w-0">
                    <div className="font-medium text-slate-700 group-hover:text-purple-700 truncate">{item.title}</div>
                    <div className="text-[10px] text-slate-400 truncate">{item.detail}</div>
                  </div>
                  <span className={`px-2 py-0.5 rounded text-[10px] shrink-0 font-semibold ${
                    item.state === 'active'
                      ? 'bg-blue-100 text-blue-700'
                      : 'bg-slate-100 text-slate-500'
                  }`}>
                    {item.state === 'active' ? '运行中' : '待命中'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ─── Center Copilot Capsule Island (visual anchor at crossroads) ─── */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center">
          <div className="w-[360px] bg-white/95 backdrop-blur-xl border border-blue-200/60 shadow-xl shadow-blue-500/10 rounded-2xl p-4 flex flex-col items-center gap-3 ring-4 ring-blue-50/40">
            <div className="text-center">
              <h2 className="text-base font-bold text-slate-800">{greeting}</h2>
              <p className="text-xs text-slate-500">
                今天有 <span className="text-blue-600 font-semibold">{tasks.length}</span> 件事项需要推进
              </p>
            </div>
            <form onSubmit={handleStartCopilot} className="w-full flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-xl px-3 py-2">
              <Sparkles className="w-4 h-4 text-blue-500 shrink-0" />
              <input
                type="text"
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                placeholder="向 Copilot 提问、指派任务或开启对话…"
                className="flex-1 bg-transparent text-xs outline-none text-slate-700 placeholder-slate-400"
              />
              <button
                type="submit"
                className="p-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors cursor-pointer"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </form>
          </div>
        </div>
      </main>
    </div>
  );
}
