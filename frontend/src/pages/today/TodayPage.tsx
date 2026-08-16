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

  // Fetch opportunities for NextStep and CareerDynamics
  const opportunitiesQuery = useQuery({
    queryKey: ['today-opportunities'],
    queryFn: () => listJobOpportunities(false),
  });

  // Fetch persistent tasks for CopilotDynamic
  const tasksQuery = useQuery({
    queryKey: ['today-persistent-tasks'],
    queryFn: () => listPersistentTasks(),
  });

  const greeting = getGreetingTimeText();
  const opportunities = opportunitiesQuery.data ?? [];
  const tasks = tasksQuery.data ?? [];

  // Calculate pending items count for dynamic greeting
  const pendingCount = 2; // Can be derived from active next steps + confirmations

  const handleStartCopilot = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!inputText.trim()) {
      navigate('/general-chat');
      return;
    }
    // Navigate with initial query
    navigate(`/general-chat?prompt=${encodeURIComponent(inputText.trim())}`);
  };

  return (
    <div className="h-full w-full overflow-y-auto p-4 md:p-6 lg:p-8 flex flex-col justify-center select-none bg-[#F8FAFC]">
      <div className="mx-auto w-full max-w-6xl h-full flex flex-col justify-between space-y-6">
        {/* Four-Quadrant Center-Radiating Spatial Grid */}
        <div className="relative flex-1 grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">
          {/* Top-Left Quadrant: 下一步 (Next Step) */}
          <div className="min-h-[300px] h-[340px] flex flex-col">
            <NextStepWidget
              opportunities={opportunities}
              loading={opportunitiesQuery.isLoading}
            />
          </div>

          {/* Top-Right Quadrant: 待我确认 (Confirmation Stacked Queue Cards) */}
          <div className="min-h-[300px] h-[340px] flex flex-col">
            <ConfirmationWidget />
          </div>

          {/* Center Floating Copilot Island (Pinned between quadrants) */}
          <div className="col-span-1 lg:col-span-2 flex flex-col items-center justify-center my-1 z-10">
            <div className="w-full max-w-xl p-5 rounded-3xl bg-white/95 backdrop-blur-xl border border-slate-200/90 shadow-md flex flex-col items-center text-center space-y-3 transition-all hover:border-blue-300">
              {/* Dynamic Greeting */}
              <div>
                <h1 className="text-xl md:text-2xl font-black text-slate-900 tracking-tight">
                  {greeting}
                </h1>
                <p className="text-xs md:text-sm text-slate-500 font-medium mt-1">
                  今天有 <span className="text-blue-600 font-bold">{pendingCount}</span> 件事情需要推进
                </p>
              </div>

              {/* Pure Conversation Input Pill */}
              <form
                onSubmit={handleStartCopilot}
                className="w-full relative flex items-center"
              >
                <div className="absolute left-4 text-blue-600">
                  <Sparkles size={18} />
                </div>

                <input
                  type="text"
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  placeholder="向 Copilot 提问、指派任务或开启对话…"
                  className="w-full pl-11 pr-24 py-3.5 rounded-2xl bg-slate-50 hover:bg-slate-100/80 focus:bg-white text-sm text-slate-800 placeholder-slate-400 border border-slate-200/90 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 outline-none transition-all shadow-inner-xs"
                />

                <button
                  type="submit"
                  className="absolute right-2 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 active:scale-95 text-white text-xs font-bold transition-all shadow-xs flex items-center gap-1 cursor-pointer"
                >
                  <span>发送</span>
                  <CornerDownLeft size={13} />
                </button>
              </form>
            </div>
          </div>

          {/* Bottom-Left Quadrant: 求职动态 (Career Dynamic) */}
          <div className="min-h-[280px] h-[320px] flex flex-col">
            <CareerDynamicWidget
              opportunities={opportunities}
              loading={opportunitiesQuery.isLoading}
            />
          </div>

          {/* Bottom-Right Quadrant: Copilot 动态 (Copilot Dynamic) */}
          <div className="min-h-[280px] h-[320px] flex flex-col">
            <CopilotDynamicWidget
              tasks={tasks}
              loading={tasksQuery.isLoading}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
