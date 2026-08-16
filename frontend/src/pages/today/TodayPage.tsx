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
    <div className="relative w-full h-full overflow-hidden select-none font-sans bg-slate-50 p-4 gap-4 grid grid-cols-2 grid-rows-2">
      
      {/* ═══ 1. Carved Organic Panels (4 Quadrants) ═══ */}
      
      {/* ─── Q1 Top-Left: 下一步 ─── */}
      <div 
        className="relative bg-blue-50/60 backdrop-blur-md shadow-[0_4px_24px_rgba(0,0,0,0.03)] border border-slate-200/60 rounded-[2rem] flex items-center justify-center p-10"
        style={{ 
          maskImage: 'radial-gradient(circle at bottom right, transparent 200px, black 201px)',
          WebkitMaskImage: 'radial-gradient(circle at bottom right, transparent 200px, black 201px)'
        }}
      >
        <div className="w-full max-w-[320px] flex flex-col -mt-16 -ml-16">
          <div className="mb-4">
            <div className="flex items-center gap-2 text-slate-900 font-bold text-base mb-1">
              <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
              下一步
            </div>
            <p className="text-[11px] text-slate-500">已确认且需亲自推进的真实事项</p>
          </div>

          {nextStepItems.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 opacity-70">
              <CheckCircle2 className="w-8 h-8 text-slate-400 mb-2 stroke-[1.5]" />
              <p className="text-xs font-medium text-slate-600">当前没有需要推进的动作</p>
            </div>
          ) : (
            <div className="space-y-2 flex-1">
              {nextStepItems.map((item) => (
                <div
                  key={item.id}
                  onClick={() => navigate(`/career?opportunity=${item.id}`)}
                  className="flex items-center justify-between p-3.5 bg-white/70 hover:bg-white shadow-sm border border-slate-100 rounded-2xl cursor-pointer group transition-all"
                >
                  <div className="min-w-0 pr-3">
                    <div className="text-xs font-bold text-slate-800 group-hover:text-blue-700 truncate mb-0.5">
                      推进 {item.step}
                    </div>
                    <div className="text-[10px] text-slate-500 truncate">{item.company} · {item.title}</div>
                  </div>
                  <ArrowUpRight size={14} className="text-slate-400 group-hover:text-blue-600 shrink-0" />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ─── Q2 Top-Right: 待我确认 (Card Deck Stack) ─── */}
      <div 
        className="relative bg-amber-50/50 backdrop-blur-md shadow-[0_4px_24px_rgba(0,0,0,0.03)] border border-slate-200/60 rounded-[2rem] flex items-center justify-center p-10"
        style={{ 
          maskImage: 'radial-gradient(circle at bottom left, transparent 200px, black 201px)',
          WebkitMaskImage: 'radial-gradient(circle at bottom left, transparent 200px, black 201px)'
        }}
      >
        <div className="w-full max-w-[340px] flex flex-col -mt-16 -mr-16">
          <div className="flex items-center justify-between mb-4 shrink-0">
            <div className="flex items-center gap-2 text-slate-900 font-bold text-base">
              <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
              待我确认
            </div>
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200/60">
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
                        y: idx * 12, 
                        scale: 1 - idx * 0.04,
                        zIndex: tasks.length - idx
                      }}
                      exit={{ opacity: 0, x: 200, scale: 0.9 }}
                      transition={{ duration: 0.3, ease: 'easeOut' }}
                      className={`absolute top-0 left-0 w-full bg-white border border-slate-200/80 shadow-[0_8px_24px_rgba(0,0,0,0.06)] rounded-2xl p-4 flex flex-col gap-2.5 ${!isTop && 'pointer-events-none'}`}
                      style={{ transformOrigin: 'top center' }}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <h3 className="text-[13px] font-bold text-slate-900 leading-snug flex-1">{task.title}</h3>
                        <div className="text-[9px] font-bold text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200/80 shrink-0">
                          {task.badge}
                        </div>
                      </div>
                      <p className="text-[11px] text-slate-600 leading-tight line-clamp-2">{task.desc}</p>
                      <div className="bg-amber-50/50 border border-amber-100/80 py-1.5 px-2.5 text-[10px] text-amber-800 flex items-center gap-1.5 rounded-lg">
                        <Sparkles size={11} className="text-amber-500 shrink-0" />
                        <span className="truncate">{task.copilotTip}</span>
                      </div>
                      <div className="flex gap-2 pt-1 mt-1">
                        <input
                          type="text"
                          placeholder="补充意见…"
                          disabled={!isTop}
                          className="flex-1 text-[11px] bg-slate-50 border border-slate-200/80 rounded-lg px-2.5 outline-none focus:border-blue-400 transition-colors h-8"
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
                  className="absolute inset-0 flex flex-col items-center justify-center py-8 opacity-70 bg-white/40 rounded-2xl border border-white/60 shadow-sm"
                >
                  <CheckCircle2 className="w-7 h-7 text-slate-400 mb-2 stroke-[1.5]" />
                  <p className="text-xs font-medium text-slate-600">全部处理完毕</p>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>

      {/* ─── Q3 Bottom-Left: 求职动态 ─── */}
      <div 
        className="relative bg-emerald-50/50 backdrop-blur-md shadow-[0_4px_24px_rgba(0,0,0,0.03)] border border-slate-200/60 rounded-[2rem] flex items-center justify-center p-10"
        style={{ 
          maskImage: 'radial-gradient(circle at top right, transparent 200px, black 201px)',
          WebkitMaskImage: 'radial-gradient(circle at top right, transparent 200px, black 201px)'
        }}
      >
        <div className="w-full max-w-[300px] flex flex-col -mb-16 -ml-16">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2 text-slate-900 font-bold text-base">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
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
          <div className="flex-1 min-h-0 space-y-2">
            {careerEvents.map((ev) => (
              <div
                key={ev.id}
                onClick={() => navigate('/career')}
                className="flex items-center justify-between p-3.5 bg-white/70 hover:bg-white shadow-sm border border-slate-100 rounded-2xl cursor-pointer group transition-all"
              >
                <span className="text-xs font-bold text-slate-800 group-hover:text-emerald-700 truncate pr-3">
                  {ev.company} · {ev.title}
                </span>
                <span className={`text-[10px] font-medium shrink-0 bg-white/60 px-2 py-0.5 rounded-full border border-slate-200/60 ${ev.isClosed ? 'text-slate-400' : 'text-emerald-600'}`}>
                  {ev.step}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ─── Q4 Bottom-Right: Copilot 工作 ─── */}
      <div 
        className="relative bg-purple-50/50 backdrop-blur-md shadow-[0_4px_24px_rgba(0,0,0,0.03)] border border-slate-200/60 rounded-[2rem] flex items-center justify-center p-10"
        style={{ 
          maskImage: 'radial-gradient(circle at top left, transparent 200px, black 201px)',
          WebkitMaskImage: 'radial-gradient(circle at top left, transparent 200px, black 201px)'
        }}
      >
        <div className="w-full max-w-[340px] flex flex-col -mb-16 -mr-16">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2 text-slate-900 font-bold text-base">
              <span className="w-2.5 h-2.5 rounded-full bg-purple-500" />
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
          <div className="flex-1 min-h-0 space-y-2">
            {copilotWork.map((item) => (
              <div
                key={item.id}
                onClick={() => navigate('/activities')}
                className="bg-white/70 hover:bg-white shadow-sm border border-slate-100 rounded-2xl p-3.5 flex items-center justify-between cursor-pointer group transition-all"
              >
                <div className="truncate pr-3 min-w-0">
                  <div className="text-xs font-bold text-slate-800 group-hover:text-purple-700 truncate mb-0.5">{item.title}</div>
                  <div className="text-[10px] text-slate-500 truncate">{item.detail}</div>
                </div>
                <span className={`px-2 py-1 rounded-full flex items-center gap-1.5 text-[9px] shrink-0 font-bold ${
                  item.state === 'active'
                    ? 'bg-blue-50 text-blue-700 border border-blue-200/60'
                    : 'bg-slate-50 text-slate-500 border border-slate-200/60'
                }`}>
                  {item.state === 'active' && <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />}
                  {item.state === 'active' ? '运行中' : '待命中'}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ═══ 2. Central Copilot Core (Seamless, NO floating box) ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center pointer-events-auto">
        <h2 className="text-2xl font-black text-slate-800 mb-1 tracking-tight">{greeting}</h2>
        <p className="text-sm font-medium text-slate-500 mb-6">
          今日有 <span className="text-blue-600 font-bold">{tasks.length}</span> 项待办事项
        </p>
        <form 
          onSubmit={handleStartCopilot} 
          className="w-[420px] bg-white shadow-[0_8px_30px_rgba(0,0,0,0.08)] border border-slate-200/80 rounded-full px-5 py-3 flex items-center gap-3 transition-shadow hover:shadow-[0_12px_40px_rgba(0,0,0,0.12)]"
        >
          <Sparkles className="w-5 h-5 text-blue-500 shrink-0" />
          <input
            type="text"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder="向 Copilot 发送指令或提问…"
            className="flex-1 bg-transparent text-sm outline-none text-slate-700 placeholder-slate-400"
          />
          <button
            type="submit"
            className="w-8 h-8 flex items-center justify-center bg-blue-600 hover:bg-blue-700 text-white rounded-full transition-colors cursor-pointer shrink-0"
          >
            <Send className="w-4 h-4 -ml-0.5" />
          </button>
        </form>
      </div>

    </div>
  );
}
