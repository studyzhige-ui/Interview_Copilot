import { useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Mic2,
  FileBarChart2,
  BookOpen,
  Sparkles,
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

  // Sub-workspace: Mock Interview
  if (tab === 'mock') {
    return (
      <div className="h-full flex flex-col overflow-hidden bg-white">
        <div className="px-5 py-2.5 bg-white border-b border-slate-200/80 flex items-center shrink-0">
          <button
            type="button"
            onClick={() => setSearchParams({ tab: 'hub' })}
            className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-blue-600 cursor-pointer transition-colors"
          >
            <ChevronLeft size={14} />
            <span>返回面试中枢</span>
          </button>
          <span className="text-slate-300 mx-2">/</span>
          <span className="text-xs font-bold text-slate-900">模拟面试实战对练</span>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto">
          <MockPage />
        </div>
      </div>
    );
  }

  // Sub-workspace: Interview Review
  if (tab === 'review') {
    return (
      <div className="h-full flex flex-col overflow-hidden bg-white">
        <div className="px-5 py-2.5 bg-white border-b border-slate-200/80 flex items-center shrink-0">
          <button
            type="button"
            onClick={() => setSearchParams({ tab: 'hub' })}
            className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-blue-600 cursor-pointer transition-colors"
          >
            <ChevronLeft size={14} />
            <span>返回面试中枢</span>
          </button>
          <span className="text-slate-300 mx-2">/</span>
          <span className="text-xs font-bold text-slate-900">真实面试录音深度复盘</span>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto">
          <ReviewPage />
        </div>
      </div>
    );
  }

  // Hub: Three-direction radiating canvas
  return (
    <div className="relative w-full h-full bg-[#F8FAFC] overflow-hidden flex flex-col font-sans select-none">
      <main className="relative flex-1 w-full h-full">
        {/* Background: Y-shaped organic fluid seams (SVG) */}
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none z-0"
          viewBox="0 0 1000 700"
          preserveAspectRatio="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          {/* Y-stem: top center to hub */}
          <path d="M 500 0 C 500 200 500 280 500 320" stroke="#E2E8F0" strokeWidth="1.5" fill="none" strokeOpacity="0.8" />
          {/* Y-branch left: hub to bottom-left */}
          <path d="M 500 380 C 450 420 300 500 0 700" stroke="#E2E8F0" strokeWidth="1.5" fill="none" strokeOpacity="0.8" />
          {/* Y-branch right: hub to bottom-right */}
          <path d="M 500 380 C 550 420 700 500 1000 700" stroke="#E2E8F0" strokeWidth="1.5" fill="none" strokeOpacity="0.8" />

          {/* Center ambient glow */}
          <defs>
            <radialGradient id="y-center-glow" cx="50%" cy="50%" r="22%">
              <stop offset="0%" stopColor="#EDE9FE" stopOpacity="0.5" />
              <stop offset="100%" stopColor="#F8FAFC" stopOpacity="0" />
            </radialGradient>
          </defs>
          <circle cx="500" cy="350" r="160" fill="url(#y-center-glow)" />
        </svg>

        {/* Three immersive partitions — directly on canvas, no card boxes */}
        <div className="relative w-full h-full flex flex-col p-8 lg:p-10 z-10">

          {/* ─── Top Partition: 面试准备与考点速查 ─── */}
          <div className="flex-[4] flex flex-col pb-24 max-w-2xl">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-base">
                <BookOpen size={16} className="text-blue-600" />
                面试准备与考点速查
              </div>
              <button
                type="button"
                onClick={() => navigate('/general-chat?prompt=帮我做针对性面试备战与高频考点预测')}
                className="text-[11px] text-blue-600 hover:text-blue-800 cursor-pointer flex items-center gap-0.5 font-semibold transition-colors"
              >
                进入备战空间 <ArrowUpRight className="w-3 h-3" />
              </button>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed mb-3 max-w-md">
              智能解析目标岗位 JD、深挖业务背景、提炼核心追问考点与 STAR 结构化应答指南。
            </p>

            <div className="flex items-center gap-2 text-[10px] text-slate-400">
              <span className="px-2 py-1 rounded-full bg-slate-100/80 font-medium">JD 考点拆解</span>
              <span className="px-2 py-1 rounded-full bg-slate-100/80 font-medium">STAR 应答训练</span>
              <span className="px-2 py-1 rounded-full bg-slate-100/80 font-medium">业务深挖模拟</span>
            </div>
          </div>

          {/* ─── Bottom Row: two partitions side by side ─── */}
          <div className="flex-[5] grid grid-cols-2 gap-16 pt-20">

            {/* Bottom-Left: 真实面试深度复盘 */}
            <div
              onClick={() => setSearchParams({ tab: 'review' })}
              className="flex flex-col justify-between pr-12 cursor-pointer group"
            >
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2 text-slate-900 font-bold text-sm">
                    <FileBarChart2 size={15} className="text-emerald-600" />
                    真实面试深度复盘
                  </div>
                  <span className="text-[11px] text-emerald-700 font-semibold flex items-center gap-0.5 group-hover:translate-x-0.5 transition-transform">
                    进入复盘 <ArrowUpRight className="w-3 h-3" />
                  </span>
                </div>

                <p className="text-xs text-slate-600 leading-relaxed">
                  一键导入实战录音，WhisperX 极速逐字转写，AI 多维诊断、答题结构优化与证据链沉淀。
                </p>
              </div>

              <div className="flex items-center justify-between text-[10px] text-slate-400 pt-3 border-t border-slate-100/60">
                <span>实战录音导入诊断</span>
                <span className="text-emerald-700 font-mono font-medium">WhisperX 驱动</span>
              </div>
            </div>

            {/* Bottom-Right: 模拟面试实战对练 */}
            <div
              onClick={() => setSearchParams({ tab: 'mock' })}
              className="flex flex-col justify-between pl-12 cursor-pointer group"
            >
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2 text-slate-900 font-bold text-sm">
                    <Mic2 size={15} className="text-purple-600" />
                    模拟面试实战对练
                  </div>
                  <span className="text-[11px] text-purple-700 font-semibold flex items-center gap-0.5 group-hover:translate-x-0.5 transition-transform">
                    进入模拟 <ArrowUpRight className="w-3 h-3" />
                  </span>
                </div>

                <p className="text-xs text-slate-600 leading-relaxed">
                  沉浸式多轮语音/文本对练，AI 面试官实时深度追问与应变考核，即时出具雷达评分与改进诊断。
                </p>
              </div>

              <div className="flex items-center justify-between text-[10px] text-slate-400 pt-3 border-t border-slate-100/60">
                <span>实时语音多轮追问</span>
                <span className="text-purple-700 font-mono font-medium">智能考官</span>
              </div>
            </div>
          </div>
        </div>

        {/* ─── Center Copilot Capsule Island (Y-junction anchor) ─── */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center">
          <div className="w-[340px] bg-white/95 backdrop-blur-xl border border-indigo-200/60 shadow-xl shadow-indigo-500/10 rounded-2xl p-4 flex flex-col items-center gap-3 ring-4 ring-indigo-50/40">
            <div className="text-center">
              <div className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700 text-[10px] font-bold mb-1">
                <Mic2 size={10} />
                全流程智能面试中枢
              </div>
              <h2 className="text-sm font-bold text-slate-800">面试备战 · 对练 · 复盘</h2>
            </div>
            <form onSubmit={handleStartPrep} className="w-full flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-xl px-3 py-2">
              <Sparkles className="w-4 h-4 text-indigo-500 shrink-0" />
              <input
                type="text"
                value={prepPrompt}
                onChange={(e) => setPrepPrompt(e.target.value)}
                placeholder="输入目标公司或考点…"
                className="flex-1 bg-transparent text-xs outline-none text-slate-700 placeholder-slate-400"
              />
              <button
                type="submit"
                className="p-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors cursor-pointer"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </form>
          </div>
        </div>
      </main>
    </div>
  );
}
