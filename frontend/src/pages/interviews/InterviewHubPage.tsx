import { useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Mic2,
  FileBarChart2,
  BookOpen,
  Send,
  ArrowUpRight,
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
    <div className="relative w-full h-full overflow-hidden select-none font-sans bg-white">
      {/* ═══ 1. Aurora Radial Glow Background ═══ */}
      <div className="absolute inset-0 z-0 opacity-80 pointer-events-none">
        {/* Center white convergence */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-white/90 blur-[120px] z-10" />
        {/* Top: 淡蓝光 (#E0F2FE) */}
        <div className="absolute -top-[10%] left-1/2 -translate-x-1/2 w-[70%] h-[50%] rounded-full bg-[#E0F2FE]/80 blur-[130px]" />
        {/* Bottom-left: 薄荷绿 (#DCFCE7) */}
        <div className="absolute -bottom-[10%] -left-[10%] w-[60%] h-[60%] rounded-full bg-[#DCFCE7]/80 blur-[130px]" />
        {/* Bottom-right: 丁香紫 (#F3E8FF) */}
        <div className="absolute -bottom-[10%] -right-[10%] w-[60%] h-[60%] rounded-full bg-[#F3E8FF]/80 blur-[130px]" />
      </div>

      {/* ═══ 2. Y-Split Flowing Seams (SVG) ═══ */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none z-0"
        viewBox="0 0 1000 700"
        preserveAspectRatio="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path d="M 500 0 C 500 150 500 250 500 350" stroke="rgba(226, 232, 240, 0.8)" strokeWidth="1.5" fill="none" />
        <path d="M 500 350 C 450 400 250 500 0 700" stroke="rgba(226, 232, 240, 0.8)" strokeWidth="1.5" fill="none" />
        <path d="M 500 350 C 550 400 750 500 1000 700" stroke="rgba(226, 232, 240, 0.8)" strokeWidth="1.5" fill="none" />
      </svg>

      {/* ═══ 3. Center Copilot Capsule (Ultra-thin, Max Height 110px) ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30">
        <div className="w-[380px] h-auto backdrop-blur-xl bg-white/70 border border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)] rounded-[2rem] p-3.5 flex flex-col items-center justify-center gap-2">
          <div className="w-full flex items-center justify-between px-2">
            <h2 className="text-sm font-bold text-slate-800 flex items-center gap-1.5">
              <Mic2 className="w-4 h-4 text-indigo-500" />
              智能面试中枢
            </h2>
            <p className="text-[10px] font-medium text-slate-500 bg-white/50 px-2 py-0.5 rounded-full border border-white/60">
              备战 · 对练 · 复盘
            </p>
          </div>
          <form onSubmit={handleStartPrep} className="w-full relative">
            <input
              type="text"
              value={prepPrompt}
              onChange={(e) => setPrepPrompt(e.target.value)}
              placeholder="输入目标公司或考点开启特训…"
              className="w-full h-10 bg-white/60 border border-slate-200/50 rounded-2xl pl-4 pr-12 text-xs outline-none text-slate-700 placeholder-slate-400 focus:bg-white/90 transition-colors shadow-inner shadow-slate-100/50"
            />
            <button
              type="submit"
              className="absolute right-1 top-1 bottom-1 w-8 flex items-center justify-center bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl transition-colors cursor-pointer"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>
      </div>

      {/* ═══ 4. Three Partitions (Strict padding to avoid capsule) ═══ */}
      <div className="relative z-10 w-full h-full flex flex-col">

        {/* Top: 面试准备与考点速查 (Full width, padded to top) */}
        <div className="flex-1 flex justify-center pt-10 px-8 pb-16">
          <div
            onClick={() => navigate('/general-chat?prompt=帮我做针对性面试备战与高频考点预测')}
            className="w-full max-w-2xl flex flex-col items-center text-center cursor-pointer group"
          >
            <div className="flex items-center gap-2 mb-2">
              <BookOpen size={20} className="text-blue-600" />
              <h3 className="text-lg font-bold text-slate-900 group-hover:text-blue-700 transition-colors">
                面试准备与考点速查
              </h3>
            </div>
            <p className="text-sm text-slate-600 leading-relaxed max-w-lg mb-4">
              智能解析目标岗位 JD、深挖业务背景、提炼核心追问考点与 STAR 结构化应答指南。
            </p>
            <div className="flex items-center gap-2 text-xs text-slate-500 font-medium">
              <span className="px-3 py-1 rounded-full bg-white/60 border border-white shadow-sm">JD 考点拆解</span>
              <span className="px-3 py-1 rounded-full bg-white/60 border border-white shadow-sm">STAR 应答训练</span>
              <span className="px-3 py-1 rounded-full bg-white/60 border border-white shadow-sm">业务深挖模拟</span>
            </div>
          </div>
        </div>

        {/* Bottom Half: 2 Columns */}
        <div className="flex-1 flex">
          {/* Bottom-Left: 真实面试深度复盘 */}
          <div className="flex-1 flex flex-col justify-end items-end pb-12 pr-16 pl-8 pt-16 border-r border-transparent">
            <div
              onClick={() => setSearchParams({ tab: 'review' })}
              className="w-full max-w-sm flex flex-col items-end text-right cursor-pointer group"
            >
              <div className="flex items-center gap-2 mb-2 flex-row-reverse">
                <FileBarChart2 size={18} className="text-emerald-600" />
                <h3 className="text-base font-bold text-slate-900 group-hover:text-emerald-700 transition-colors">
                  真实面试深度复盘
                </h3>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed mb-3">
                一键导入实战录音，WhisperX 极速逐字转写，AI 多维诊断、答题结构优化与证据链沉淀。
              </p>
              <span className="text-[11px] text-emerald-700 font-bold flex items-center gap-0.5 group-hover:-translate-x-1 transition-transform">
                进入复盘 <ArrowUpRight className="w-3 h-3" />
              </span>
            </div>
          </div>

          {/* Bottom-Right: 模拟面试实战对练 */}
          <div className="flex-1 flex flex-col justify-end items-start pb-12 pl-16 pr-8 pt-16">
            <div
              onClick={() => setSearchParams({ tab: 'mock' })}
              className="w-full max-w-sm flex flex-col items-start text-left cursor-pointer group"
            >
              <div className="flex items-center gap-2 mb-2">
                <Mic2 size={18} className="text-purple-600" />
                <h3 className="text-base font-bold text-slate-900 group-hover:text-purple-700 transition-colors">
                  模拟面试实战对练
                </h3>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed mb-3">
                沉浸式多轮语音/文本对练，AI 面试官实时深度追问与应变考核，即时出具雷达评分与改进诊断。
              </p>
              <span className="text-[11px] text-purple-700 font-bold flex items-center gap-0.5 group-hover:translate-x-1 transition-transform">
                进入模拟 <ArrowUpRight className="w-3 h-3" />
              </span>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
