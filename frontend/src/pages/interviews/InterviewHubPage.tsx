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
    <div className="relative w-full h-full overflow-hidden select-none font-sans bg-slate-50 p-4 gap-4 flex flex-col">
      
      {/* ─── Top: 面试准备与考点速查 ─── */}
      <div 
        className="flex-1 w-full bg-blue-50/60 backdrop-blur-md shadow-[0_4px_24px_rgba(0,0,0,0.03)] border border-slate-200/60 rounded-[2rem] flex items-center justify-center p-10"
        style={{ 
          maskImage: 'radial-gradient(circle at bottom center, transparent 200px, black 201px)',
          WebkitMaskImage: 'radial-gradient(circle at bottom center, transparent 200px, black 201px)'
        }}
      >
        <div
          onClick={() => navigate('/general-chat?prompt=帮我做针对性面试备战与高频考点预测')}
          className="w-full max-w-xl flex flex-col items-center text-center cursor-pointer group -mt-16"
        >
          <div className="bg-white/70 border border-slate-100 p-3 rounded-2xl shadow-sm mb-4 group-hover:scale-105 transition-transform">
            <BookOpen size={24} className="text-blue-600" />
          </div>
          <h3 className="text-lg font-bold text-slate-900 group-hover:text-blue-700 transition-colors mb-2">
            面试准备与考点速查
          </h3>
          <p className="text-xs text-slate-600 leading-relaxed mb-4 max-w-md">
            智能解析目标岗位 JD、深挖业务背景、提炼核心追问考点与 STAR 结构化应答指南。
          </p>
          <div className="flex items-center justify-center gap-2 text-[11px] font-bold text-slate-500">
            <span className="px-3 py-1 rounded-full bg-white/80 border border-slate-200/50 shadow-sm">JD 考点拆解</span>
            <span className="px-3 py-1 rounded-full bg-white/80 border border-slate-200/50 shadow-sm">STAR 训练</span>
            <span className="px-3 py-1 rounded-full bg-white/80 border border-slate-200/50 shadow-sm">业务深挖模拟</span>
          </div>
        </div>
      </div>

      {/* ─── Bottom Half ─── */}
      <div className="flex-1 w-full flex gap-4">
        
        {/* Bottom-Left: 真实面试深度复盘 */}
        <div 
          className="flex-1 bg-emerald-50/50 backdrop-blur-md shadow-[0_4px_24px_rgba(0,0,0,0.03)] border border-slate-200/60 rounded-[2rem] flex items-center justify-center p-10"
          style={{ 
            maskImage: 'radial-gradient(circle at top right, transparent 200px, black 201px)',
            WebkitMaskImage: 'radial-gradient(circle at top right, transparent 200px, black 201px)'
          }}
        >
          <div
            onClick={() => setSearchParams({ tab: 'review' })}
            className="w-full max-w-[320px] flex flex-col items-start cursor-pointer group bg-white/60 hover:bg-white p-6 rounded-[2rem] border border-slate-100 shadow-sm transition-all -mb-16 -ml-16"
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2.5 rounded-xl bg-emerald-100/50 text-emerald-600 group-hover:bg-emerald-100 transition-colors">
                <FileBarChart2 size={20} />
              </div>
              <h3 className="text-base font-bold text-slate-900 group-hover:text-emerald-700 transition-colors">
                真实面试深度复盘
              </h3>
            </div>
            <p className="text-[11px] text-slate-600 leading-relaxed mb-4">
              一键导入实战录音，WhisperX 极速逐字转写，AI 多维诊断、答题结构优化与证据链沉淀。
            </p>
            <span className="text-[11px] text-emerald-700 font-bold flex items-center gap-1 group-hover:translate-x-1 transition-transform">
              进入复盘 <ArrowUpRight className="w-3 h-3" />
            </span>
          </div>
        </div>

        {/* Bottom-Right: 模拟面试实战对练 */}
        <div 
          className="flex-1 bg-purple-50/50 backdrop-blur-md shadow-[0_4px_24px_rgba(0,0,0,0.03)] border border-slate-200/60 rounded-[2rem] flex items-center justify-center p-10"
          style={{ 
            maskImage: 'radial-gradient(circle at top left, transparent 200px, black 201px)',
            WebkitMaskImage: 'radial-gradient(circle at top left, transparent 200px, black 201px)'
          }}
        >
          <div
            onClick={() => setSearchParams({ tab: 'mock' })}
            className="w-full max-w-[320px] flex flex-col items-start cursor-pointer group bg-white/60 hover:bg-white p-6 rounded-[2rem] border border-slate-100 shadow-sm transition-all -mb-16 -mr-16"
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2.5 rounded-xl bg-purple-100/50 text-purple-600 group-hover:bg-purple-100 transition-colors">
                <Mic2 size={20} />
              </div>
              <h3 className="text-base font-bold text-slate-900 group-hover:text-purple-700 transition-colors">
                模拟面试实战对练
              </h3>
            </div>
            <p className="text-[11px] text-slate-600 leading-relaxed mb-4">
              沉浸式多轮语音或文本对练，AI 考官实时深度追问考核，即时出具雷达评分与诊断。
            </p>
            <span className="text-[11px] text-purple-700 font-bold flex items-center gap-1 group-hover:translate-x-1 transition-transform">
              进入模拟 <ArrowUpRight className="w-3 h-3" />
            </span>
          </div>
        </div>

      </div>

      {/* ═══ Central Copilot Core (Seamless, NO floating box) ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center pointer-events-auto">
        <h2 className="text-2xl font-black text-slate-800 mb-1 tracking-tight flex items-center gap-2">
          智能面试中枢
        </h2>
        <p className="text-sm font-medium text-slate-500 mb-6">
          沉浸式全流程护航
        </p>
        <form 
          onSubmit={handleStartPrep} 
          className="w-[420px] bg-white shadow-[0_8px_30px_rgba(0,0,0,0.08)] border border-slate-200/80 rounded-full px-5 py-3 flex items-center gap-3 transition-shadow hover:shadow-[0_12px_40px_rgba(0,0,0,0.12)]"
        >
          <Sparkles className="w-5 h-5 text-indigo-500 shrink-0" />
          <input
            type="text"
            value={prepPrompt}
            onChange={(e) => setPrepPrompt(e.target.value)}
            placeholder="输入目标公司或考点开启特训…"
            className="flex-1 bg-transparent text-sm outline-none text-slate-700 placeholder-slate-400"
          />
          <button
            type="submit"
            className="w-8 h-8 flex items-center justify-center bg-indigo-600 hover:bg-indigo-700 text-white rounded-full transition-colors cursor-pointer shrink-0"
          >
            <Send className="w-4 h-4 -ml-0.5" />
          </button>
        </form>
      </div>

    </div>
  );
}
