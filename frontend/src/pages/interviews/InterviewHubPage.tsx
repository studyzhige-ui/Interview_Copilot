import { useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Sparkles,
  ArrowRight,
  Send,
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
    <div className="relative w-full h-full bg-[#F8FAFC] overflow-hidden flex flex-col font-sans select-none">
      {/* 主画布区域 */}
      <main className="relative flex-1 w-full h-full">
        {/* 背景 Y 字形流体曲面分割线 */}
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none z-0"
          xmlns="http://www.w3.org/2000/svg"
        >
          {/* Y字形贝塞尔平滑流体分割线 */}
          <path
            d="M 50% 0 C 50% 25% 50% 35% 50% 45%"
            stroke="#E2E8F0"
            strokeWidth="1.5"
            fill="none"
          />
          <path
            d="M 50% 55% C 50% 70% 30% 85% 15% 100%"
            stroke="#E2E8F0"
            strokeWidth="1.5"
            fill="none"
          />
          <path
            d="M 50% 55% C 50% 70% 70% 85% 85% 100%"
            stroke="#E2E8F0"
            strokeWidth="1.5"
            fill="none"
          />
        </svg>

        {/* 三向分区内容层 */}
        <div className="relative w-full h-full flex flex-col justify-between p-8 lg:p-10 z-10">
          {/* 上半区: 面试准备与考点速查 */}
          <div
            onClick={() => navigate('/general-chat?prompt=帮我做针对性面试备战与高频考点预测')}
            className="h-[42%] w-full flex flex-col justify-between pb-12 cursor-pointer group"
          >
            <div className="flex items-center justify-between pb-2 border-b border-slate-100/80">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                <span className="text-base font-bold text-slate-900">面试准备与考点速查</span>
              </div>
              <span className="text-xs text-blue-600 font-medium flex items-center gap-1 group-hover:translate-x-1 transition-transform">
                <span>进入备战空间</span>
                <ArrowRight size={12} />
              </span>
            </div>

            <div className="flex-1 flex items-center justify-between gap-8 py-2">
              <p className="text-xs text-slate-600 leading-relaxed max-w-lg">
                智能解析目标岗位 JD、深挖业务背景、提炼核心追问考点与 STAR 结构化应答指南。
              </p>
              <div className="flex items-center gap-2 text-[10px] text-slate-400 font-mono">
                <span className="px-2.5 py-1 rounded-full bg-white border border-slate-200/80 shadow-2xs">JD 考点拆解</span>
                <span className="px-2.5 py-1 rounded-full bg-white border border-slate-200/80 shadow-2xs">STAR 应答应答</span>
              </div>
            </div>
          </div>

          {/* 下半区: 左（面试复盘） + 右（模拟面试） */}
          <div className="h-[42%] w-full grid grid-cols-2 gap-16 pt-12 border-t border-slate-100/80">
            {/* 左侧: 真实面试深度复盘 */}
            <div
              onClick={() => setSearchParams({ tab: 'review' })}
              className="h-full flex flex-col justify-between pr-12 cursor-pointer group select-none"
            >
              <div className="flex items-center justify-between pb-2 border-b border-slate-100/80">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                  <span className="text-sm md:text-base font-bold text-slate-900">真实面试深度复盘</span>
                </div>
                <span className="text-xs text-emerald-600 font-medium flex items-center gap-1 group-hover:translate-x-1 transition-transform">
                  <span>进入复盘</span>
                  <ArrowRight size={12} />
                </span>
              </div>

              <p className="text-xs text-slate-600 leading-relaxed">
                一键导入实战录音，WhisperX 极速逐字转写，AI 多维诊断、答题结构优化与证据链沉淀。
              </p>

              <div className="pt-1 flex items-center justify-between text-[10px] text-slate-400">
                <span>实战录音逐字转写</span>
                <span className="text-emerald-700 font-mono">WhisperX 驱动</span>
              </div>
            </div>

            {/* 右侧: 模拟面试实战对练 */}
            <div
              onClick={() => setSearchParams({ tab: 'mock' })}
              className="h-full flex flex-col justify-between pl-12 cursor-pointer group select-none"
            >
              <div className="flex items-center justify-between pb-2 border-b border-slate-100/80">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-purple-500" />
                  <span className="text-sm md:text-base font-bold text-slate-900">模拟面试实战对练</span>
                </div>
                <span className="text-xs text-purple-600 font-medium flex items-center gap-1 group-hover:translate-x-1 transition-transform">
                  <span>进入模拟</span>
                  <ArrowRight size={12} />
                </span>
              </div>

              <p className="text-xs text-slate-600 leading-relaxed">
                沉浸式多轮语音/文本对练，AI 面试官实时深度追问与应变考核，即时出具雷达评分与改进诊断。
              </p>

              <div className="pt-1 flex items-center justify-between text-[10px] text-slate-400">
                <span>多轮语音深度追问</span>
                <span className="text-purple-700 font-mono">智能考官</span>
              </div>
            </div>
          </div>
        </div>

        {/* 核心锚点：中央 Copilot 胶囊浮岛 */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center pointer-events-auto">
          <div className="w-[380px] md:w-[420px] bg-white/95 backdrop-blur-xl border border-blue-200/80 shadow-xl shadow-blue-500/10 rounded-2xl p-4 flex flex-col items-center gap-2.5 ring-4 ring-blue-50/50">
            <div className="text-center">
              <h2 className="text-base font-bold text-slate-800">全流程智能面试中枢</h2>
              <p className="text-xs text-slate-500">
                面试备战 · 对练 · 深度复盘
              </p>
            </div>
            <form onSubmit={handleStartPrep} className="w-full flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-xl px-3 py-1.5">
              <Sparkles className="w-4 h-4 text-blue-500 shrink-0" />
              <input
                type="text"
                value={prepPrompt}
                onChange={(e) => setPrepPrompt(e.target.value)}
                placeholder="输入目标公司或考点进行备战..."
                className="flex-1 bg-transparent text-xs outline-none text-slate-700 placeholder-slate-400"
              />
              <button
                type="submit"
                className="p-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors cursor-pointer"
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
