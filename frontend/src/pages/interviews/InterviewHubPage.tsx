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
    <div className="relative w-full h-full overflow-hidden select-none font-sans">
      {/* ═══ Aurora Radial Glow Background ═══ */}
      <div className="absolute inset-0 z-0 bg-[#F9FAFB]">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-white/80 blur-[120px]" />
        <div className="absolute -top-20 left-1/2 -translate-x-1/2 w-[600px] h-[400px] rounded-full bg-blue-200/30 blur-[140px]" />
        <div className="absolute -bottom-10 -left-20 w-[500px] h-[500px] rounded-full bg-emerald-200/30 blur-[130px]" />
        <div className="absolute -bottom-10 -right-20 w-[500px] h-[500px] rounded-full bg-violet-200/30 blur-[130px]" />
      </div>

      {/* ═══ Center Copilot Capsule Island ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30">
        <div className="w-[340px] backdrop-blur-2xl bg-white/80 border border-white/60 shadow-lg rounded-2xl p-4 flex flex-col items-center gap-3">
          <div className="text-center">
            <div className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-indigo-50/80 text-indigo-700 text-[10px] font-bold mb-1">
              <Mic2 size={10} />
              全流程智能面试中枢
            </div>
            <h2 className="text-sm font-bold text-slate-800">面试备战 · 对练 · 复盘</h2>
          </div>
          <form onSubmit={handleStartPrep} className="w-full flex items-center gap-2 bg-white/60 border border-slate-200/80 rounded-xl px-3 py-2">
            <Sparkles className="w-4 h-4 text-indigo-500 shrink-0" />
            <input
              type="text"
              value={prepPrompt}
              onChange={(e) => setPrepPrompt(e.target.value)}
              placeholder="输入目标公司或考点…"
              className="flex-1 bg-transparent text-xs outline-none text-slate-700 placeholder-slate-400"
            />
            <button type="submit" className="p-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors cursor-pointer">
              <Send className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>
      </div>

      {/* ═══ Three Partitions (top full-width, bottom 2-col) ═══ */}
      <div className="relative z-10 w-full h-full flex flex-col p-8 gap-y-20">

        {/* Top: 面试准备与考点速查 */}
        <div
          onClick={() => navigate('/general-chat?prompt=帮我做针对性面试备战与高频考点预测')}
          className="overflow-hidden flex-[4] flex flex-col justify-between pb-4 cursor-pointer group"
        >
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-base">
                <BookOpen size={16} className="text-blue-600" />
                面试准备与考点速查
              </div>
              <span className="text-[11px] text-blue-600 font-semibold flex items-center gap-0.5 group-hover:translate-x-1 transition-transform">
                进入备战空间 <ArrowUpRight className="w-3 h-3" />
              </span>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed max-w-lg">
              智能解析目标岗位 JD、深挖业务背景、提炼核心追问考点与 STAR 结构化应答指南。
            </p>
          </div>
          <div className="flex items-center gap-2 text-[10px] text-slate-400 pt-2">
            <span className="px-2 py-1 rounded-full bg-white/50 font-medium">JD 考点拆解</span>
            <span className="px-2 py-1 rounded-full bg-white/50 font-medium">STAR 应答训练</span>
            <span className="px-2 py-1 rounded-full bg-white/50 font-medium">业务深挖模拟</span>
          </div>
        </div>

        {/* Bottom row */}
        <div className="flex-[5] grid grid-cols-2 gap-x-28 pt-4">

          {/* Bottom-Left: 真实面试深度复盘 */}
          <div
            onClick={() => setSearchParams({ tab: 'review' })}
            className="overflow-hidden flex flex-col justify-between cursor-pointer group"
          >
            <div>
              <div className="flex items-center justify-between mb-2">
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
            <div className="flex items-center justify-between text-[10px] text-slate-400 pt-3 border-t border-slate-200/40">
              <span>实战录音导入诊断</span>
              <span className="text-emerald-700 font-mono font-medium">WhisperX 驱动</span>
            </div>
          </div>

          {/* Bottom-Right: 模拟面试实战对练 */}
          <div
            onClick={() => setSearchParams({ tab: 'mock' })}
            className="overflow-hidden flex flex-col justify-between cursor-pointer group"
          >
            <div>
              <div className="flex items-center justify-between mb-2">
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
            <div className="flex items-center justify-between text-[10px] text-slate-400 pt-3 border-t border-slate-200/40">
              <span>实时语音多轮追问</span>
              <span className="text-purple-700 font-mono font-medium">智能考官</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
