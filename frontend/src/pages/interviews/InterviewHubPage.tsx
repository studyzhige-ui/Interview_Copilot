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
  Play,
  UploadCloud,
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
        {/* Top-Left: Sky Blue & Cyan (面试准备) */}
        <div className="absolute -top-[20%] -left-[20%] w-[70%] h-[70%] rounded-full bg-gradient-to-br from-sky-200/55 via-blue-200/40 to-transparent blur-[130px]" />
        {/* Top-Right: Violet & Purple (模拟对练) */}
        <div className="absolute -top-[20%] -right-[20%] w-[70%] h-[70%] rounded-full bg-gradient-to-bl from-purple-200/55 via-indigo-200/40 to-transparent blur-[130px]" />
        {/* Bottom-Center: Emerald & Mint (真实复盘) */}
        <div className="absolute -bottom-[20%] left-1/2 -translate-x-1/2 w-[80%] h-[70%] rounded-full bg-gradient-to-t from-emerald-200/55 via-teal-200/40 to-transparent blur-[130px]" />
        {/* Center Luminous Convergence */}
        <div className="absolute top-[48%] left-1/2 -translate-x-1/2 -translate-y-1/2 w-[50%] h-[50%] rounded-full bg-white/80 blur-[80px]" />
      </div>

      {/* ═══ 2. Full-Span Apple Liquid Glass 3-Pointed Star (Snug waist wrapping center) ═══ */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none z-10"
        viewBox="0 0 1000 700"
        preserveAspectRatio="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          {/* Multi-Stop Liquid Glass Translucent Refraction Gradient */}
          <linearGradient id="hubGlassSurface" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.75" />
            <stop offset="30%" stopColor="#F8FAFC" stopOpacity="0.5" />
            <stop offset="60%" stopColor="#FFFFFF" stopOpacity="0.65" />
            <stop offset="85%" stopColor="#F1F5F9" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0.75" />
          </linearGradient>

          {/* High-Gloss Specular Rim Highlight */}
          <linearGradient id="hubGlassRimStroke" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="rgba(255, 255, 255, 1)" />
            <stop offset="30%" stopColor="rgba(226, 232, 240, 0.7)" />
            <stop offset="70%" stopColor="rgba(203, 213, 225, 0.6)" />
            <stop offset="100%" stopColor="rgba(255, 255, 255, 1)" />
          </linearGradient>

          {/* Tactile Drop Shadow Filter */}
          <filter id="hubGlassShadow" x="-10%" y="-10%" width="120%" height="120%">
            <feDropShadow dx="0" dy="20" stdDeviation="35" floodColor="#0F172A" floodOpacity="0.06" />
            <feDropShadow dx="0" dy="6" stdDeviation="12" floodColor="#0F172A" floodOpacity="0.04" />
          </filter>
        </defs>

        {/* ── Main Liquid Glass 3-Pointed Star (Bottom vertices in exact corners 0,700 and 1000,700) ── */}
        <path
          d="M 500 0 C 500 200, 640 280, 1000 700 C 700 450, 300 450, 0 700 C 360 280, 500 200, 500 0 Z"
          fill="url(#hubGlassSurface)"
          stroke="url(#hubGlassRimStroke)"
          strokeWidth="2"
          filter="url(#hubGlassShadow)"
        />

        {/* Primary Specular Light Refraction Bevels */}
        <path
          d="M 500 0 C 500 200, 360 280, 0 700"
          fill="none"
          stroke="rgba(255, 255, 255, 0.95)"
          strokeWidth="3"
          strokeLinecap="round"
          opacity="0.95"
        />
        <path
          d="M 500 0 C 500 200, 640 280, 1000 700"
          fill="none"
          stroke="rgba(255, 255, 255, 0.85)"
          strokeWidth="2.5"
          strokeLinecap="round"
          opacity="0.85"
        />
        <path
          d="M 0 700 C 300 450, 700 450, 1000 700"
          fill="none"
          stroke="rgba(255, 255, 255, 0.75)"
          strokeWidth="2"
          strokeLinecap="round"
          opacity="0.8"
        />
      </svg>

      {/* ═══ 3. Central Copilot Nexus (Snugly encased in the Liquid Glass Tri-Star) ═══ */}
      <div className="absolute top-[48%] left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center pointer-events-auto">
        <div className="flex flex-col items-center mb-4">
          <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight drop-shadow-sm flex items-center gap-2">
            智能面试中枢
          </h2>
          <p className="text-xs sm:text-sm font-medium text-slate-500 mt-1">
            备战 · 对练 · 复盘全流程护航
          </p>
        </div>

        {/* High-Gloss Frosted Glass Capsule Searchbox */}
        <form 
          onSubmit={handleStartPrep} 
          className="w-[440px] h-[52px] bg-white/85 backdrop-blur-2xl border border-white/90 shadow-[0_12px_36px_rgba(15,23,42,0.06),0_1px_2px_rgba(255,255,255,0.9)_inset] rounded-full px-5 flex items-center gap-3 transition-all hover:bg-white/95 hover:shadow-[0_16px_44px_rgba(15,23,42,0.09)]"
        >
          <Sparkles className="w-4 h-4 text-indigo-500 shrink-0" />
          <input
            type="text"
            value={prepPrompt}
            onChange={(e) => setPrepPrompt(e.target.value)}
            placeholder="输入目标公司或考点开启特训…"
            className="flex-1 bg-transparent text-sm font-normal outline-none text-slate-800 placeholder:text-slate-400"
          />
          <button
            type="submit"
            className="w-8 h-8 flex items-center justify-center bg-indigo-600 hover:bg-indigo-700 text-white rounded-full transition-transform hover:scale-105 cursor-pointer shrink-0 shadow-sm"
          >
            <Send className="w-3.5 h-3.5 -ml-0.5" />
          </button>
        </form>
      </div>

      {/* ═══ 4. Three Distinct Sectors (Top-Left, Top-Right, Bottom-Center - Centered in each Region) ═══ */}
      <div className="relative z-20 w-full h-full flex flex-col pointer-events-none">
        
        {/* ── Top Half: Left (面试准备) & Right (模拟实战) ── */}
        <div className="h-[62%] flex">
          
          {/* ─── Top-Left: 面试准备与考点速查 (Centered in Top-Left Region) ─── */}
          <div className="flex-1 flex flex-col justify-center items-center p-8 pl-12 pr-6">
            <div
              onClick={() => navigate('/general-chat?prompt=帮我做针对性面试备战与高频考点预测')}
              className="w-full max-w-[380px] flex flex-col items-start cursor-pointer group pointer-events-auto transition-all"
            >
              <div className="flex items-center gap-3.5 mb-3">
                <div className="w-11 h-11 rounded-2xl bg-blue-500/10 text-blue-600 flex items-center justify-center group-hover:scale-105 transition-transform shadow-xs">
                  <BookOpen size={22} />
                </div>
                <div>
                  <h3 className="text-xl font-extrabold text-slate-900 group-hover:text-blue-600 transition-colors tracking-tight">
                    面试准备与考点速查
                  </h3>
                  <p className="text-xs font-semibold text-blue-600/80">针对性 JD 剖析与策略预测</p>
                </div>
              </div>

              <p className="text-sm text-slate-600 leading-relaxed mb-4">
                深度拆解目标企业业务与技术栈，智能提取高频追问雷区，生成 STAR 结构化应答应考指南。
              </p>

              <div className="flex flex-wrap gap-2 mb-4">
                <span className="px-3.5 py-1.5 rounded-xl bg-white/80 backdrop-blur-md text-xs font-semibold text-slate-700 border border-white/90 shadow-xs">
                  JD 考点拆解
                </span>
                <span className="px-3.5 py-1.5 rounded-xl bg-white/80 backdrop-blur-md text-xs font-semibold text-slate-700 border border-white/90 shadow-xs">
                  STAR 应答强化
                </span>
                <span className="px-3.5 py-1.5 rounded-xl bg-white/80 backdrop-blur-md text-xs font-semibold text-slate-700 border border-white/90 shadow-xs">
                  业务深挖预测
                </span>
              </div>

              <span className="text-sm text-blue-600 font-bold flex items-center gap-1.5 group-hover:translate-x-1 transition-transform">
                开启考点备战 <ArrowUpRight className="w-4 h-4" />
              </span>
            </div>
          </div>

          {/* ─── Top-Right: 模拟面试实战对练 (Centered in Top-Right Region) ─── */}
          <div className="flex-1 flex flex-col justify-center items-center p-8 pr-12 pl-6">
            <div
              onClick={() => setSearchParams({ tab: 'mock' })}
              className="w-full max-w-[380px] flex flex-col items-end text-right cursor-pointer group pointer-events-auto transition-all"
            >
              <div className="flex items-center gap-3.5 mb-3 flex-row-reverse">
                <div className="w-11 h-11 rounded-2xl bg-purple-500/10 text-purple-600 flex items-center justify-center group-hover:scale-105 transition-transform shadow-xs">
                  <Mic2 size={22} />
                </div>
                <div>
                  <h3 className="text-xl font-extrabold text-slate-900 group-hover:text-purple-600 transition-colors tracking-tight">
                    模拟面试实战对练
                  </h3>
                  <p className="text-xs font-semibold text-purple-600/80">多轮深度交互与应变诊断</p>
                </div>
              </div>

              <p className="text-sm text-slate-600 leading-relaxed mb-4">
                沉浸式 AI 面试官全流程真实追问，支持多轮语音与文本对答，即时出具多维雷达评分与改进方案。
              </p>

              <div className="flex flex-wrap gap-2 mb-4 justify-end">
                <span className="px-3.5 py-1.5 rounded-xl bg-white/80 backdrop-blur-md text-xs font-semibold text-slate-700 border border-white/90 shadow-xs">
                  多轮语音交互
                </span>
                <span className="px-3.5 py-1.5 rounded-xl bg-white/80 backdrop-blur-md text-xs font-semibold text-slate-700 border border-white/90 shadow-xs">
                  压力追问考核
                </span>
                <span className="px-3.5 py-1.5 rounded-xl bg-white/80 backdrop-blur-md text-xs font-semibold text-slate-700 border border-white/90 shadow-xs">
                  雷达能力诊断
                </span>
              </div>

              <span className="text-sm text-purple-600 font-bold flex items-center gap-1.5 group-hover:-translate-x-1 transition-transform">
                <Play className="w-4 h-4 fill-current" /> 进入模拟实战
              </span>
            </div>
          </div>

        </div>

        {/* ── Bottom Half: Bottom-Center (Centered in the spacious Bottom Region below waist) ── */}
        <div className="h-[38%] flex justify-center items-center pb-8 px-12">
          <div
            onClick={() => setSearchParams({ tab: 'review' })}
            className="w-full max-w-2xl flex flex-col items-center text-center cursor-pointer group pointer-events-auto transition-all"
          >
            <div className="flex items-center gap-3.5 mb-2.5">
              <div className="w-10 h-10 rounded-2xl bg-emerald-500/10 text-emerald-600 flex items-center justify-center group-hover:scale-105 transition-transform shadow-xs">
                <FileBarChart2 size={20} />
              </div>
              <div>
                <h3 className="text-xl font-extrabold text-slate-900 group-hover:text-emerald-700 transition-colors tracking-tight">
                  真实面试录音深度复盘
                </h3>
              </div>
            </div>

            <p className="text-sm text-slate-600 leading-relaxed mb-4 max-w-xl">
              一键导入真实实战录音，WhisperX 极速逐字转写与智能切片，多维诊断答题缺陷并沉淀优质回答。
            </p>

            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2.5 text-xs font-semibold text-slate-700">
                <span className="px-3.5 py-1.5 rounded-xl bg-white/80 backdrop-blur-md border border-white/90 shadow-xs">逐字精准转写</span>
                <span className="px-3.5 py-1.5 rounded-xl bg-white/80 backdrop-blur-md border border-white/90 shadow-xs">证据链归档</span>
                <span className="px-3.5 py-1.5 rounded-xl bg-white/80 backdrop-blur-md border border-white/90 shadow-xs">答题重构优化</span>
              </div>
              <span className="text-sm text-emerald-700 font-bold flex items-center gap-1.5 group-hover:translate-x-1 transition-transform ml-2">
                <UploadCloud className="w-4 h-4" /> 导入实战录音复盘
              </span>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
