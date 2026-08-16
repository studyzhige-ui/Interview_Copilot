import { useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Mic2,
  FileBarChart2,
  BookOpen,
  Send,
  ArrowUpRight,
  ChevronLeft,
  Sparkles,
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

  if (tab === 'mock') {
    return (
      <div className="h-full flex flex-col overflow-hidden bg-white">
        <div className="px-5 py-2.5 bg-white border-b border-slate-200/80 flex items-center shrink-0">
          <button type="button" onClick={() => setSearchParams({ tab: 'hub' })} className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-blue-600 cursor-pointer transition-colors">
            <ChevronLeft size={14} /><span>返回面试中枢</span>
          </button>
          <span className="text-slate-300 mx-2">/</span>
          <span className="text-xs font-bold text-slate-900">模拟面试实战对练</span>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto"><MockPage /></div>
      </div>
    );
  }

  if (tab === 'review') {
    return (
      <div className="h-full flex flex-col overflow-hidden bg-white">
        <div className="px-5 py-2.5 bg-white border-b border-slate-200/80 flex items-center shrink-0">
          <button type="button" onClick={() => setSearchParams({ tab: 'hub' })} className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-blue-600 cursor-pointer transition-colors">
            <ChevronLeft size={14} /><span>返回面试中枢</span>
          </button>
          <span className="text-slate-300 mx-2">/</span>
          <span className="text-xs font-bold text-slate-900">真实面试录音深度复盘</span>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto"><ReviewPage /></div>
      </div>
    );
  }

  return (
    <div className="relative w-full h-full overflow-hidden select-none font-sans bg-[#F9FAFD]">
      
      {/* ═══ 1. Ambient Background Glows ═══ */}
      <div className="absolute inset-0 z-0 pointer-events-none">
        <div className="absolute -top-[10%] left-1/2 -translate-x-1/2 w-[70%] h-[50%] rounded-full bg-blue-100/60 blur-[140px]" />
        <div className="absolute -bottom-[10%] -left-[10%] w-[55%] h-[55%] rounded-full bg-emerald-100/50 blur-[140px]" />
        <div className="absolute -bottom-[10%] -right-[10%] w-[55%] h-[55%] rounded-full bg-purple-100/50 blur-[140px]" />
      </div>

      {/* ═══ 2. Three-Pointed Sparkle Core (SVG) ═══ */}
      {/* Outer Glow */}
      <svg
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[520px] h-[520px] pointer-events-none z-0 opacity-40 blur-3xl"
        viewBox="0 0 500 500"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M 250 30 C 250 180 340 280 450 420 C 340 370 160 370 50 420 C 160 280 250 180 250 30 Z"
          fill="url(#hubGlowGradient)"
        />
        <defs>
          <radialGradient id="hubGlowGradient" cx="50%" cy="55%" r="50%">
            <stop offset="0%" stopColor="#818CF8" />
            <stop offset="50%" stopColor="#34D399" />
            <stop offset="100%" stopColor="#3B82F6" />
          </radialGradient>
        </defs>
      </svg>

      {/* Sharp Three-pointed Sparkle */}
      <svg
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[420px] h-[420px] pointer-events-none z-10 drop-shadow-[0_12px_48px_rgba(99,102,241,0.22)]"
        viewBox="0 0 500 500"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <filter id="hubInternalBlur">
            <feGaussianBlur stdDeviation="35" />
          </filter>
          <clipPath id="triSparkleClip">
            <path d="M 250 30 C 250 180 340 280 450 420 C 340 370 160 370 50 420 C 160 280 250 180 250 30 Z" />
          </clipPath>
        </defs>

        <g clipPath="url(#triSparkleClip)">
          {/* Base Indigo */}
          <rect width="500" height="500" fill="#4F46E5" />
          {/* Top: Bright Blue */}
          <circle cx="250" cy="70" r="180" fill="#38BDF8" filter="url(#hubInternalBlur)" />
          {/* Bottom-Left: Emerald */}
          <circle cx="100" cy="400" r="170" fill="#10B981" filter="url(#hubInternalBlur)" />
          {/* Bottom-Right: Violet & Rose */}
          <circle cx="400" cy="400" r="170" fill="#A855F7" filter="url(#hubInternalBlur)" />
          {/* Center Luminous Core */}
          <circle cx="250" cy="270" r="120" fill="#C7D2FE" opacity="0.9" filter="url(#hubInternalBlur)" />
          <circle cx="250" cy="270" r="60" fill="#FFFFFF" opacity="0.5" filter="url(#hubInternalBlur)" />
        </g>
      </svg>

      {/* ═══ 3. Central Copilot Controls ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center pointer-events-auto">
        <div className="flex flex-col items-center mb-6">
          <h2 className="text-2xl font-black text-slate-800 tracking-tight drop-shadow-sm flex items-center gap-2">
            智能面试中枢
          </h2>
          <p className="text-xs font-semibold text-slate-600 mt-1 drop-shadow-sm">
            备战 · 对练 · 复盘全流程护航
          </p>
        </div>

        {/* Integrated Frosted Glass Capsule */}
        <form 
          onSubmit={handleStartPrep} 
          className="w-[430px] bg-white/85 backdrop-blur-xl border border-white/80 shadow-[0_12px_40px_rgba(0,0,0,0.08)] rounded-full px-5 py-3 flex items-center gap-3 transition-all hover:bg-white hover:shadow-[0_16px_48px_rgba(0,0,0,0.12)]"
        >
          <Sparkles className="w-4 h-4 text-indigo-500 shrink-0" />
          <input
            type="text"
            value={prepPrompt}
            onChange={(e) => setPrepPrompt(e.target.value)}
            placeholder="输入目标公司或考点开启特训…"
            className="flex-1 bg-transparent text-xs outline-none text-slate-800 placeholder-slate-400 font-medium"
          />
          <button
            type="submit"
            className="w-7 h-7 flex items-center justify-center bg-indigo-600 hover:bg-indigo-700 text-white rounded-full transition-transform hover:scale-105 cursor-pointer shrink-0 shadow-sm"
          >
            <Send className="w-3.5 h-3.5 -ml-0.5" />
          </button>
        </form>
      </div>

      {/* ═══ 4. Three Borderless Immersive Sectors ═══ */}
      <div className="relative z-20 w-full h-full flex flex-col pointer-events-none">
        
        {/* ─── Top: 面试准备与考点速查 ─── */}
        <div className="flex-1 flex items-center justify-center pt-8 px-10 pb-28">
          <div
            onClick={() => navigate('/general-chat?prompt=帮我做针对性面试备战与高频考点预测')}
            className="w-full max-w-lg flex flex-col items-center text-center cursor-pointer group pointer-events-auto"
          >
            <div className="bg-white/80 backdrop-blur-md p-3 rounded-2xl shadow-sm mb-3 group-hover:scale-105 transition-transform">
              <BookOpen size={22} className="text-blue-600" />
            </div>
            <h3 className="text-base font-bold text-slate-900 group-hover:text-blue-700 transition-colors mb-1.5">
              面试准备与考点速查
            </h3>
            <p className="text-xs text-slate-600 leading-relaxed mb-3 max-w-md">
              智能解析目标岗位 JD、深挖业务背景、提炼核心追问考点与 STAR 结构化应答指南。
            </p>
            <div className="flex items-center justify-center gap-2 text-[11px] font-bold text-slate-500">
              <span className="px-3 py-1 rounded-full bg-white/80 backdrop-blur-sm shadow-sm">JD 考点拆解</span>
              <span className="px-3 py-1 rounded-full bg-white/80 backdrop-blur-sm shadow-sm">STAR 训练</span>
              <span className="px-3 py-1 rounded-full bg-white/80 backdrop-blur-sm shadow-sm">业务深挖模拟</span>
            </div>
          </div>
        </div>

        {/* ─── Bottom Half ─── */}
        <div className="flex-1 flex">
          
          {/* Bottom-Left: 真实面试深度复盘 */}
          <div className="flex-1 flex items-center justify-center pl-12 pt-20 pb-10 pr-28">
            <div
              onClick={() => setSearchParams({ tab: 'review' })}
              className="w-full max-w-[310px] flex flex-col items-start cursor-pointer group bg-white/70 hover:bg-white/95 backdrop-blur-md p-5 rounded-2xl shadow-sm hover:shadow-md transition-all pointer-events-auto"
            >
              <div className="flex items-center gap-3 mb-2.5">
                <div className="p-2 rounded-xl bg-emerald-100/60 text-emerald-600 group-hover:bg-emerald-100 transition-colors">
                  <FileBarChart2 size={18} />
                </div>
                <h3 className="text-sm font-bold text-slate-900 group-hover:text-emerald-700 transition-colors">
                  真实面试深度复盘
                </h3>
              </div>
              <p className="text-[11px] text-slate-600 leading-relaxed mb-3">
                一键导入实战录音，WhisperX 极速逐字转写，AI 多维诊断、答题结构优化与证据链沉淀。
              </p>
              <span className="text-[11px] text-emerald-700 font-bold flex items-center gap-1 group-hover:translate-x-1 transition-transform">
                进入复盘 <ArrowUpRight className="w-3 h-3" />
              </span>
            </div>
          </div>

          {/* Bottom-Right: 模拟面试实战对练 */}
          <div className="flex-1 flex items-center justify-center pr-12 pt-20 pb-10 pl-28">
            <div
              onClick={() => setSearchParams({ tab: 'mock' })}
              className="w-full max-w-[310px] flex flex-col items-start cursor-pointer group bg-white/70 hover:bg-white/95 backdrop-blur-md p-5 rounded-2xl shadow-sm hover:shadow-md transition-all pointer-events-auto"
            >
              <div className="flex items-center gap-3 mb-2.5">
                <div className="p-2 rounded-xl bg-purple-100/60 text-purple-600 group-hover:bg-purple-100 transition-colors">
                  <Mic2 size={18} />
                </div>
                <h3 className="text-sm font-bold text-slate-900 group-hover:text-purple-700 transition-colors">
                  模拟面试实战对练
                </h3>
              </div>
              <p className="text-[11px] text-slate-600 leading-relaxed mb-3">
                沉浸式多轮语音或文本对练，AI 考官实时深度追问考核，即时出具雷达评分与诊断。
              </p>
              <span className="text-[11px] text-purple-700 font-bold flex items-center gap-1 group-hover:translate-x-1 transition-transform">
                进入模拟 <ArrowUpRight className="w-3 h-3" />
              </span>
            </div>
          </div>

        </div>

      </div>
    </div>
  );
}
