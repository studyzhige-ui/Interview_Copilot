import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Sparkles,
  Send,
  CheckCircle2,
  ArrowUpRight,
  ChevronRight,
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
  statusHint?: string;
  bgGradient?: string;
  headerTextColor?: string;
}

const SEED_TASKS: ConfirmTask[] = [
  {
    id: 1,
    title: '腾讯 HR 邮件：确认技术一面面试时间',
    desc: '收到腾讯招聘团队发来的面试邀约，建议面试时间为下周二（8月19日）上午 10:30。',
    copilotTip: '检测到该时间段无冲突，是否授权发送确认回信？',
    badge: '外部动作审批',
    statusHint: '待确认发送',
    bgGradient: 'from-[#FEF3C7] to-[#FDE68A]',
    headerTextColor: 'text-amber-950',
  },
  {
    id: 2,
    title: '字节跳动：更新应聘进展至「二面通过」',
    desc: '系统检测到邮件更新，确认更新状态库。',
    copilotTip: '是否将该机会推进至「HR 面 / Offer 沟通」？',
    badge: '进展事实确认',
    statusHint: '建议推进',
    bgGradient: 'from-[#E0F2FE] to-[#BAE6FD]',
    headerTextColor: 'text-sky-950',
  },
  {
    id: 3,
    title: '求职档案：同步在面试中确证的项目亮点',
    desc: '根据最新复盘录音提炼的项目经验沉淀。',
    copilotTip: '是否将该项已确证的工程经历提炼并沉淀到核心档案？',
    badge: '档案更新确认',
    statusHint: '待归档',
    bgGradient: 'from-[#F3E8FF] to-[#E9D5FF]',
    headerTextColor: 'text-purple-950',
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

  const nextStepItems = useMemo(() => {
    const active = opportunities.filter((o) => !o.outcome && !o.archived_at);
    return active.slice(0, 3).map((o) => ({
      id: o.id,
      company: o.company_name,
      title: o.job_title,
      step: o.current_step || '推进中',
    }));
  }, [opportunities]);

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
    return [
      { id: 'm1', company: '腾讯科技', title: '高级后端开发工程师', step: '技术初面已通过', isClosed: false },
      { id: 'm2', company: '字节跳动', title: '全栈架构师', step: '面试已预约下周三', isClosed: false },
    ];
  }, [opportunities]);

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

  const handlePromoteTask = (id: number) => {
    setTasks((prev) => {
      const target = prev.find((t) => t.id === id);
      if (!target) return prev;
      return [target, ...prev.filter((t) => t.id !== id)];
    });
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
    <div className="relative w-full h-full overflow-hidden select-none font-sans bg-[#FAFBFD]">
      
      {/* ═══ 1. Continuous Multi-Color Aurora Mesh Flow ═══ */}
      <div className="absolute inset-0 z-0 pointer-events-none overflow-hidden">
        {/* Top-Left: Sky Blue & Cyan */}
        <div className="absolute top-0 left-0 w-[55%] h-[55%] rounded-full bg-gradient-to-br from-sky-200/70 via-blue-100/50 to-transparent blur-[110px]" />
        {/* Top-Right: Warm Amber & Coral Red */}
        <div className="absolute top-0 right-0 w-[55%] h-[55%] rounded-full bg-gradient-to-bl from-rose-200/70 via-amber-100/50 to-transparent blur-[110px]" />
        {/* Bottom-Left: Fresh Mint & Emerald */}
        <div className="absolute bottom-0 left-0 w-[55%] h-[55%] rounded-full bg-gradient-to-tr from-emerald-200/70 via-teal-100/50 to-transparent blur-[110px]" />
        {/* Bottom-Right: Soft Violet & Indigo */}
        <div className="absolute bottom-0 right-0 w-[55%] h-[55%] rounded-full bg-gradient-to-tl from-indigo-200/70 via-purple-100/50 to-transparent blur-[110px]" />
        {/* Center Luminous Convergence */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[45%] h-[45%] rounded-full bg-white/90 blur-[75px]" />
      </div>

      {/* ═══ 2. Enhanced Apple Liquid Glass Astroid Star ═══ */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none z-10"
        viewBox="0 0 1000 700"
        preserveAspectRatio="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          {/* Multi-Stop Liquid Glass Translucent Refraction Gradient */}
          <linearGradient id="liquidGlassSurface" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.8" />
            <stop offset="25%" stopColor="#F8FAFC" stopOpacity="0.55" />
            <stop offset="50%" stopColor="#FFFFFF" stopOpacity="0.7" />
            <stop offset="75%" stopColor="#F1F5F9" stopOpacity="0.5" />
            <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0.8" />
          </linearGradient>

          {/* High-Gloss Specular Rim Highlight */}
          <linearGradient id="liquidGlassRimStroke" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="rgba(255, 255, 255, 1)" />
            <stop offset="30%" stopColor="rgba(226, 232, 240, 0.75)" />
            <stop offset="70%" stopColor="rgba(203, 213, 225, 0.65)" />
            <stop offset="100%" stopColor="rgba(255, 255, 255, 1)" />
          </linearGradient>

          {/* Tactile Drop Shadow Filter */}
          <filter id="liquidGlassShadow" x="-10%" y="-10%" width="120%" height="120%">
            <feDropShadow dx="0" dy="20" stdDeviation="35" floodColor="#0F172A" floodOpacity="0.06" />
            <feDropShadow dx="0" dy="6" stdDeviation="12" floodColor="#0F172A" floodOpacity="0.04" />
          </filter>
        </defs>

        {/* ── Main Liquid Glass 4-Pointed Star ── */}
        <path
          d="M 500 0 C 500 240, 680 350, 1000 350 C 680 350, 500 460, 500 700 C 500 460, 320 350, 0 350 C 320 350, 500 240, 500 0 Z"
          fill="url(#liquidGlassSurface)"
          stroke="url(#liquidGlassRimStroke)"
          strokeWidth="2"
          filter="url(#liquidGlassShadow)"
        />

        {/* Primary Specular Light Refraction Bevels */}
        <path
          d="M 500 0 C 500 240, 320 350, 0 350"
          fill="none"
          stroke="rgba(255, 255, 255, 0.95)"
          strokeWidth="3"
          strokeLinecap="round"
          opacity="0.95"
        />
        <path
          d="M 1000 350 C 680 350, 500 460, 500 700"
          fill="none"
          stroke="rgba(255, 255, 255, 0.85)"
          strokeWidth="2.5"
          strokeLinecap="round"
          opacity="0.85"
        />
      </svg>

      {/* ═══ 3. Central Copilot Nexus (Snugly encased in the Liquid Glass Star) ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center pointer-events-auto">
        <div className="flex flex-col items-center mb-3.5">
          <h2 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight drop-shadow-sm">
            {greeting}
          </h2>
          <p className="text-xs sm:text-sm font-medium text-slate-500 mt-0.5">
            今日有 <span className="text-blue-600 font-bold">{tasks.length}</span> 项待办事项需推进
          </p>
        </div>

        {/* High-Gloss Frosted Glass Capsule Searchbox */}
        <form 
          onSubmit={handleStartCopilot} 
          className="w-[440px] h-[52px] bg-white/85 backdrop-blur-2xl border border-white/90 shadow-[0_12px_36px_rgba(15,23,42,0.06),0_1px_2px_rgba(255,255,255,0.9)_inset] rounded-full px-5 flex items-center gap-3 transition-all hover:bg-white/95 hover:shadow-[0_16px_44px_rgba(15,23,42,0.09)]"
        >
          <Sparkles className="w-4 h-4 text-blue-500 shrink-0" />
          <input
            type="text"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder="向 Copilot 发送指令或提问…"
            className="flex-1 bg-transparent text-sm font-normal outline-none text-slate-800 placeholder:text-slate-400"
          />
          <button
            type="submit"
            className="w-8 h-8 flex items-center justify-center bg-blue-600 hover:bg-blue-700 text-white rounded-full transition-transform hover:scale-105 cursor-pointer shrink-0 shadow-sm"
          >
            <Send className="w-3.5 h-3.5 -ml-0.5" />
          </button>
        </form>
      </div>

      {/* ═══ 4. Four Expansive Quadrants Strictly Contained within Regions ═══ */}
      <div className="relative z-20 w-full h-full grid grid-cols-2 grid-rows-2 pointer-events-none">

        {/* ─── Q1 Top-Left: 下一步 (Next Steps) ─── */}
        <div className="flex items-center justify-center p-8 pr-28 pb-14">
          <div className="w-full max-w-[340px] flex flex-col pointer-events-auto">
            <div className="mb-3">
              <div className="flex items-center gap-2 text-slate-900 font-black text-base tracking-tight mb-0.5">
                <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                下一步
              </div>
              <p className="text-xs text-slate-500 font-normal">已确认为真实面试并需推进的重点动作</p>
            </div>

            {nextStepItems.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 bg-white/30 backdrop-blur-md rounded-2xl border border-white/50">
                <CheckCircle2 className="w-6 h-6 text-slate-400 mb-1.5 stroke-[1.5]" />
                <p className="text-xs font-medium text-slate-500">当前没有需要推进的动作</p>
              </div>
            ) : (
              <div className="space-y-2.5 flex-1">
                {nextStepItems.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => navigate(`/career?opportunity=${item.id}`)}
                    className="flex items-center justify-between p-3.5 bg-white/70 hover:bg-white/95 backdrop-blur-md shadow-[0_4px_20px_rgba(15,23,42,0.03)] border border-white/80 rounded-2xl cursor-pointer group transition-all"
                  >
                    <div className="min-w-0 pr-3">
                      <div className="text-sm font-bold text-slate-900 group-hover:text-blue-600 truncate mb-0.5">
                        推进 {item.step}
                      </div>
                      <div className="text-xs text-slate-500 truncate">{item.company} · {item.title}</div>
                    </div>
                    <ArrowUpRight size={16} className="text-slate-400 group-hover:text-blue-600 shrink-0" />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ─── Q2 Top-Right: 待我确认 (Strictly Contained Stepped Card Stack) ─── */}
        <div className="flex items-center justify-center p-8 pl-28 pb-14">
          <div className="w-full max-w-[350px] flex flex-col pointer-events-auto">
            <div className="flex items-center justify-between mb-2.5 shrink-0">
              <div>
                <div className="flex items-center gap-2 text-slate-900 font-black text-base tracking-tight">
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                  待我确认
                </div>
                <p className="text-xs text-slate-500 font-normal mt-0.5">需授权或确认的事实与外部动作</p>
              </div>
              <span className="text-xs font-bold px-2.5 py-0.5 rounded-full bg-amber-100/90 text-amber-800 border border-amber-200/60">
                {tasks.length} 待决
              </span>
            </div>

            {/* Stepped Physical Card Stack Container (Strictly bounded to 215px) */}
            <div className="relative w-full h-[215px] overflow-visible">
              <AnimatePresence mode="popLayout">
                {tasks.length > 0 ? (
                  tasks.map((task, idx) => {
                    const isTop = idx === 0;
                    // Tight stepped offset of 28px to keep stack within boundaries
                    const topOffset = isTop ? (tasks.length - 1) * 28 : (tasks.length - 1 - idx) * 28;
                    const zIndex = isTop ? 30 : 20 - idx;
                    const bgGradientClass = task.bgGradient ? `bg-gradient-to-r ${task.bgGradient}` : 'bg-gradient-to-r from-amber-100 to-amber-50';
                    const headerTextClass = task.headerTextColor || 'text-slate-900';

                    if (!isTop) {
                      // ── Behind Card: Full-sized card stepping behind ──
                      return (
                        <motion.div
                          key={task.id}
                          layout
                          initial={{ opacity: 0, y: -10 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, x: 200 }}
                          transition={{ duration: 0.25 }}
                          onClick={() => handlePromoteTask(task.id)}
                          style={{ top: `${topOffset}px`, zIndex }}
                          className={`absolute left-0 w-full h-[150px] ${bgGradientClass} border border-white/80 shadow-[0_4px_16px_rgba(15,23,42,0.04)] rounded-2xl p-3 flex flex-col justify-between cursor-pointer transition-all hover:brightness-105`}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-1.5 min-w-0 pr-2">
                              <span className={`text-xs font-bold ${headerTextClass} truncate`}>
                                {task.title}
                              </span>
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                              <span className={`text-[11px] font-semibold ${headerTextClass} opacity-80`}>
                                {task.statusHint || task.badge}
                              </span>
                              <ChevronRight size={13} className="opacity-50" />
                            </div>
                          </div>
                          <div className="text-[11px] text-slate-500/40 select-none pointer-events-none truncate pt-1">
                            {task.desc}
                          </div>
                        </motion.div>
                      );
                    }

                    // ── Front Active Card: Full-sized card expanded on top ──
                    return (
                      <motion.div
                        key={task.id}
                        layout
                        initial={{ opacity: 0, y: 15, scale: 0.96 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, x: 220, scale: 0.92 }}
                        transition={{ duration: 0.28, ease: 'easeOut' }}
                        style={{ top: `${topOffset}px`, zIndex }}
                        className="absolute left-0 w-full h-[150px] bg-white/95 backdrop-blur-2xl border border-white shadow-[0_12px_28px_rgba(15,23,42,0.08)] rounded-2xl p-3 flex flex-col justify-between"
                      >
                        <div>
                          <div className="flex items-start justify-between gap-1.5 mb-1">
                            <div className="flex items-center gap-1.5 flex-1 min-w-0">
                              <div className="w-4.5 h-4.5 rounded-full bg-amber-500/15 text-amber-600 flex items-center justify-center shrink-0">
                                <Sparkles size={11} />
                              </div>
                              <h3 className="text-xs font-bold text-slate-900 leading-tight truncate">
                                {task.title}
                              </h3>
                            </div>
                            <div className="text-[10px] font-bold text-amber-800 bg-amber-100/90 px-2 py-0.5 rounded-md shrink-0 border border-amber-200/60">
                              {task.badge}
                            </div>
                          </div>

                          <p className="text-[11px] text-slate-600 leading-snug line-clamp-1 mb-1.5">
                            {task.desc}
                          </p>

                          <div className="bg-amber-50/70 border border-amber-200/50 py-1 px-2 text-[11px] text-amber-900 flex items-center gap-1.5 rounded-lg">
                            <span className="font-semibold text-amber-700 shrink-0 text-[10px]">建议:</span>
                            <span className="truncate font-medium text-[10px]">{task.copilotTip}</span>
                          </div>
                        </div>

                        <div className="flex gap-1.5 pt-0.5">
                          <input
                            type="text"
                            placeholder="补充批注或确认意见…"
                            className="flex-1 text-[11px] bg-slate-50/80 border border-slate-200/80 rounded-lg px-2.5 h-7.5 outline-none focus:bg-white focus:border-blue-500 transition-colors"
                          />
                          <button
                            type="button"
                            onClick={() => handleConfirm(task.id)}
                            className="px-3 h-7.5 bg-slate-900 hover:bg-slate-800 text-white text-[11px] font-bold rounded-lg transition-colors whitespace-nowrap shadow-sm hover:shadow cursor-pointer"
                          >
                            确认执行
                          </button>
                        </div>
                      </motion.div>
                    );
                  })
                ) : (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="absolute inset-0 flex flex-col items-center justify-center py-6 bg-white/30 backdrop-blur-md rounded-2xl border border-white/50"
                  >
                    <CheckCircle2 className="w-6 h-6 text-slate-400 mb-1.5 stroke-[1.5]" />
                    <p className="text-xs font-medium text-slate-500">今日待办已全部处理完毕</p>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>

        {/* ─── Q3 Bottom-Left: 求职动态 (Career Stream) ─── */}
        <div className="flex items-center justify-center p-8 pr-28 pt-14">
          <div className="w-full max-w-[340px] flex flex-col pointer-events-auto">
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="flex items-center gap-2 text-slate-900 font-black text-base tracking-tight">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                  求职动态
                </div>
                <p className="text-xs text-slate-500 font-normal mt-0.5">近期岗位状态变更与最新回执</p>
              </div>
              <button
                type="button"
                onClick={() => navigate('/career')}
                className="text-xs text-slate-500 hover:text-emerald-700 cursor-pointer flex items-center gap-0.5 font-bold transition-colors"
              >
                全部 <ArrowUpRight className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="flex-1 min-h-0 space-y-2.5">
              {careerEvents.map((ev) => (
                <div
                  key={ev.id}
                  onClick={() => navigate('/career')}
                  className="flex items-center justify-between p-3.5 bg-white/70 hover:bg-white/95 backdrop-blur-md shadow-[0_4px_20px_rgba(15,23,42,0.03)] border border-white/80 rounded-2xl cursor-pointer group transition-all"
                >
                  <span className="text-sm font-bold text-slate-900 group-hover:text-emerald-700 truncate pr-3">
                    {ev.company} · {ev.title}
                  </span>
                  <span className={`text-xs font-semibold shrink-0 bg-white/80 px-2.5 py-0.5 rounded-full border border-white/80 ${ev.isClosed ? 'text-slate-400' : 'text-emerald-600'}`}>
                    {ev.step}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ─── Q4 Bottom-Right: Copilot 工作 (Agent Tasks) ─── */}
        <div className="flex items-center justify-center p-8 pl-28 pt-14">
          <div className="w-full max-w-[350px] flex flex-col pointer-events-auto">
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="flex items-center gap-2 text-slate-900 font-black text-base tracking-tight">
                  <span className="w-2.5 h-2.5 rounded-full bg-purple-500" />
                  Copilot 工作
                </div>
                <p className="text-xs text-slate-500 font-normal mt-0.5">AI Agent 常驻后台巡检与分析任务</p>
              </div>
              <button
                type="button"
                onClick={() => navigate('/activities')}
                className="text-xs text-slate-500 hover:text-purple-700 cursor-pointer flex items-center gap-0.5 font-bold transition-colors"
              >
                控制台 <ArrowUpRight className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="flex-1 min-h-0 space-y-2.5">
              {copilotWork.map((item) => (
                <div
                  key={item.id}
                  onClick={() => navigate('/activities')}
                  className="bg-white/70 hover:bg-white/95 backdrop-blur-md shadow-[0_4px_20px_rgba(15,23,42,0.03)] border border-white/80 rounded-2xl p-3.5 flex items-center justify-between cursor-pointer group transition-all"
                >
                  <div className="truncate pr-3 min-w-0">
                    <div className="text-sm font-bold text-slate-900 group-hover:text-purple-700 truncate mb-0.5">{item.title}</div>
                    <div className="text-xs text-slate-500 truncate">{item.detail}</div>
                  </div>
                  <span className={`px-2.5 py-1 rounded-full flex items-center gap-1.5 text-[10px] shrink-0 font-bold ${
                    item.state === 'active'
                      ? 'bg-blue-50 text-blue-700 border border-blue-100'
                      : 'bg-slate-100 text-slate-500 border border-slate-200'
                  }`}>
                    {item.state === 'active' && <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />}
                    {item.state === 'active' ? '运行中' : '待命中'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
