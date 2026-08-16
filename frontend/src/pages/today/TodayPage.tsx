import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Sparkles, CornerDownLeft } from 'lucide-react';
import { listJobOpportunities } from '@/api/careerProcess';
import { listPersistentTasks } from '@/api/persistentTasks';
import { NextStepWidget } from './widgets/NextStepWidget';
import { ConfirmationWidget } from './widgets/ConfirmationWidget';
import { CareerDynamicWidget } from './widgets/CareerDynamicWidget';
import { CopilotDynamicWidget } from './widgets/CopilotDynamicWidget';

function getGreetingTimeText() {
  const hour = new Date().getHours();
  if (hour < 6) return '夜深了';
  if (hour < 11) return '早上好';
  if (hour < 14) return '中午好';
  if (hour < 18) return '下午好';
  return '晚上好';
}

export function TodayPage() {
  const navigate = useNavigate();
  const [inputText, setInputText] = useState('');

  const opportunitiesQuery = useQuery({
    queryKey: ['today-opportunities'],
    queryFn: () => listJobOpportunities(false),
  });

  const tasksQuery = useQuery({
    queryKey: ['today-persistent-tasks'],
    queryFn: () => listPersistentTasks(),
  });

  const greeting = getGreetingTimeText();
  const opportunities = opportunitiesQuery.data ?? [];
  const tasks = tasksQuery.data ?? [];
  const pendingCount = 2;

  const handleStartCopilot = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!inputText.trim()) {
      navigate('/general-chat');
      return;
    }
    navigate(`/general-chat?prompt=${encodeURIComponent(inputText.trim())}`);
  };

  return (
    <div className="h-full w-full overflow-hidden select-none relative bg-[#F8FAFC] flex flex-col">
      {/* Background Organic Concave Crossroads Fluid Dividers */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none z-0"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <linearGradient id="curve-gradient-h" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#E2E8F0" stopOpacity="0.4" />
            <stop offset="50%" stopColor="#93C5FD" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#E2E8F0" stopOpacity="0.4" />
          </linearGradient>
          <linearGradient id="curve-gradient-v" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#E2E8F0" stopOpacity="0.4" />
            <stop offset="50%" stopColor="#C4B5FD" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#E2E8F0" stopOpacity="0.4" />
          </linearGradient>
          <radialGradient id="center-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#EEF2FF" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#F8FAFC" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Ambient Center Glow */}
        <circle cx="50%" cy="50%" r="35%" fill="url(#center-glow)" />

        {/* Horizontal dividing line with center concave contour */}
        <path
          d="M 0,50% H calc(50% - 260px) Q 50%,45% calc(50% + 260px),50% H 100%"
          fill="none"
          stroke="url(#curve-gradient-h)"
          strokeWidth="1.5"
        />

        {/* Vertical dividing line */}
        <line
          x1="50%"
          y1="0"
          x2="50%"
          y2="calc(50% - 100px)"
          stroke="url(#curve-gradient-v)"
          strokeWidth="1.5"
        />
        <line
          x1="50%"
          y1="calc(50% + 100px)"
          x2="50%"
          y2="100%"
          stroke="url(#curve-gradient-v)"
          strokeWidth="1.5"
        />
      </svg>

      {/* Center Floating Copilot Capsule Island */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-20 w-[92%] max-w-xl">
        <div className="p-4 md:p-5 rounded-3xl bg-white/95 backdrop-blur-2xl border border-slate-200/90 shadow-lg shadow-blue-500/5 flex flex-col items-center text-center space-y-2.5 transition-all hover:border-blue-300">
          {/* Dynamic Greeting */}
          <div>
            <h1 className="text-lg md:text-xl font-black text-slate-900 tracking-tight">
              {greeting}
            </h1>
            <p className="text-[11px] md:text-xs text-slate-500 font-medium mt-0.5">
              今天有 <span className="text-blue-600 font-bold">{pendingCount}</span> 件事情需要推进
            </p>
          </div>

          {/* Pure Conversation Input Pill */}
          <form onSubmit={handleStartCopilot} className="w-full relative flex items-center">
            <div className="absolute left-3.5 text-blue-600">
              <Sparkles size={16} />
            </div>

            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="向 Copilot 提问、指派任务或开启对话…"
              className="w-full pl-10 pr-20 py-2.5 rounded-2xl bg-slate-50 hover:bg-slate-100/70 focus:bg-white text-xs md:text-sm text-slate-800 placeholder-slate-400 border border-slate-200 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 outline-none transition-all shadow-inner-xs"
            />

            <button
              type="submit"
              className="absolute right-1.5 px-3 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-700 active:scale-95 text-white text-xs font-bold transition-all shadow-xs flex items-center gap-1 cursor-pointer"
            >
              <span>发送</span>
              <CornerDownLeft size={11} />
            </button>
          </form>
        </div>
      </div>

      {/* 4 Seamless Proportional Quadrant Zones (Filling 100% Height Without Scrolling) */}
      <div className="relative z-10 flex-1 grid grid-cols-2 grid-rows-2 p-4 md:p-6 lg:p-7 gap-x-8 gap-y-6">
        {/* Top-Left Quadrant: 下一步 (Next Step) */}
        <div className="h-full min-h-0 pb-12 pr-6">
          <NextStepWidget
            opportunities={opportunities}
            loading={opportunitiesQuery.isLoading}
          />
        </div>

        {/* Top-Right Quadrant: 待我确认 (Confirmation Stacked Queue) */}
        <div className="h-full min-h-0 pb-12 pl-6">
          <ConfirmationWidget />
        </div>

        {/* Bottom-Left Quadrant: 求职动态 (Career Dynamic) */}
        <div className="h-full min-h-0 pt-12 pr-6">
          <CareerDynamicWidget
            opportunities={opportunities}
            loading={opportunitiesQuery.isLoading}
          />
        </div>

        {/* Bottom-Right Quadrant: Copilot 工作 (Copilot Dynamic) */}
        <div className="h-full min-h-0 pt-12 pl-6">
          <CopilotDynamicWidget
            tasks={tasks}
            loading={tasksQuery.isLoading}
          />
        </div>
      </div>
    </div>
  );
}
