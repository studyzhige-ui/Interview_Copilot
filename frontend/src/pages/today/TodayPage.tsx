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
    <div className="h-[calc(100vh-64px)] w-full overflow-hidden select-none relative bg-[#F8FAFC] flex flex-col justify-between p-6">
      {/* Background Layer: Organic Astroid Concave Crossroads Fluid Dividers */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none z-0"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id="astroid-h" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#CBD5E1" stopOpacity="0.3" />
            <stop offset="50%" stopColor="#60A5FA" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#CBD5E1" stopOpacity="0.3" />
          </linearGradient>
          <linearGradient id="astroid-v" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#CBD5E1" stopOpacity="0.3" />
            <stop offset="50%" stopColor="#A78BFA" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#CBD5E1" stopOpacity="0.3" />
          </linearGradient>
          <radialGradient id="center-cradle-glow" cx="50%" cy="50%" r="45%">
            <stop offset="0%" stopColor="#EFF6FF" stopOpacity="0.8" />
            <stop offset="60%" stopColor="#F8FAFC" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#F8FAFC" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Center Organic Glow */}
        <circle cx="50%" cy="50%" r="30%" fill="url(#center-cradle-glow)" />

        {/* Organic Curved Partition Lines (Concave Curves meeting the center Copilot Island) */}
        {/* Horizontal Seam: from Left to Center Island, and from Right to Center Island */}
        <path
          d="M 0,50% Q 25%,50% calc(50% - 240px),50%"
          fill="none"
          stroke="url(#astroid-h)"
          strokeWidth="1.5"
        />
        <path
          d="M calc(50% + 240px),50% Q 75%,50% 100%,50%"
          fill="none"
          stroke="url(#astroid-h)"
          strokeWidth="1.5"
        />

        {/* Vertical Seam: from Top to Center Island, and from Bottom to Center Island */}
        <path
          d="M 50%,0 Q 50%,25% 50%,calc(50% - 60px)"
          fill="none"
          stroke="url(#astroid-v)"
          strokeWidth="1.5"
        />
        <path
          d="M 50%,calc(50% + 60px) Q 50%,75% 50%,100%"
          fill="none"
          stroke="url(#astroid-v)"
          strokeWidth="1.5"
        />
      </svg>

      {/* Center Copilot Capsule Island (The Visual Anchor of the Crossroads) */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-20 w-[90%] max-w-lg">
        <div className="p-3.5 md:p-4 rounded-3xl bg-white/95 backdrop-blur-2xl border border-slate-200/90 shadow-md shadow-blue-500/5 flex flex-col items-center text-center space-y-2 transition-all hover:border-blue-300">
          {/* Dynamic Greeting */}
          <div>
            <h1 className="text-base md:text-lg font-black text-slate-900 tracking-tight">
              {greeting}
            </h1>
            <p className="text-[11px] text-slate-500 font-medium mt-0.5">
              今天有 <span className="text-blue-600 font-bold">{pendingCount}</span> 件事情需要推进
            </p>
          </div>

          {/* Conversation Input Pill */}
          <form onSubmit={handleStartCopilot} className="w-full relative flex items-center">
            <div className="absolute left-3.5 text-blue-600">
              <Sparkles size={15} />
            </div>

            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="向 Copilot 提问、指派任务或开启对话…"
              className="w-full pl-9 pr-16 py-2 rounded-full bg-slate-50 hover:bg-slate-100/80 focus:bg-white text-xs text-slate-800 placeholder-slate-400 border border-slate-200 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 outline-none transition-all shadow-inner-xs"
            />

            <button
              type="submit"
              className="absolute right-1 px-3 py-1 rounded-full bg-blue-600 hover:bg-blue-700 active:scale-95 text-white text-[11px] font-bold transition-all shadow-xs flex items-center gap-1 cursor-pointer"
            >
              <span>发送</span>
              <CornerDownLeft size={10} />
            </button>
          </form>
        </div>
      </div>

      {/* 4 Seamless De-Cardified Quadrants (Directly on Canvas, with Margin to prevent Center Overlap) */}
      <div className="relative z-10 w-full h-full grid grid-cols-2 grid-rows-2">
        {/* Top-Left Quadrant: 下一步 (Next Step) */}
        <div className="h-full min-h-0 pb-16 pr-14">
          <NextStepWidget
            opportunities={opportunities}
            loading={opportunitiesQuery.isLoading}
          />
        </div>

        {/* Top-Right Quadrant: 待我确认 (Confirmation Stacked Queue) */}
        <div className="h-full min-h-0 pb-16 pl-14">
          <ConfirmationWidget />
        </div>

        {/* Bottom-Left Quadrant: 求职动态 (Career Dynamic) */}
        <div className="h-full min-h-0 pt-16 pr-14">
          <CareerDynamicWidget
            opportunities={opportunities}
            loading={opportunitiesQuery.isLoading}
          />
        </div>

        {/* Bottom-Right Quadrant: Copilot 工作 (Copilot Dynamic) */}
        <div className="h-full min-h-0 pt-16 pl-14">
          <CopilotDynamicWidget
            tasks={tasks}
            loading={tasksQuery.isLoading}
          />
        </div>
      </div>
    </div>
  );
}
