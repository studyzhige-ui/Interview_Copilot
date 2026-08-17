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
    desc: '收到腾讯招聘团队发来的面试邀约，建议面试时间为下周二（8月19日）上午 10:30。已同步对比您的日程表。',
    copilotTip: '检测到该时间段无任何日程冲突，是否授权发送标准回信？',
    badge: '外部动作审批',
    statusHint: '待确认发送',
    bgGradient: 'from-[#FEF3C7] to-[#FDE68A]',
    headerTextColor: 'text-amber-950',
  },
  {
    id: 2,
    title: '字节跳动：更新应聘进展至「二面通过」',
    desc: '系统通过招聘来信解析到最新阶段更新，建议同步流转至下一步状态库。',
    copilotTip: '是否将该岗位机会正式推进至「HR 面 / Offer 沟通」？',
    badge: '进展事实确认',
    statusHint: '建议推进',
    bgGradient: 'from-[#E0F2FE] to-[#BAE6FD]',
    headerTextColor: 'text-sky-950',
  },
  {
    id: 3,
    title: '求职档案：同步在面试中确证的项目亮点',
    desc: '根据昨日复盘录音深度提炼出高并发架构实战经验与量化成果。',
    copilotTip: '是否将该项已确证的工程经历提炼并沉淀到个人全局档案？',
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
      
      {/* ═══ 1. High-Impact Chromatic Center Aurora Burst (Fading to Light Airiness at Corners) ═══ */}
      <div className="absolute inset-0 z-0 pointer-events-none overflow-hidden">
        {/* Core Chromatic Nebula centered on the Star Nexus */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[70vw] h-[70vh] rounded-full bg-[radial-gradient(circle_at_center,_rgba(147,197,253,0.7)_0%,_rgba(192,132,252,0.65)_30%,_rgba(253,186,116,0.6)_55%,_rgba(110,231,183,0.5)_75%,_transparent_100%)] blur-[95px]" />
        
        {/* Directional radiant bursts radiating from center towards the 4 quadrants, decaying to faint pastel */}
        {/* Top-Left Ray: Sky Blue */}
        <div className="absolute top-[20%] left-[20%] w-[45vw] h-[45vh] rounded-full bg-[radial-gradient(circle,_rgba(56,189,248,0.45)_0%,_rgba(186,230,253,0.2)_50%,_transparent_75%)] blur-[90px]" />
        {/* Top-Right Ray: Coral Rose */}
        <div className="absolute top-[20%] right-[20%] w-[45vw] h-[45vh] rounded-full bg-[radial-gradient(circle,_rgba(251,113,133,0.4)_0%,_rgba(254,205,211,0.18)_50%,_transparent_75%)] blur-[90px]" />
        {/* Bottom-Left Ray: Emerald */}
        <div className="absolute bottom-[20%] left-[20%] w-[45vw] h-[45vh] rounded-full bg-[radial-gradient(circle,_rgba(52,211,153,0.4)_0%,_rgba(167,243,208,0.18)_50%,_transparent_75%)] blur-[90px]" />
        {/* Bottom-Right Ray: Purple Violet */}
        <div className="absolute bottom-[20%] right-[20%] w-[45vw] h-[45vh] rounded-full bg-[radial-gradient(circle,_rgba(168,85,247,0.45)_0%,_rgba(233,213,255,0.2)_50%,_transparent_75%)] blur-[90px]" />

        {/* Center Luminous Energy Spike */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[30vw] h-[30vh] rounded-full bg-white/75 blur-[55px]" />
      </div>

      {/* ═══ 2. Vibrant Chromatic Apple Liquid Glass Astroid Star ═══ */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none z-10"
        viewBox="0 0 1000 700"
        preserveAspectRatio="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          {/* Saturated Chromatic Liquid Glass Translucent Refraction */}
          <linearGradient id="vibrantGlassSurface" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#BAE6FD" stopOpacity="0.7" />
            <stop offset="25%" stopColor="#FFFFFF" stopOpacity="0.85" />
            <stop offset="50%" stopColor="#DDD6FE" stopOpacity="0.65" />
            <stop offset="75%" stopColor="#FFFFFF" stopOpacity="0.85" />
            <stop offset="100%" stopColor="#FED7AA" stopOpacity="0.7" />
          </linearGradient>

          {/* High-Impact Chromatic Specular Rim Highlight */}
          <linearGradient id="vibrantGlassRimStroke" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="rgba(255, 255, 255, 1)" />
            <stop offset="25%" stopColor="rgba(56, 189, 248, 0.85)" />
            <stop offset="50%" stopColor="rgba(255, 255, 255, 1)" />
            <stop offset="75%" stopColor="rgba(192, 132, 252, 0.85)" />
            <stop offset="100%" stopColor="rgba(255, 255, 255, 1)" />
          </linearGradient>

          {/* Tactile Soft Drop Shadow */}
          <filter id="vibrantGlassShadow" x="-10%" y="-10%" width="120%" height="120%">
            <feDropShadow dx="0" dy="24" stdDeviation="40" floodColor="#0F172A" floodOpacity="0.08" />
            <feDropShadow dx="0" dy="8" stdDeviation="16" floodColor="#0F172A" floodOpacity="0.05" />
          </filter>
        </defs>

        {/* ── Main Liquid Glass 4-Pointed Star ── */}
        <path
          d="M 500 0 C 500 240, 680 350, 1000 350 C 680 350, 500 460, 500 700 C 500 460, 320 350, 0 350 C 320 350, 500 240, 500 0 Z"
          fill="url(#vibrantGlassSurface)"
          stroke="url(#vibrantGlassRimStroke)"
          strokeWidth="2.5"
          filter="url(#vibrantGlassShadow)"
        />

        {/* Primary Specular Light Refraction Bevels */}
        <path
          d="M 500 0 C 500 240, 320 350, 0 350"
          fill="none"
          stroke="rgba(255, 255, 255, 0.95)"
          strokeWidth="3.5"
          strokeLinecap="round"
          opacity="0.95"
        />
        <path
          d="M 1000 350 C 680 350, 500 460, 500 700"
          fill="none"
          stroke="rgba(255, 255, 255, 0.9)"
          strokeWidth="3"
          strokeLinecap="round"
          opacity="0.9"
        />
      </svg>

      {/* ═══ 3. Central Copilot Nexus ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center pointer-events-auto">
        <div className="flex flex-col items-center mb-3.5">
          <h2 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight drop-shadow-sm">
            {greeting}
          </h2>
          <p className="text-xs sm:text-sm font-medium text-slate-600 mt-0.5">
            今日有 <span className="text-blue-600 font-bold">{tasks.length}</span> 项待办事项需推进
          </p>
        </div>

        {/* High-Gloss Frosted Glass Capsule Searchbox */}
        <form 
          onSubmit={handleStartCopilot} 
          className="w-[450px] h-[54px] bg-white/90 backdrop-blur-2xl border border-white shadow-[0_16px_40px_rgba(15,23,42,0.08),0_1px_2px_rgba(255,255,255,1)_inset] rounded-full px-5 flex items-center gap-3 transition-all hover:bg-white hover:shadow-[0_20px_48px_rgba(15,23,42,0.12)]"
        >
          <Sparkles className="w-4.5 h-4.5 text-blue-500 shrink-0" />
          <input
            type="text"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder="向 Copilot 发送指令或提问…"
            className="flex-1 bg-transparent text-sm font-normal outline-none text-slate-800 placeholder:text-slate-400"
          />
          <button
            type="submit"
            className="w-9 h-9 flex items-center justify-center bg-blue-600 hover:bg-blue-700 text-white rounded-full transition-transform hover:scale-105 cursor-pointer shrink-0 shadow-sm"
          >
            <Send className="w-3.5 h-3.5 -ml-0.5" />
          </button>
        </form>
      </div>

      {/* ═══ 4. Four Quadrants Positioned at the Balanced Sweet-Spots ═══ */}
      <div className="absolute inset-0 z-20 pointer-events-none">

        {/* ─── Q1 Top-Left: 下一步 (Sweet Spot: centered at x=26%, y=26%, filling quadrant comfortably) ─── */}
        <div className="absolute top-[26%] left-[26%] -translate-x-1/2 -translate-y-1/2 w-[410px] flex flex-col pointer-events-auto">
          <div className="mb-3.5">
            <div className="flex items-center gap-2.5 text-slate-900 font-black text-lg tracking-tight mb-0.5">
              <span className="w-3 h-3 rounded-full bg-blue-500 shadow-sm" />
              下一步
            </div>
            <p className="text-sm text-slate-600 font-medium">已确认为真实面试并需推进的重点动作</p>
          </div>

          {nextStepItems.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 bg-white/50 backdrop-blur-md rounded-2xl border border-white/70 shadow-sm">
              <CheckCircle2 className="w-7 h-7 text-slate-400 mb-1.5 stroke-[1.5]" />
              <p className="text-sm font-medium text-slate-500">当前没有需要推进的动作</p>
            </div>
          ) : (
            <div className="space-y-3 flex-1">
              {nextStepItems.map((item) => (
                <div
                  key={item.id}
                  onClick={() => navigate(`/career?opportunity=${item.id}`)}
                  className="flex items-center justify-between p-4 bg-white/80 hover:bg-white backdrop-blur-md shadow-[0_4px_20px_rgba(15,23,42,0.03)] border border-white/90 rounded-2xl cursor-pointer group transition-all"
                >
                  <div className="min-w-0 pr-3">
                    <div className="text-base font-bold text-slate-900 group-hover:text-blue-600 truncate mb-0.5">
                      推进 {item.step}
                    </div>
                    <div className="text-sm text-slate-500 truncate">{item.company} · {item.title}</div>
                  </div>
                  <ArrowUpRight size={18} className="text-slate-400 group-hover:text-blue-600 shrink-0" />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ─── Q2 Top-Right: 待我确认 (Sweet Spot: centered at x=74%, y=26%, full detailed display) ─── */}
        <div className="absolute top-[26%] right-[26%] translate-x-1/2 -translate-y-1/2 w-[420px] flex flex-col pointer-events-auto">
          <div className="flex items-center justify-between mb-3 shrink-0">
            <div>
              <div className="flex items-center gap-2.5 text-slate-900 font-black text-lg tracking-tight">
                <span className="w-3 h-3 rounded-full bg-amber-500 shadow-sm" />
                待我确认
              </div>
              <p className="text-sm text-slate-600 font-medium mt-0.5">需授权或确认的事实与外部动作</p>
            </div>
            <span className="text-xs font-bold px-3 py-0.5 rounded-full bg-amber-100/90 text-amber-800 border border-amber-200/60 shadow-xs">
              {tasks.length} 待决
            </span>
          </div>

          {/* Stepped Physical Card Stack Container with Full Detailed Content on Active Card */}
          <div className="relative w-full h-[270px] overflow-visible">
            <AnimatePresence mode="popLayout">
              {tasks.length > 0 ? (
                tasks.map((task, idx) => {
                  const isTop = idx === 0;
                  const topOffset = isTop ? (tasks.length - 1) * 36 : (tasks.length - 1 - idx) * 36;
                  const zIndex = isTop ? 30 : 20 - idx;
                  const bgGradientClass = task.bgGradient ? `bg-gradient-to-r ${task.bgGradient}` : 'bg-gradient-to-r from-amber-100 to-amber-50';
                  const headerTextClass = task.headerTextColor || 'text-slate-900';

                  if (!isTop) {
                    // ── Behind Card: Full-sized card stepping behind with visible top bar ──
                    return (
                      <motion.div
                        key={task.id}
                        layout
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, x: 220 }}
                        transition={{ duration: 0.25 }}
                        onClick={() => handlePromoteTask(task.id)}
                        style={{ top: `${topOffset}px`, zIndex }}
                        className={`absolute left-0 w-full h-[190px] ${bgGradientClass} border border-white/80 shadow-[0_4px_16px_rgba(15,23,42,0.04)] rounded-2xl p-4 flex flex-col justify-between cursor-pointer transition-all hover:brightness-105`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 min-w-0 pr-2">
                            <span className={`text-sm font-bold ${headerTextClass} truncate`}>
                              {task.title}
                            </span>
                          </div>
                          <div className="flex items-center gap-1 shrink-0">
                            <span className={`text-xs font-semibold ${headerTextClass} opacity-85`}>
                              {task.statusHint || task.badge}
                            </span>
                            <ChevronRight size={14} className="opacity-60" />
                          </div>
                        </div>
                        <div className="text-xs text-slate-500/40 select-none pointer-events-none truncate pt-1">
                          {task.desc}
                        </div>
                      </motion.div>
                    );
                  }

                  // ── Front Active Card: Full detailed information without any truncation ──
                  return (
                    <motion.div
                      key={task.id}
                      layout
                      initial={{ opacity: 0, y: 15, scale: 0.96 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, x: 240, scale: 0.92 }}
                      transition={{ duration: 0.28, ease: 'easeOut' }}
                      style={{ top: `${topOffset}px`, zIndex }}
                      className="absolute left-0 w-full bg-white/95 backdrop-blur-2xl border border-white shadow-[0_16px_36px_rgba(15,23,42,0.09)] rounded-2xl p-4.5 flex flex-col gap-2.5"
                    >
                      {/* Title & Badge */}
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2 flex-1 min-w-0">
                          <div className="w-6 h-6 rounded-full bg-amber-500/15 text-amber-600 flex items-center justify-center shrink-0">
                            <Sparkles size={13} />
                          </div>
                          <h3 className="text-sm sm:text-base font-bold text-slate-900 leading-snug">
                            {task.title}
                          </h3>
                        </div>
                        <div className="text-xs font-bold text-amber-800 bg-amber-100/90 px-2.5 py-0.5 rounded-md shrink-0 border border-amber-200/60">
                          {task.badge}
                        </div>
                      </div>

                      {/* Full Complete Description */}
                      <p className="text-xs sm:text-sm text-slate-600 leading-relaxed">
                        {task.desc}
                      </p>

                      {/* Full Complete Copilot Recommendation Callout */}
                      <div className="bg-amber-50/80 border border-amber-200/60 p-2.5 text-xs sm:text-sm text-amber-950 rounded-xl flex items-start gap-2">
                        <span className="font-bold text-amber-700 shrink-0">建议:</span>
                        <span className="font-medium leading-relaxed">{task.copilotTip}</span>
                      </div>

                      {/* Action Row */}
                      <div className="flex gap-2 pt-1">
                        <input
                          type="text"
                          placeholder="补充批注或确认意见…"
                          className="flex-1 text-xs sm:text-sm bg-slate-50/90 border border-slate-200 rounded-xl px-3.5 h-8.5 outline-none focus:bg-white focus:border-blue-500 transition-colors"
                        />
                        <button
                          type="button"
                          onClick={() => handleConfirm(task.id)}
                          className="px-4 h-8.5 bg-slate-900 hover:bg-slate-800 text-white text-xs sm:text-sm font-bold rounded-xl transition-colors whitespace-nowrap shadow-sm hover:shadow cursor-pointer"
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
                  className="absolute inset-0 flex flex-col items-center justify-center py-6 bg-white/40 backdrop-blur-md rounded-2xl border border-white/60 shadow-sm"
                >
                  <CheckCircle2 className="w-7 h-7 text-slate-400 mb-1.5 stroke-[1.5]" />
                  <p className="text-sm font-medium text-slate-500">今日待办已全部处理完毕</p>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* ─── Q3 Bottom-Left: 求职动态 (Sweet Spot: centered at x=26%, y=74%) ─── */}
        <div className="absolute bottom-[26%] left-[26%] -translate-x-1/2 translate-y-1/2 w-[410px] flex flex-col pointer-events-auto">
          <div className="flex items-center justify-between mb-3.5">
            <div>
              <div className="flex items-center gap-2.5 text-slate-900 font-black text-lg tracking-tight">
                <span className="w-3 h-3 rounded-full bg-emerald-500 shadow-sm" />
                求职动态
              </div>
              <p className="text-sm text-slate-600 font-medium mt-0.5">近期岗位状态变更与最新回执</p>
            </div>
            <button
              type="button"
              onClick={() => navigate('/career')}
              className="text-sm text-slate-500 hover:text-emerald-700 cursor-pointer flex items-center gap-0.5 font-bold transition-colors"
            >
              全部 <ArrowUpRight className="w-4 h-4" />
            </button>
          </div>
          <div className="space-y-3 flex-1">
            {careerEvents.map((ev) => (
              <div
                key={ev.id}
                onClick={() => navigate('/career')}
                className="flex items-center justify-between p-4 bg-white/80 hover:bg-white backdrop-blur-md shadow-[0_4px_20px_rgba(15,23,42,0.03)] border border-white/90 rounded-2xl cursor-pointer group transition-all"
              >
                <span className="text-base font-bold text-slate-900 group-hover:text-emerald-700 truncate pr-3">
                  {ev.company} · {ev.title}
                </span>
                <span className={`text-xs font-semibold shrink-0 bg-white/90 px-3 py-1 rounded-full border border-slate-100 ${ev.isClosed ? 'text-slate-400' : 'text-emerald-600'}`}>
                  {ev.step}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* ─── Q4 Bottom-Right: Copilot 工作 (Sweet Spot: centered at x=74%, y=74%) ─── */}
        <div className="absolute bottom-[26%] right-[26%] translate-x-1/2 translate-y-1/2 w-[420px] flex flex-col pointer-events-auto">
          <div className="flex items-center justify-between mb-3.5">
            <div>
              <div className="flex items-center gap-2.5 text-slate-900 font-black text-lg tracking-tight">
                <span className="w-3 h-3 rounded-full bg-purple-500 shadow-sm" />
                Copilot 工作
              </div>
              <p className="text-sm text-slate-600 font-medium mt-0.5">AI Agent 常驻后台巡检与分析任务</p>
            </div>
            <button
              type="button"
              onClick={() => navigate('/activities')}
              className="text-sm text-slate-500 hover:text-purple-700 cursor-pointer flex items-center gap-0.5 font-bold transition-colors"
            >
              控制台 <ArrowUpRight className="w-4 h-4" />
            </button>
          </div>
          <div className="space-y-3 flex-1">
            {copilotWork.map((item) => (
              <div
                key={item.id}
                onClick={() => navigate('/activities')}
                className="bg-white/80 hover:bg-white backdrop-blur-md shadow-[0_4px_20px_rgba(15,23,42,0.03)] border border-white/90 rounded-2xl p-4 flex items-center justify-between cursor-pointer group transition-all"
              >
                <div className="truncate pr-3 min-w-0">
                  <div className="text-base font-bold text-slate-900 group-hover:text-purple-700 truncate mb-0.5">{item.title}</div>
                  <div className="text-sm text-slate-500 truncate">{item.detail}</div>
                </div>
                <span className={`px-3 py-1.5 rounded-full flex items-center gap-1.5 text-xs shrink-0 font-bold ${
                  item.state === 'active'
                    ? 'bg-blue-50 text-blue-700 border border-blue-100'
                    : 'bg-slate-100 text-slate-500 border border-slate-200'
                }`}>
                  {item.state === 'active' && <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />}
                  {item.state === 'active' ? '运行中' : '待命中'}
                </span>
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}
