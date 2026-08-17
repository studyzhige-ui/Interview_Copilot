import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Sparkles,
  Send,
  CheckCircle2,
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
    copilotTip: '检测到该时间段无冲突，是否授权发送确认回信？',
    badge: '外部动作审批',
  },
  {
    id: 2,
    title: '字节跳动：更新应聘进展至「二面通过」',
    desc: '系统检测到邮件更新，确认更新状态库。',
    copilotTip: '是否将该机会推进至「HR 面 / Offer 沟通」？',
    badge: '进展事实确认',
  },
  {
    id: 3,
    title: '求职档案：同步在面试中确证的项目亮点',
    desc: '根据最新复盘录音提炼的项目经验沉淀。',
    copilotTip: '是否将该项已确证的工程经历提炼并沉淀到核心档案？',
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
        <div className="absolute -top-[20%] -left-[20%] w-[70%] h-[70%] rounded-full bg-gradient-to-br from-sky-200/55 via-blue-200/40 to-transparent blur-[130px]" />
        {/* Top-Right: Warm Amber & Coral Red */}
        <div className="absolute -top-[20%] -right-[20%] w-[70%] h-[70%] rounded-full bg-gradient-to-bl from-rose-200/55 via-amber-200/40 to-transparent blur-[130px]" />
        {/* Bottom-Left: Fresh Mint & Emerald */}
        <div className="absolute -bottom-[20%] -left-[20%] w-[70%] h-[70%] rounded-full bg-gradient-to-tr from-emerald-200/55 via-teal-200/40 to-transparent blur-[130px]" />
        {/* Bottom-Right: Soft Violet & Indigo */}
        <div className="absolute -bottom-[20%] -right-[20%] w-[70%] h-[70%] rounded-full bg-gradient-to-tl from-indigo-200/55 via-purple-200/40 to-transparent blur-[130px]" />
        {/* Center Luminous Bloom */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[50%] h-[50%] rounded-full bg-white/80 blur-[80px]" />
      </div>

      {/* ═══ 2. Enhanced Apple Liquid Glass Astroid Star (Snugly wrapping central capsule) ═══ */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none z-10"
        viewBox="0 0 1000 700"
        preserveAspectRatio="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          {/* Multi-Stop Liquid Glass Translucent Refraction Gradient */}
          <linearGradient id="liquidGlassSurface" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.75" />
            <stop offset="25%" stopColor="#F8FAFC" stopOpacity="0.5" />
            <stop offset="50%" stopColor="#FFFFFF" stopOpacity="0.65" />
            <stop offset="75%" stopColor="#F1F5F9" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0.75" />
          </linearGradient>

          {/* High-Gloss Specular Rim Highlight */}
          <linearGradient id="liquidGlassRimStroke" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="rgba(255, 255, 255, 1)" />
            <stop offset="30%" stopColor="rgba(226, 232, 240, 0.7)" />
            <stop offset="70%" stopColor="rgba(203, 213, 225, 0.6)" />
            <stop offset="100%" stopColor="rgba(255, 255, 255, 1)" />
          </linearGradient>

          {/* Liquid Glass Tactile Drop Shadow & Caustic Light Filter */}
          <filter id="liquidGlassShadow" x="-10%" y="-10%" width="120%" height="120%">
            <feDropShadow dx="0" dy="20" stdDeviation="35" floodColor="#0F172A" floodOpacity="0.06" />
            <feDropShadow dx="0" dy="6" stdDeviation="12" floodColor="#0F172A" floodOpacity="0.04" />
          </filter>
        </defs>

        {/* ── Main Liquid Glass 4-Pointed Star (Tighter waist for larger quadrants) ── */}
        {/* Vertices touch (500,0), (1000,350), (500,700), (0,350) */}
        <path
          d="M 500 0 C 500 240, 680 350, 1000 350 C 680 350, 500 460, 500 700 C 500 460, 320 350, 0 350 C 320 350, 500 240, 500 0 Z"
          fill="url(#liquidGlassSurface)"
          stroke="url(#liquidGlassRimStroke)"
          strokeWidth="2"
          filter="url(#liquidGlassShadow)"
        />

        {/* Primary Specular Light Refraction Bevel along Top-Left & Bottom-Right Flanks */}
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

        {/* Subtle Caustic Highlight Curve */}
        <path
          d="M 500 0 C 500 240, 680 350, 1000 350"
          fill="none"
          stroke="rgba(255, 255, 255, 0.7)"
          strokeWidth="1.5"
          strokeLinecap="round"
          opacity="0.75"
        />
      </svg>

      {/* ═══ 3. Central Copilot Nexus (Snugly encased in the Liquid Glass Star) ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center pointer-events-auto">
        <div className="flex flex-col items-center mb-5">
          <h2 className="text-2xl font-black text-slate-800 tracking-tight drop-shadow-sm">
            {greeting}
          </h2>
          <p className="text-xs font-semibold text-slate-500 mt-1">
            今日有 <span className="text-blue-600 font-bold">{tasks.length}</span> 项待办事项
          </p>
        </div>

        {/* High-Gloss Frosted Glass Capsule Searchbox */}
        <form 
          onSubmit={handleStartCopilot} 
          className="w-[430px] bg-white/85 backdrop-blur-2xl border border-white/90 shadow-[0_12px_36px_rgba(15,23,42,0.06),0_1px_2px_rgba(255,255,255,0.9)_inset] rounded-full px-5 py-3 flex items-center gap-3 transition-all hover:bg-white/95 hover:shadow-[0_16px_44px_rgba(15,23,42,0.09)]"
        >
          <Sparkles className="w-4 h-4 text-blue-500 shrink-0" />
          <input
            type="text"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder="向 Copilot 发送指令或提问…"
            className="flex-1 bg-transparent text-xs outline-none text-slate-800 placeholder-slate-400 font-medium"
          />
          <button
            type="submit"
            className="w-7 h-7 flex items-center justify-center bg-blue-600 hover:bg-blue-700 text-white rounded-full transition-transform hover:scale-105 cursor-pointer shrink-0 shadow-sm"
          >
            <Send className="w-3.5 h-3.5 -ml-0.5" />
          </button>
        </form>
      </div>

      {/* ═══ 4. Four Expansive Quadrants (Spacious & Integrated) ═══ */}
      <div className="relative z-20 w-full h-full grid grid-cols-2 grid-rows-2 pointer-events-none">

        {/* ─── Q1 Top-Left: 下一步 ─── */}
        <div className="flex items-center justify-center p-8 pr-28 pb-16">
          <div className="w-full max-w-[340px] flex flex-col pointer-events-auto">
            <div className="mb-4">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-sm mb-0.5">
                <span className="w-2 h-2 rounded-full bg-blue-500" />
                下一步
              </div>
              <p className="text-[11px] text-slate-500">已确认且需亲自推进的真实事项</p>
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
                    className="flex items-center justify-between p-4 bg-white/60 hover:bg-white/95 backdrop-blur-md shadow-[0_4px_20px_rgba(15,23,42,0.03)] border border-white/80 rounded-2xl cursor-pointer group transition-all"
                  >
                    <div className="min-w-0 pr-3">
                      <div className="text-xs font-bold text-slate-800 group-hover:text-blue-700 truncate mb-0.5">
                        推进 {item.step}
                      </div>
                      <div className="text-[11px] text-slate-500 truncate">{item.company} · {item.title}</div>
                    </div>
                    <ArrowUpRight size={15} className="text-slate-400 group-hover:text-blue-600 shrink-0" />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ─── Q2 Top-Right: 待我确认 (3D Stacked Card Deck) ─── */}
        <div className="flex items-center justify-center p-8 pl-28 pb-16">
          <div className="w-full max-w-[360px] flex flex-col pointer-events-auto">
            <div className="flex items-center justify-between mb-4 shrink-0">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-sm">
                <span className="w-2 h-2 rounded-full bg-amber-500" />
                待我确认
              </div>
              <span className="text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-amber-100/80 text-amber-800 border border-amber-200/50">
                {tasks.length} 待决
              </span>
            </div>

            <div className="relative w-full h-[220px]">
              <AnimatePresence>
                {tasks.length > 0 ? (
                  tasks.map((task, idx) => {
                    const isTop = idx === 0;
                    return (
                      <motion.div
                        key={task.id}
                        layout
                        initial={{ opacity: 0, y: 30, scale: 0.95 }}
                        animate={{ 
                          opacity: 1 - idx * 0.15, 
                          y: idx * 10, 
                          scale: 1 - idx * 0.04,
                          zIndex: tasks.length - idx
                        }}
                        exit={{ opacity: 0, x: 200, scale: 0.9 }}
                        transition={{ duration: 0.3, ease: 'easeOut' }}
                        className={`absolute top-0 left-0 w-full bg-white/90 backdrop-blur-xl border border-white/80 shadow-[0_8px_30px_rgba(15,23,42,0.06)] rounded-2xl p-4 flex flex-col gap-2 ${!isTop && 'pointer-events-none'}`}
                        style={{ transformOrigin: 'top center' }}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <h3 className="text-xs font-bold text-slate-900 leading-snug flex-1">{task.title}</h3>
                          <div className="text-[9px] font-bold text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded shrink-0 border border-amber-200/60">
                            {task.badge}
                          </div>
                        </div>
                        <p className="text-[11px] text-slate-600 leading-tight line-clamp-2">{task.desc}</p>
                        <div className="bg-amber-50/60 border border-amber-100/70 py-1.5 px-2.5 text-[10px] text-amber-800 flex items-center gap-1.5 rounded-lg">
                          <Sparkles size={11} className="text-amber-500 shrink-0" />
                          <span className="truncate">{task.copilotTip}</span>
                        </div>
                        <div className="flex gap-2 pt-0.5">
                          <input
                            type="text"
                            placeholder="补充意见…"
                            disabled={!isTop}
                            className="flex-1 text-[11px] bg-slate-50 border border-slate-200/70 rounded-lg px-2.5 outline-none focus:border-blue-400 transition-colors h-8"
                          />
                          <button
                            type="button"
                            onClick={() => isTop && handleConfirm(task.id)}
                            disabled={!isTop}
                            className="px-3.5 h-8 bg-slate-800 hover:bg-slate-900 text-white text-[11px] font-bold rounded-lg transition-colors whitespace-nowrap shadow-sm cursor-pointer disabled:opacity-50"
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
                    className="absolute inset-0 flex flex-col items-center justify-center py-8 bg-white/30 backdrop-blur-md rounded-2xl border border-white/50"
                  >
                    <CheckCircle2 className="w-6 h-6 text-slate-400 mb-1.5 stroke-[1.5]" />
                    <p className="text-xs font-medium text-slate-500">全部处理完毕</p>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>

        {/* ─── Q3 Bottom-Left: 求职动态 ─── */}
        <div className="flex items-center justify-center p-8 pr-28 pt-16">
          <div className="w-full max-w-[340px] flex flex-col pointer-events-auto">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-sm">
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                求职动态
              </div>
              <button
                type="button"
                onClick={() => navigate('/career')}
                className="text-[11px] text-slate-500 hover:text-emerald-700 cursor-pointer flex items-center gap-0.5 font-bold transition-colors"
              >
                全部 <ArrowUpRight className="w-3 h-3" />
              </button>
            </div>
            <div className="flex-1 min-h-0 space-y-2.5">
              {careerEvents.map((ev) => (
                <div
                  key={ev.id}
                  onClick={() => navigate('/career')}
                  className="flex items-center justify-between p-4 bg-white/60 hover:bg-white/95 backdrop-blur-md shadow-[0_4px_20px_rgba(15,23,42,0.03)] border border-white/80 rounded-2xl cursor-pointer group transition-all"
                >
                  <span className="text-xs font-bold text-slate-800 group-hover:text-emerald-700 truncate pr-3">
                    {ev.company} · {ev.title}
                  </span>
                  <span className={`text-[10px] font-medium shrink-0 bg-white/80 px-2.5 py-0.5 rounded-full border border-white/80 ${ev.isClosed ? 'text-slate-400' : 'text-emerald-600'}`}>
                    {ev.step}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ─── Q4 Bottom-Right: Copilot 工作 ─── */}
        <div className="flex items-center justify-center p-8 pl-28 pt-16">
          <div className="w-full max-w-[360px] flex flex-col pointer-events-auto">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-sm">
                <span className="w-2 h-2 rounded-full bg-purple-500" />
                Copilot 工作
              </div>
              <button
                type="button"
                onClick={() => navigate('/activities')}
                className="text-[11px] text-slate-500 hover:text-purple-700 cursor-pointer flex items-center gap-0.5 font-bold transition-colors"
              >
                控制台 <ArrowUpRight className="w-3 h-3" />
              </button>
            </div>
            <div className="flex-1 min-h-0 space-y-2.5">
              {copilotWork.map((item) => (
                <div
                  key={item.id}
                  onClick={() => navigate('/activities')}
                  className="bg-white/60 hover:bg-white/95 backdrop-blur-md shadow-[0_4px_20px_rgba(15,23,42,0.03)] border border-white/80 rounded-2xl p-3.5 flex items-center justify-between cursor-pointer group transition-all"
                >
                  <div className="truncate pr-3 min-w-0">
                    <div className="text-xs font-bold text-slate-800 group-hover:text-purple-700 truncate mb-0.5">{item.title}</div>
                    <div className="text-[11px] text-slate-500 truncate">{item.detail}</div>
                  </div>
                  <span className={`px-2.5 py-1 rounded-full flex items-center gap-1.5 text-[9px] shrink-0 font-bold ${
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
