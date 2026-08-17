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
    <div className="relative w-full h-full overflow-hidden select-none font-sans bg-[#FAFBFD]">
      
      {/* ═══ 1. Continuous Multi-Color Aurora Mesh Flow ═══ */}
      <div className="absolute inset-0 z-0 pointer-events-none overflow-hidden">
        {/* Top: Sky Blue & Indigo Flow */}
        <div className="absolute -top-[15%] left-1/2 -translate-x-1/2 w-[75%] h-[60%] rounded-full bg-gradient-to-b from-blue-200/50 via-indigo-200/35 to-transparent blur-[120px]" />
        {/* Bottom-Left: Emerald & Mint Flow */}
        <div className="absolute -bottom-[15%] -left-[15%] w-[65%] h-[65%] rounded-full bg-gradient-to-tr from-emerald-200/50 via-teal-200/35 to-transparent blur-[120px]" />
        {/* Bottom-Right: Violet & Rose Flow */}
        <div className="absolute -bottom-[15%] -right-[15%] w-[65%] h-[65%] rounded-full bg-gradient-to-tl from-purple-200/50 via-pink-200/35 to-transparent blur-[120px]" />
        {/* Center Radiant Convergence */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[55%] h-[55%] rounded-full bg-white/70 blur-[90px]" />
      </div>

      {/* ═══ 2. Full-Span Apple Liquid Glass 3-Pointed Star (Vertices touch boundaries) ═══ */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none z-10"
        viewBox="0 0 1000 700"
        preserveAspectRatio="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          {/* Liquid Glass Translucent Gradient */}
          <linearGradient id="hubGlassSurface" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.65" />
            <stop offset="35%" stopColor="#F8FAFC" stopOpacity="0.45" />
            <stop offset="65%" stopColor="#F1F5F9" stopOpacity="0.38" />
            <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0.6" />
          </linearGradient>

          {/* Specular Refraction Rim Highlight */}
          <linearGradient id="hubGlassRimStroke" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="rgba(255, 255, 255, 0.95)" />
            <stop offset="30%" stopColor="rgba(226, 232, 240, 0.6)" />
            <stop offset="70%" stopColor="rgba(203, 213, 225, 0.5)" />
            <stop offset="100%" stopColor="rgba(255, 255, 255, 0.95)" />
          </linearGradient>

          {/* Liquid Glass Drop Shadow Filter */}
          <filter id="hubGlassShadow" x="-10%" y="-10%" width="120%" height="120%">
            <feDropShadow dx="0" dy="16" stdDeviation="30" floodColor="#0F172A" floodOpacity="0.04" />
            <feDropShadow dx="0" dy="4" stdDeviation="10" floodColor="#0F172A" floodOpacity="0.03" />
          </filter>
        </defs>

        {/* ── Main Liquid Glass 3-Pointed Star Body ── */}
        {/* Vertices touch: (500,0), (1000,700), (0,700) */}
        <path
          d="M 500 0 C 500 240, 760 400, 1000 700 C 720 540, 280 540, 0 700 C 240 400, 500 240, 500 0 Z"
          fill="url(#hubGlassSurface)"
          stroke="url(#hubGlassRimStroke)"
          strokeWidth="1.5"
          filter="url(#hubGlassShadow)"
        />

        {/* Specular Inner Glints along the Concave Wings */}
        <path
          d="M 500 0 C 500 240, 240 400, 0 700"
          fill="none"
          stroke="rgba(255, 255, 255, 0.85)"
          strokeWidth="2.5"
          strokeLinecap="round"
          opacity="0.9"
        />
        <path
          d="M 500 0 C 500 240, 760 400, 1000 700"
          fill="none"
          stroke="rgba(255, 255, 255, 0.75)"
          strokeWidth="2"
          strokeLinecap="round"
          opacity="0.8"
        />
      </svg>

      {/* ═══ 3. Central Copilot Controls (Inside the Liquid Glass Center) ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center pointer-events-auto">
        <div className="flex flex-col items-center mb-6">
          <h2 className="text-2xl font-black text-slate-800 tracking-tight drop-shadow-sm flex items-center gap-2">
            智能面试中枢
          </h2>
          <p className="text-xs font-semibold text-slate-500 mt-1">
            备战 · 对练 · 复盘全流程护航
          </p>
        </div>

        {/* Integrated Frosted Glass Capsule Searchbox */}
        <form 
          onSubmit={handleStartPrep} 
          className="w-[430px] bg-white/80 backdrop-blur-2xl border border-white/90 shadow-[0_12px_36px_rgba(15,23,42,0.06)] rounded-full px-5 py-3 flex items-center gap-3 transition-all hover:bg-white/95 hover:shadow-[0_16px_44px_rgba(15,23,42,0.09)]"
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

      {/* ═══ 4. Three Distinct Sectors (Outside the Liquid Glass Wings) ═══ */}
      <div className="relative z-20 w-full h-full flex flex-col pointer-events-none">
        
        {/* ─── Top: 面试准备与考点速查 ─── */}
        <div className="flex-1 flex items-center justify-center pt-8 px-10 pb-28">
          <div
            onClick={() => navigate('/general-chat?prompt=帮我做针对性面试备战与高频考点预测')}
            className="w-full max-w-lg flex flex-col items-center text-center cursor-pointer group pointer-events-auto"
          >
            <div className="bg-white/70 hover:bg-white/90 backdrop-blur-md p-3 rounded-2xl shadow-[0_4px_16px_rgba(15,23,42,0.03)] border border-white/80 mb-3 group-hover:scale-105 transition-all">
              <BookOpen size={22} className="text-blue-600" />
            </div>
            <h3 className="text-base font-bold text-slate-900 group-hover:text-blue-700 transition-colors mb-1.5">
              面试准备与考点速查
            </h3>
            <p className="text-xs text-slate-600 leading-relaxed mb-3 max-w-md">
              智能解析目标岗位 JD、深挖业务背景、提炼核心追问考点与 STAR 结构化应答指南。
            </p>
            <div className="flex items-center justify-center gap-2 text-[11px] font-bold text-slate-500">
              <span className="px-3 py-1 rounded-full bg-white/70 backdrop-blur-sm border border-white/80 shadow-sm">JD 考点拆解</span>
              <span className="px-3 py-1 rounded-full bg-white/70 backdrop-blur-sm border border-white/80 shadow-sm">STAR 训练</span>
              <span className="px-3 py-1 rounded-full bg-white/70 backdrop-blur-sm border border-white/80 shadow-sm">业务深挖模拟</span>
            </div>
          </div>
        </div>

        {/* ─── Bottom Half ─── */}
        <div className="flex-1 flex">
          
          {/* Bottom-Left: 真实面试深度复盘 */}
          <div className="flex-1 flex items-center justify-center pl-12 pt-20 pb-10 pr-28">
            <div
              onClick={() => setSearchParams({ tab: 'review' })}
              className="w-full max-w-[310px] flex flex-col items-start cursor-pointer group bg-white/60 hover:bg-white/90 backdrop-blur-md p-5 rounded-2xl shadow-[0_4px_16px_rgba(15,23,42,0.03)] border border-white/70 hover:shadow-md transition-all pointer-events-auto"
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
              className="w-full max-w-[310px] flex flex-col items-start cursor-pointer group bg-white/60 hover:bg-white/90 backdrop-blur-md p-5 rounded-2xl shadow-[0_4px_16px_rgba(15,23,42,0.03)] border border-white/70 hover:shadow-md transition-all pointer-events-auto"
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
