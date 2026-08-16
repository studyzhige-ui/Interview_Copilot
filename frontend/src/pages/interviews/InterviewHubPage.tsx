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
    <div className="h-[calc(100vh-64px)] w-full overflow-hidden select-none relative bg-[#F8FAFC] flex flex-col justify-between p-6">
      {/* Background Organic Y-Shaped Fluid Dividers */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none z-0"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id="y-arc-top" x1="50%" y1="0%" x2="50%" y2="50%">
            <stop offset="0%" stopColor="#CBD5E1" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#60A5FA" stopOpacity="0.8" />
          </linearGradient>
          <linearGradient id="y-arc-right" x1="50%" y1="50%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#C084FC" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#CBD5E1" stopOpacity="0.3" />
          </linearGradient>
          <linearGradient id="y-arc-left" x1="50%" y1="50%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#34D399" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#CBD5E1" stopOpacity="0.3" />
          </linearGradient>
          <radialGradient id="y-center-glow" cx="50%" cy="50%" r="40%">
            <stop offset="0%" stopColor="#EEF2FF" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#F8FAFC" stopOpacity="0" />
          </radialGradient>
        </defs>

        <circle cx="50%" cy="50%" r="30%" fill="url(#y-center-glow)" />

        {/* 3 Y-Shaped Smooth Fluid Seams Radiating from Center */}
        {/* Ray 1: Top Dividing Seam (separating left and right top bounds) */}
        <path
          d="M 50%,0 Q 50%,25% 50%,calc(50% - 70px)"
          fill="none"
          stroke="url(#y-arc-top)"
          strokeWidth="1.5"
        />

        {/* Ray 2: Bottom-Right Dividing Seam */}
        <path
          d="M calc(50% + 180px),calc(50% + 30px) Q 75%,75% 100%,100%"
          fill="none"
          stroke="url(#y-arc-right)"
          strokeWidth="1.5"
        />

        {/* Ray 3: Bottom-Left Dividing Seam */}
        <path
          d="M calc(50% - 180px),calc(50% + 30px) Q 25%,75% 0%,100%"
          fill="none"
          stroke="url(#y-arc-left)"
          strokeWidth="1.5"
        />
      </svg>

      {/* Center Copilot Core Capsule Island (Visual Anchor) */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-20 w-[90%] max-w-md">
        <div className="p-3.5 md:p-4 rounded-3xl bg-white/95 backdrop-blur-2xl border border-slate-200/90 shadow-md shadow-indigo-500/5 flex flex-col items-center text-center space-y-2 transition-all hover:border-indigo-300">
          <div>
            <div className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-blue-50 text-blue-700 text-[10px] font-bold">
              <Mic2 size={10} />
              <span>全流程智能面试中枢</span>
            </div>
            <h1 className="text-sm md:text-base font-black text-slate-900 tracking-tight mt-0.5">
              面试备战 · 对练 · 复盘
            </h1>
          </div>

          {/* Conversation Input */}
          <form onSubmit={handleStartPrep} className="w-full relative flex items-center">
            <div className="absolute left-3 text-indigo-600">
              <Sparkles size={14} />
            </div>

            <input
              type="text"
              value={prepPrompt}
              onChange={(e) => setPrepPrompt(e.target.value)}
              placeholder="输入目标公司或考点…"
              className="w-full pl-8 pr-16 py-1.5 rounded-full bg-slate-50 hover:bg-slate-100/80 focus:bg-white text-xs text-slate-800 placeholder-slate-400 border border-slate-200 focus:border-indigo-500 outline-none transition-all"
            />

            <button
              type="submit"
              className="absolute right-1 px-3 py-1 rounded-full bg-indigo-600 hover:bg-indigo-700 active:scale-95 text-white text-[11px] font-bold transition-all shadow-xs flex items-center gap-1 cursor-pointer"
            >
              <span>生成</span>
              <CornerDownLeft size={10} />
            </button>
          </form>
        </div>
      </div>

      {/* 3 Immersive De-Cardified Partitions (Directly on Canvas) */}
      <div className="relative z-10 w-full h-full flex flex-col justify-between">
        {/* Top Half: 面试准备与考点速查 (Interview Prep) */}
        <div
          onClick={() => navigate('/general-chat?prompt=帮我做针对性面试备战与高频考点预测')}
          className="h-[44%] w-full flex flex-col justify-between pb-12 cursor-pointer group"
        >
          <div className="flex items-center justify-between pb-1.5 border-b border-slate-200/50">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-lg bg-blue-100/70 text-blue-700 flex items-center justify-center font-bold">
                <BookOpen size={13} />
              </div>
              <span className="text-xs font-bold text-slate-900">面试准备与考点速查</span>
            </div>
            <span className="text-[10px] text-blue-600 font-semibold flex items-center gap-0.5 group-hover:translate-x-1 transition-transform">
              <span>进入备战空间</span>
              <ArrowRight size={11} />
            </span>
          </div>

          <div className="flex-1 flex items-center justify-between gap-8 py-2">
            <p className="text-xs text-slate-600 leading-relaxed max-w-md">
              智能解析目标岗位 JD、深挖业务背景、提炼核心追问考点与 STAR 结构化应答指南。
            </p>
            <div className="flex items-center gap-2 text-[10px] text-slate-400 font-mono">
              <span className="px-2 py-1 rounded-full bg-slate-100/80">JD 考点拆解</span>
              <span className="px-2 py-1 rounded-full bg-slate-100/80">STAR 应答应答</span>
            </div>
          </div>
        </div>

        {/* Bottom Half: Left (面试复盘) and Right (模拟面试) */}
        <div className="h-[44%] w-full grid grid-cols-2 gap-12 pt-12">
          {/* Bottom-Left: 真实面试深度复盘 (Interview Review) */}
          <div
            onClick={() => setSearchParams({ tab: 'review' })}
            className="h-full flex flex-col justify-between pr-8 cursor-pointer group select-none"
          >
            <div className="flex items-center justify-between pb-1.5 border-b border-slate-200/50">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-lg bg-emerald-100/70 text-emerald-700 flex items-center justify-center font-bold">
                  <FileBarChart2 size={13} />
                </div>
                <span className="text-xs font-bold text-slate-900">真实面试深度复盘</span>
              </div>
              <span className="text-[10px] text-emerald-700 font-semibold flex items-center gap-0.5 group-hover:translate-x-1 transition-transform">
                <span>进入复盘</span>
                <ArrowRight size={11} />
              </span>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              一键导入实战录音，WhisperX 极速逐字转写，AI 多维诊断、答题结构优化与证据链沉淀。
            </p>

            <div className="pt-1 flex items-center justify-between text-[9px] text-slate-400">
              <span>实战录音导入诊断</span>
              <span className="text-emerald-700 font-mono">WhisperX 驱动</span>
            </div>
          </div>

          {/* Bottom-Right: 模拟面试实战对练 (Mock Interview) */}
          <div
            onClick={() => setSearchParams({ tab: 'mock' })}
            className="h-full flex flex-col justify-between pl-8 cursor-pointer group select-none"
          >
            <div className="flex items-center justify-between pb-1.5 border-b border-slate-200/50">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-lg bg-purple-100/70 text-purple-700 flex items-center justify-center font-bold">
                  <Mic2 size={13} />
                </div>
                <span className="text-xs font-bold text-slate-900">模拟面试实战对练</span>
              </div>
              <span className="text-[10px] text-purple-700 font-semibold flex items-center gap-0.5 group-hover:translate-x-1 transition-transform">
                <span>进入模拟</span>
                <ArrowRight size={11} />
              </span>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              沉浸式多轮语音/文本对练，AI 面试官实时深度追问与应变考核，即时出具雷达评分与改进诊断。
            </p>

            <div className="pt-1 flex items-center justify-between text-[9px] text-slate-400">
              <span>实时语音多轮追问</span>
              <span className="text-purple-700 font-mono">智能考官</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
