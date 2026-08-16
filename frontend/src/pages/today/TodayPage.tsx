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
    <div className="relative w-full h-full overflow-hidden select-none font-sans bg-[#F8FAFC]">
      
      {/* ═══ 1. Aurora Radial Glow Background ═══ */}
      <div className="absolute inset-0 z-0 opacity-90 pointer-events-none">
        {/* Top-left: 淡蓝光 (#E0F2FE) */}
        <div className="absolute top-[-10%] left-[-10%] w-[60%] h-[60%] rounded-full bg-[#E0F2FE]/80 blur-[140px]" />
        {/* Top-right: 暖橙/琥珀光 (#FEF3C7) */}
        <div className="absolute top-[-10%] right-[-10%] w-[60%] h-[60%] rounded-full bg-[#FEF3C7]/80 blur-[140px]" />
        {/* Bottom-left: 薄荷绿 (#DCFCE7) */}
        <div className="absolute bottom-[-10%] left-[-10%] w-[60%] h-[60%] rounded-full bg-[#DCFCE7]/80 blur-[140px]" />
        {/* Bottom-right: 丁香紫 (#F3E8FF) */}
        <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] rounded-full bg-[#F3E8FF]/80 blur-[140px]" />
      </div>

      {/* ═══ 2. Central Nexus (White Core Depth Dropoff) ═══ */}
      {/* 采用面与面之间的软过渡，极大的弥散阴影和模糊构成视觉焦点，而非硬线条 */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[700px] rounded-full bg-white/70 blur-[100px] pointer-events-none z-10" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[450px] h-[450px] rounded-full bg-white/90 shadow-[0_0_80px_rgba(255,255,255,1)] blur-[40px] pointer-events-none z-10" />

      {/* ═══ 3. Central Copilot Island (Input Controls) ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center">
        {/* 浑然一体的轻量灵动胶囊 */}
        <div className="w-[380px] backdrop-blur-2xl bg-white/80 border border-white/90 shadow-[0_8px_30px_rgba(0,0,0,0.04)] rounded-[2rem] p-3 flex flex-col items-center gap-2">
          <div className="w-full flex items-center justify-between px-3">
            <h2 className="text-sm font-bold text-slate-800 flex items-center gap-1.5">
              <Sparkles className="w-4 h-4 text-blue-500" />
              {greeting}
            </h2>
            <p className="text-[10px] font-medium text-slate-500">
              今日 <span className="text-blue-600 font-bold">{tasks.length}</span> 项待办
            </p>
          </div>
          <form onSubmit={handleStartCopilot} className="w-full relative">
            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="向 Copilot 发送指令或提问…"
              className="w-full h-11 bg-white/60 border border-slate-200/50 rounded-2xl pl-4 pr-12 text-xs outline-none text-slate-700 placeholder-slate-400 focus:bg-white/90 transition-colors shadow-inner shadow-slate-100/50"
            />
            <button
              type="submit"
              className="absolute right-1.5 top-1.5 bottom-1.5 w-8 flex items-center justify-center bg-blue-600 hover:bg-blue-700 text-white rounded-xl transition-colors cursor-pointer shadow-sm"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>
      </div>

      {/* ═══ 4. Four Quadrants (Strict flex layout for perfect centering) ═══ */}
      <div className="relative z-20 w-full h-full grid grid-cols-2 grid-rows-2">

        {/* ─── Q1 Top-Left: 下一步 ─── */}
        <div className="flex items-center justify-center p-10 pr-28 pb-20">
          <div className="w-full max-w-[300px] flex flex-col">
            <div className="mb-4 text-center">
              <div className="flex items-center justify-center gap-2 text-slate-900 font-bold text-base mb-1">
                <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                下一步
              </div>
              <p className="text-[11px] text-slate-500">已确认且需亲自推进的真实事项</p>
            </div>

            {nextStepItems.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-6 opacity-70 bg-white/40 rounded-2xl border border-white/60 shadow-sm">
                <CheckCircle2 className="w-6 h-6 text-slate-400 mb-2 stroke-[1.5]" />
                <p className="text-xs font-medium text-slate-600">当前没有需要推进的动作</p>
              </div>
            ) : (
              <div className="space-y-1.5 flex-1 min-h-0 overflow-y-auto pr-2 custom-scrollbar">
                {nextStepItems.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => navigate(`/career?opportunity=${item.id}`)}
                    className="flex items-center justify-between p-3 bg-white/50 hover:bg-white/80 border border-white/60 shadow-sm rounded-xl cursor-pointer group transition-all"
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

        {/* ─── Q2 Top-Right: 待我确认 (Strict boundary) ─── */}
        <div className="flex items-center justify-center p-10 pl-28 pb-20">
          <div className="w-full max-w-[340px] flex flex-col h-full max-h-[300px] justify-center">
            <div className="flex items-center justify-between mb-4 shrink-0 px-2">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-base">
                <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                待我确认
              </div>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200">
                {tasks.length} 待决
              </span>
            </div>

            <div className="relative flex-1 flex flex-col justify-start min-h-0">
              <AnimatePresence mode="popLayout">
                {tasks.length > 0 ? (
                  tasks.map((task, idx) => {
                    // Top Expanded Card
                    if (idx === 0) {
                      return (
                        <motion.div
                          key={task.id}
                          layout
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, x: 120 }}
                          transition={{ duration: 0.25 }}
                          className="backdrop-blur-xl bg-white/80 border border-white shadow-md shadow-amber-900/5 rounded-2xl p-3.5 mb-2.5 shrink-0 flex flex-col gap-2.5 relative overflow-hidden"
                        >
                          {/* Inner soft glow for card */}
                          <div className="absolute top-0 right-0 w-32 h-32 bg-amber-400/10 blur-2xl rounded-full pointer-events-none" />
                          
                          <div className="flex items-start justify-between gap-2 relative z-10">
                            <h3 className="text-[13px] font-bold text-slate-900 leading-snug flex-1">{task.title}</h3>
                            <div className="text-[9px] font-bold text-amber-700 bg-amber-100/80 px-1.5 py-0.5 rounded border border-amber-200 shrink-0">
                              {task.badge}
                            </div>
                          </div>
                          <p className="text-[11px] text-slate-600 leading-tight line-clamp-2 relative z-10">{task.desc}</p>
                          <div className="bg-gradient-to-r from-amber-50/80 to-white/40 border-l-2 border-amber-400 py-1.5 px-2.5 text-[10px] text-amber-800 flex items-center gap-1.5 rounded-r relative z-10">
                            <Sparkles size={11} className="text-amber-500 shrink-0" />
                            <span className="truncate">{task.copilotTip}</span>
                          </div>
                          <div className="flex gap-2 pt-1 mt-1 relative z-10">
                            <input
                              type="text"
                              placeholder="补充意见…"
                              className="flex-1 text-[11px] bg-white border border-slate-200/80 rounded-lg px-2.5 outline-none focus:border-blue-400 transition-colors h-8"
                            />
                            <button
                              type="button"
                              onClick={() => handleConfirm(task.id)}
                              className="px-3.5 h-8 bg-slate-800 hover:bg-slate-900 text-white text-[11px] font-bold rounded-lg transition-colors whitespace-nowrap shadow-sm cursor-pointer"
                            >
                              确认执行
                            </button>
                          </div>
                        </motion.div>
                      );
                    }
                    // Collapsed Pills
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
                        className="bg-white/60 backdrop-blur-md border border-white shadow-sm rounded-full px-4 h-9 shrink-0 mb-2 flex items-center justify-between text-[11px] text-slate-700 hover:bg-white/90 cursor-pointer transition-all"
                      >
                        <span className="truncate font-medium">{task.title}</span>
                        <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                      </motion.div>
                    );
                  })
                ) : (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="flex-1 flex flex-col items-center justify-center py-8 opacity-70 bg-white/40 rounded-2xl border border-white/60 shadow-sm"
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
        <div className="flex items-center justify-center p-10 pr-28 pt-20">
          <div className="w-full max-w-[300px] flex flex-col">
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
            <div className="flex-1 min-h-0 space-y-1.5">
              {careerEvents.map((ev) => (
                <div
                  key={ev.id}
                  onClick={() => navigate('/career')}
                  className="flex items-center justify-between p-3 bg-white/50 hover:bg-white/80 border border-white/60 shadow-sm rounded-xl cursor-pointer group transition-all"
                >
                  <span className="text-xs font-bold text-slate-800 group-hover:text-emerald-700 truncate pr-3">
                    {ev.company} · {ev.title}
                  </span>
                  <span className={`text-[10px] font-medium shrink-0 bg-white/60 px-2 py-0.5 rounded-full border border-white/80 ${ev.isClosed ? 'text-slate-400' : 'text-emerald-600'}`}>
                    {ev.step}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ─── Q4 Bottom-Right: Copilot 工作 ─── */}
        <div className="flex items-center justify-center p-10 pl-28 pt-20">
          <div className="w-full max-w-[340px] flex flex-col">
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
                  className="bg-white/50 backdrop-blur-sm border border-white/70 shadow-sm rounded-2xl p-3 flex items-center justify-between cursor-pointer group hover:bg-white/80 transition-all"
                >
                  <div className="truncate pr-3 min-w-0">
                    <div className="text-xs font-bold text-slate-800 group-hover:text-purple-700 truncate mb-0.5">{item.title}</div>
                    <div className="text-[10px] text-slate-500 truncate">{item.detail}</div>
                  </div>
                  <span className={`px-2 py-1 rounded-full flex items-center gap-1.5 text-[9px] shrink-0 font-bold ${
                    item.state === 'active'
                      ? 'bg-blue-100 text-blue-700 border border-blue-200'
                      : 'bg-white text-slate-500 border border-slate-200'
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
