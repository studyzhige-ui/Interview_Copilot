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
    <div className="relative w-full h-full overflow-hidden select-none font-sans bg-white">
      {/* ═══ 1. Aurora Radial Glow Colors ═══ */}
      <div className="absolute inset-0 z-0 opacity-80 pointer-events-none">
        {/* Center white convergence */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] rounded-full bg-white/90 blur-[120px] z-10" />
        {/* Top-left: 淡蓝光 (#E0F2FE) */}
        <div className="absolute -top-[10%] -left-[10%] w-[60%] h-[60%] rounded-full bg-[#E0F2FE]/80 blur-[130px]" />
        {/* Top-right: 暖橙/琥珀光 (#FEF3C7) */}
        <div className="absolute -top-[10%] -right-[10%] w-[60%] h-[60%] rounded-full bg-[#FEF3C7]/80 blur-[130px]" />
        {/* Bottom-left: 薄荷绿 (#DCFCE7) */}
        <div className="absolute -bottom-[10%] -left-[10%] w-[60%] h-[60%] rounded-full bg-[#DCFCE7]/80 blur-[130px]" />
        {/* Bottom-right: 丁香紫 (#F3E8FF) */}
        <div className="absolute -bottom-[10%] -right-[10%] w-[60%] h-[60%] rounded-full bg-[#F3E8FF]/80 blur-[130px]" />
      </div>

      {/* ═══ 2. Astroid Concave Seams (SVG) ═══ */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none z-0"
        viewBox="0 0 1000 700"
        preserveAspectRatio="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path d="M 500 0 C 500 250 250 350 0 350" stroke="rgba(226, 232, 240, 0.8)" strokeWidth="1.5" fill="none" />
        <path d="M 500 0 C 500 250 750 350 1000 350" stroke="rgba(226, 232, 240, 0.8)" strokeWidth="1.5" fill="none" />
        <path d="M 500 700 C 500 450 250 350 0 350" stroke="rgba(226, 232, 240, 0.8)" strokeWidth="1.5" fill="none" />
        <path d="M 500 700 C 500 450 750 350 1000 350" stroke="rgba(226, 232, 240, 0.8)" strokeWidth="1.5" fill="none" />
      </svg>

      {/* ═══ 3. Center Copilot Capsule (Ultra-thin, Max Height 110px) ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30">
        <div className="w-[380px] h-auto backdrop-blur-xl bg-white/70 border border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)] rounded-[2rem] p-3.5 flex flex-col items-center justify-center gap-2">
          <div className="w-full flex items-center justify-between px-2">
            <h2 className="text-sm font-bold text-slate-800 flex items-center gap-1.5">
              <Sparkles className="w-4 h-4 text-blue-500" />
              {greeting}
            </h2>
            <p className="text-[10px] font-medium text-slate-500 bg-white/50 px-2 py-0.5 rounded-full border border-white/60">
              今日 <span className="text-blue-600 font-bold">{tasks.length}</span> 项待办
            </p>
          </div>
          <form onSubmit={handleStartCopilot} className="w-full relative">
            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="向 Copilot 发送指令或提问…"
              className="w-full h-10 bg-white/60 border border-slate-200/50 rounded-2xl pl-4 pr-12 text-xs outline-none text-slate-700 placeholder-slate-400 focus:bg-white/90 transition-colors shadow-inner shadow-slate-100/50"
            />
            <button
              type="submit"
              className="absolute right-1 top-1 bottom-1 w-8 flex items-center justify-center bg-blue-600 hover:bg-blue-700 text-white rounded-xl transition-colors cursor-pointer"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>
      </div>

      {/* ═══ 4. Four Quadrants (Strict grid, inward padding to avoid capsule) ═══ */}
      <div className="relative z-10 w-full h-full grid grid-cols-2 grid-rows-2">

        {/* ─── Q1 Top-Left: 下一步 ─── */}
        <div className="overflow-hidden flex flex-col pt-8 pl-8 pr-16 pb-16">
          <div className="mb-3">
            <div className="flex items-center gap-2 text-slate-900 font-bold text-base mb-0.5">
              <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
              下一步
            </div>
            <p className="text-[11px] text-slate-400">已确认且需你亲自推进的真实事项</p>
          </div>

          {nextStepItems.length === 0 ? (
            <div className="flex flex-col items-center justify-center flex-1 text-center opacity-70">
              <CheckCircle2 className="w-6 h-6 text-slate-400 mb-1.5 stroke-[1.5]" />
              <p className="text-xs font-medium text-slate-600">当前没有需要推进的动作</p>
            </div>
          ) : (
            <div className="space-y-0 flex-1 min-h-0 overflow-y-auto">
              {nextStepItems.map((item) => (
                <div
                  key={item.id}
                  onClick={() => navigate(`/career?opportunity=${item.id}`)}
                  className="flex items-center justify-between py-2 border-b border-white/40 cursor-pointer group hover:bg-white/20 px-2 -mx-2 rounded-lg transition-colors"
                >
                  <div className="min-w-0 pr-2">
                    <div className="text-xs font-bold text-slate-800 group-hover:text-blue-700 truncate">
                      推进 {item.step}
                    </div>
                    <div className="text-[10px] text-slate-500 truncate">{item.company} · {item.title}</div>
                  </div>
                  <ArrowUpRight size={13} className="text-slate-400 group-hover:text-blue-600 shrink-0" />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ─── Q2 Top-Right: 待我确认 (Strict height limit) ─── */}
        <div className="overflow-hidden flex flex-col pt-8 pr-8 pl-16 pb-16">
          <div className="flex items-center justify-between mb-3 shrink-0">
            <div className="flex items-center gap-2 text-slate-900 font-bold text-base">
              <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
              待我确认
            </div>
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100/60 text-amber-700 border border-amber-200/50">
              {tasks.length} 待决
            </span>
          </div>

          <div className="relative flex-1 flex flex-col justify-start min-h-0">
            <AnimatePresence mode="popLayout">
              {tasks.length > 0 ? (
                tasks.map((task, idx) => {
                  // Expanded active card
                  if (idx === 0) {
                    return (
                      <motion.div
                        key={task.id}
                        layout
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, x: 120 }}
                        transition={{ duration: 0.25 }}
                        className="backdrop-blur-md bg-white/70 border border-white shadow-sm rounded-2xl p-3 mb-2 shrink-0 flex flex-col gap-2"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <h3 className="text-xs font-bold text-slate-900 leading-snug flex-1">{task.title}</h3>
                          <div className="text-[9px] font-bold text-amber-700 bg-amber-50/80 px-1.5 py-0.5 rounded border border-amber-200/60 shrink-0">
                            {task.badge}
                          </div>
                        </div>
                        <p className="text-[10px] text-slate-600 leading-tight line-clamp-2">{task.desc}</p>
                        <div className="bg-gradient-to-r from-amber-50/60 to-transparent border-l-2 border-amber-400 py-1 px-2 text-[10px] text-amber-800 flex items-center gap-1.5 rounded-r">
                          <Sparkles size={10} className="text-amber-500 shrink-0" />
                          <span className="truncate">{task.copilotTip}</span>
                        </div>
                        <div className="flex gap-2 pt-1 mt-auto">
                          <input
                            type="text"
                            placeholder="意见…"
                            className="flex-1 text-[10px] bg-white/80 border border-slate-200/60 rounded-lg px-2 outline-none focus:border-blue-400 transition-colors h-7"
                          />
                          <button
                            type="button"
                            onClick={() => handleConfirm(task.id)}
                            className="px-3 h-7 bg-slate-900 hover:bg-slate-800 text-white text-[10px] font-bold rounded-lg transition-colors whitespace-nowrap shadow-xs cursor-pointer"
                          >
                            确认执行
                          </button>
                        </div>
                      </motion.div>
                    );
                  }
                  // Collapsed pill items
                  return (
                    <motion.div
                      key={task.id}
                      layout
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0, x: 80 }}
                      transition={{ duration: 0.2 }}
                      onClick={() => {
                        setTasks((prev) => {
                          const target = prev.find((t) => t.id === task.id);
                          if (!target) return prev;
                          return [target, ...prev.filter((t) => t.id !== task.id)];
                        });
                      }}
                      className="bg-white/40 border border-white/60 shadow-sm rounded-full px-3 h-8 shrink-0 mb-1.5 flex items-center justify-between text-[10px] text-slate-600 hover:bg-white/70 cursor-pointer transition-all"
                    >
                      <span className="truncate font-medium">{task.title}</span>
                      <ChevronRight className="w-3 h-3 text-slate-400 shrink-0" />
                    </motion.div>
                  );
                })
              ) : (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="flex-1 flex flex-col items-center justify-center text-center opacity-70"
                >
                  <CheckCircle2 className="w-6 h-6 text-slate-400 mb-1.5 stroke-[1.5]" />
                  <p className="text-xs font-medium text-slate-600">全部处理完毕</p>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* ─── Q3 Bottom-Left: 求职动态 ─── */}
        <div className="overflow-hidden flex flex-col pb-8 pl-8 pr-16 pt-16">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-slate-900 font-bold text-sm">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              求职动态
            </div>
            <button
              type="button"
              onClick={() => navigate('/career')}
              className="text-[10px] text-slate-500 hover:text-emerald-700 cursor-pointer flex items-center gap-0.5 font-bold transition-colors"
            >
              查看全部 <ArrowUpRight className="w-3 h-3" />
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto">
            {careerEvents.map((ev) => (
              <div
                key={ev.id}
                onClick={() => navigate('/career')}
                className="flex items-center justify-between py-2 border-b border-white/40 cursor-pointer group hover:bg-white/20 px-2 -mx-2 rounded-lg transition-colors"
              >
                <span className="text-xs font-bold text-slate-800 group-hover:text-emerald-700 truncate pr-2">
                  {ev.company} · {ev.title}
                </span>
                <span className={`text-[10px] font-medium shrink-0 ${ev.isClosed ? 'text-slate-400' : 'text-emerald-600'}`}>
                  {ev.step}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* ─── Q4 Bottom-Right: Copilot 工作 ─── */}
        <div className="overflow-hidden flex flex-col pb-8 pr-8 pl-16 pt-16">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-slate-900 font-bold text-sm">
              <span className="w-2 h-2 rounded-full bg-purple-500" />
              Copilot 工作
            </div>
            <button
              type="button"
              onClick={() => navigate('/activities')}
              className="text-[10px] text-slate-500 hover:text-purple-700 cursor-pointer flex items-center gap-0.5 font-bold transition-colors"
            >
              活动中心 <ArrowUpRight className="w-3 h-3" />
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto space-y-2">
            {copilotWork.map((item) => (
              <div
                key={item.id}
                onClick={() => navigate('/activities')}
                className="bg-white/40 border border-white/50 shadow-sm rounded-xl p-2.5 flex items-center justify-between cursor-pointer group hover:bg-white/70 transition-colors"
              >
                <div className="truncate pr-2 min-w-0">
                  <div className="text-xs font-bold text-slate-800 group-hover:text-purple-700 truncate">{item.title}</div>
                  <div className="text-[10px] text-slate-500 truncate mt-0.5">{item.detail}</div>
                </div>
                <span className={`px-2 py-0.5 rounded flex items-center gap-1 text-[9px] shrink-0 font-bold ${
                  item.state === 'active'
                    ? 'bg-blue-100/80 text-blue-700'
                    : 'bg-slate-200/60 text-slate-500'
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
  );
}
