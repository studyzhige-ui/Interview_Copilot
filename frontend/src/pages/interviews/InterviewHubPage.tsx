import { useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Mic2,
  FileBarChart2,
  BookOpen,
  Sparkles,
  ArrowRight,
  CornerDownLeft,
  ChevronLeft,
} from 'lucide-react';
import { MockPage } from '@/pages/mock/MockPage';
import { ReviewPage } from '@/pages/review/ReviewPage';

export function InterviewHubPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const tab = searchParams.get('tab') || 'hub';
  const [prepPrompt, setPrepPrompt] = useState('');

  const handleStartPrep = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!prepPrompt.trim()) {
      navigate('/general-chat');
      return;
    }
    navigate(`/general-chat?prompt=${encodeURIComponent(`针对面试准备：${prepPrompt.trim()}`)}`);
  };

  // Full-screen sub-workspaces
  if (tab === 'mock') {
    return (
      <div className="h-full flex flex-col overflow-hidden bg-white">
        <div className="px-5 py-2.5 bg-white border-b border-slate-200/80 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSearchParams({ tab: 'hub' })}
              className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-blue-600 cursor-pointer transition-colors"
            >
              <ChevronLeft size={14} />
              <span>返回面试中枢</span>
            </button>
            <span className="text-slate-300">/</span>
            <span className="text-xs font-bold text-slate-900">模拟面试实战对练</span>
          </div>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto">
          <MockPage />
        </div>
      </div>
    );
  }

  if (tab === 'review') {
    return (
      <div className="h-full flex flex-col overflow-hidden bg-white">
        <div className="px-5 py-2.5 bg-white border-b border-slate-200/80 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSearchParams({ tab: 'hub' })}
              className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-blue-600 cursor-pointer transition-colors"
            >
              <ChevronLeft size={14} />
              <span>返回面试中枢</span>
            </button>
            <span className="text-slate-300">/</span>
            <span className="text-xs font-bold text-slate-900">真实面试录音深度复盘</span>
          </div>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto">
          <ReviewPage />
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full overflow-hidden select-none relative bg-[#F8FAFC] flex flex-col">
      {/* Background Organic Three-Direction Radiating Fluid Arc Dividers */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none z-0"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <linearGradient id="tri-arc-1" x1="0%" y1="0%" x2="50%" y2="50%">
            <stop offset="0%" stopColor="#93C5FD" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#3B82F6" stopOpacity="0.2" />
          </linearGradient>
          <linearGradient id="tri-arc-2" x1="100%" y1="50%" x2="50%" y2="50%">
            <stop offset="0%" stopColor="#C084FC" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#8B5CF6" stopOpacity="0.2" />
          </linearGradient>
          <linearGradient id="tri-arc-3" x1="50%" y1="100%" x2="50%" y2="50%">
            <stop offset="0%" stopColor="#6EE7B7" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#10B981" stopOpacity="0.2" />
          </linearGradient>
          <radialGradient id="tri-center-glow" cx="50%" cy="50%" r="40%">
            <stop offset="0%" stopColor="#EEF2FF" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#F8FAFC" stopOpacity="0" />
          </radialGradient>
        </defs>

        <circle cx="50%" cy="50%" r="35%" fill="url(#tri-center-glow)" />

        {/* 3 Radiating Fluid Dividing Rays from Center */}
        {/* Ray 1: Towards Top-Left (150 deg) */}
        <path
          d="M calc(50% - 150px),calc(50% - 50px) Q 35%,30% 0%,15%"
          fill="none"
          stroke="url(#tri-arc-1)"
          strokeWidth="1.5"
        />
        {/* Ray 2: Towards Right (0 deg) */}
        <path
          d="M calc(50% + 180px),50% Q 75%,45% 100%,45%"
          fill="none"
          stroke="url(#tri-arc-2)"
          strokeWidth="1.5"
        />
        {/* Ray 3: Towards Bottom-Left (220 deg) */}
        <path
          d="M calc(50% - 120px),calc(50% + 80px) Q 30%,75% 15%,100%"
          fill="none"
          stroke="url(#tri-arc-3)"
          strokeWidth="1.5"
        />
      </svg>

      {/* Center Radiating Copilot Core Island */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-20 w-[92%] max-w-lg">
        <div className="p-4 md:p-5 rounded-3xl bg-white/95 backdrop-blur-2xl border border-slate-200/90 shadow-lg shadow-indigo-500/5 flex flex-col items-center text-center space-y-2.5 transition-all hover:border-indigo-300">
          <div>
            <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-blue-50 text-blue-700 text-[10px] font-bold mb-1">
              <Mic2 size={11} />
              <span>全流程智能面试中枢</span>
            </div>
            <h1 className="text-base md:text-lg font-black text-slate-900 tracking-tight">
              面试备战 · 对练 · 复盘
            </h1>
          </div>

          {/* Conversation Input */}
          <form onSubmit={handleStartPrep} className="w-full relative flex items-center">
            <div className="absolute left-3.5 text-indigo-600">
              <Sparkles size={16} />
            </div>

            <input
              type="text"
              value={prepPrompt}
              onChange={(e) => setPrepPrompt(e.target.value)}
              placeholder="输入目标公司或考点（如：腾讯二面系统设计备战）…"
              className="w-full pl-10 pr-20 py-2.5 rounded-2xl bg-slate-50 hover:bg-slate-100/70 focus:bg-white text-xs md:text-sm text-slate-800 placeholder-slate-400 border border-slate-200 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 outline-none transition-all shadow-inner-xs"
            />

            <button
              type="submit"
              className="absolute right-1.5 px-3 py-1.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 active:scale-95 text-white text-xs font-bold transition-all shadow-xs flex items-center gap-1 cursor-pointer"
            >
              <span>生成</span>
              <CornerDownLeft size={11} />
            </button>
          </form>
        </div>
      </div>

      {/* Three Seamless Spatial Fluid Partitions Filling the Entire Viewport */}
      <div className="relative z-10 flex-1 grid grid-cols-1 md:grid-cols-2 grid-rows-2 p-6 md:p-8 gap-8">
        {/* Sector 1: Top-Left - 面试准备与考点速查 (Interview Prep) */}
        <div
          onClick={() => navigate('/general-chat?prompt=帮我做针对性面试备战与高频考点预测')}
          className="group flex flex-col justify-between p-6 rounded-3xl bg-blue-50/20 hover:bg-blue-50/50 border border-blue-100/60 hover:border-blue-300 transition-all cursor-pointer select-none"
        >
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold shadow-2xs group-hover:scale-105 transition-transform">
                <BookOpen size={16} />
              </div>
              <h2 className="text-sm font-bold text-slate-900 group-hover:text-blue-600 transition-colors">
                面试准备与考点速查
              </h2>
            </div>
            <p className="text-xs text-slate-500 leading-relaxed max-w-sm">
              智能解析目标岗位 JD、深挖业务背景、提炼核心追问考点与 STAR 结构化应答指南。
            </p>
          </div>

          <div className="pt-2 flex items-center gap-1 text-xs font-bold text-blue-600 group-hover:translate-x-1 transition-transform">
            <span>进入备战空间</span>
            <ArrowRight size={13} />
          </div>
        </div>

        {/* Sector 2: Right - 模拟面试实战对练 (Mock Interview) */}
        <div
          onClick={() => setSearchParams({ tab: 'mock' })}
          className="group row-span-2 flex flex-col justify-between p-7 rounded-3xl bg-purple-50/20 hover:bg-purple-50/50 border border-purple-100/60 hover:border-purple-300 transition-all cursor-pointer select-none"
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="w-10 h-10 rounded-2xl bg-purple-50 text-purple-600 flex items-center justify-center font-bold shadow-2xs group-hover:scale-105 transition-transform">
                <Mic2 size={20} />
              </div>
              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 text-purple-800 border border-purple-200">
                实时语音实战
              </span>
            </div>

            <div>
              <h2 className="text-base font-bold text-slate-900 group-hover:text-purple-700 transition-colors">
                模拟面试实战对练
              </h2>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                沉浸式多轮语音/文本对练，AI 面试官实时深度追问与应变考核，即时出具雷达评分与改进诊断。
              </p>
            </div>
          </div>

          <div className="pt-4 border-t border-purple-100/60 flex items-center justify-between text-xs font-bold text-purple-700">
            <span>开启模拟面试</span>
            <ArrowRight size={14} className="group-hover:translate-x-1 transition-transform" />
          </div>
        </div>

        {/* Sector 3: Bottom-Left - 真实面试深度复盘 (Interview Review) */}
        <div
          onClick={() => setSearchParams({ tab: 'review' })}
          className="group flex flex-col justify-between p-6 rounded-3xl bg-emerald-50/20 hover:bg-emerald-50/50 border border-emerald-100/60 hover:border-emerald-300 transition-all cursor-pointer select-none"
        >
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center font-bold shadow-2xs group-hover:scale-105 transition-transform">
                <FileBarChart2 size={16} />
              </div>
              <h2 className="text-sm font-bold text-slate-900 group-hover:text-emerald-700 transition-colors">
                真实面试深度复盘
              </h2>
            </div>
            <p className="text-xs text-slate-500 leading-relaxed max-w-sm">
              一键导入实战录音，WhisperX 极速逐字转写，AI 多维诊断、答题结构优化与证据链沉淀。
            </p>
          </div>

          <div className="pt-2 flex items-center gap-1 text-xs font-bold text-emerald-700 group-hover:translate-x-1 transition-transform">
            <span>进入复盘工作区</span>
            <ArrowRight size={13} />
          </div>
        </div>
      </div>
    </div>
  );
}
