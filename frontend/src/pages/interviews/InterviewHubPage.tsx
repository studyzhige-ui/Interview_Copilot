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
    <div className="relative w-full h-full overflow-hidden select-none font-sans bg-white flex flex-col">
      
      {/* ═══ 1. Ambient Area Backgrounds (Soft, Borderless) ═══ */}
      <div className="absolute inset-0 z-0 pointer-events-none">
        {/* Top: Light blue / Purple */}
        <div className="absolute top-[-10%] left-[20%] w-[60%] h-[50%] rounded-full bg-blue-100/50 blur-[120px]" />
        {/* Bottom-left: Emerald */}
        <div className="absolute bottom-[-10%] left-[-10%] w-[50%] h-[60%] rounded-full bg-emerald-100/50 blur-[120px]" />
        {/* Bottom-right: Purple/Orange */}
        <div className="absolute bottom-[-10%] right-[-10%] w-[50%] h-[60%] rounded-full bg-purple-100/50 blur-[120px]" />
      </div>

      {/* ═══ 2. SVG Clip Path Definitions (3-Pointed Astroid) ═══ */}
      <svg width="0" height="0" className="absolute pointer-events-none">
        <defs>
          <clipPath id="tristar-clip" clipPathUnits="objectBoundingBox">
            <path d="M 0.5 0 Q 0.5 0.5 1 0.866 Q 0.5 0.5 0 0.866 Q 0.5 0.5 0.5 0 Z" />
          </clipPath>
        </defs>
      </svg>

      {/* ═══ 3. Gemini Astroid Spark Core ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-10 w-[600px] h-[600px] pointer-events-none flex items-center justify-center">
        {/* Deep ambient glow backing the star */}
        <div className="absolute w-[360px] h-[360px] bg-gradient-to-tr from-emerald-300 via-blue-400 to-purple-400 rounded-full blur-[70px] opacity-30" />
        
        {/* The Crisp 3-Pointed Astroid Star */}
        <div 
          className="relative w-[340px] h-[340px] overflow-hidden"
          style={{ clipPath: 'url(#tristar-clip)', WebkitClipPath: 'url(#tristar-clip)' }}
        >
          {/* Multi-color mesh gradient simulation */}
          <div className="absolute inset-0 bg-gradient-to-t from-emerald-400 via-blue-500 to-indigo-500 opacity-90 mix-blend-screen" />
          <div className="absolute inset-0 bg-gradient-to-br from-amber-300/80 to-transparent mix-blend-overlay" />
          <div className="absolute -top-10 -left-10 w-[200px] h-[200px] bg-blue-300/60 blur-[40px]" />
          <div className="absolute -bottom-10 -right-10 w-[200px] h-[200px] bg-purple-500/60 blur-[40px]" />
        </div>
      </div>

      {/* ═══ 4. Embedded Central Input Controls ═══ */}
      <div className="absolute top-[48%] left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center pointer-events-auto">
        <h2 className="text-[28px] font-black text-slate-900 mb-1 tracking-tight drop-shadow-sm flex items-center gap-2">
          智能面试中枢
        </h2>
        <p className="text-[13px] font-bold text-slate-600 mb-7 drop-shadow-sm">
          沉浸式全流程护航
        </p>
        <form 
          onSubmit={handleStartPrep} 
          className="w-[460px] h-[52px] bg-white/70 backdrop-blur-2xl shadow-[0_8px_32px_rgba(0,0,0,0.06)] border border-white rounded-full px-5 flex items-center gap-3 transition-all hover:shadow-[0_12px_40px_rgba(0,0,0,0.08)] hover:bg-white/80"
        >
          <Sparkles className="w-5 h-5 text-indigo-500 shrink-0" />
          <input
            type="text"
            value={prepPrompt}
            onChange={(e) => setPrepPrompt(e.target.value)}
            placeholder="输入目标公司或考点开启特训…"
            className="flex-1 bg-transparent text-[13px] font-medium outline-none text-slate-800 placeholder-slate-500"
          />
          <button
            type="submit"
            className="w-8 h-8 flex items-center justify-center bg-indigo-600 hover:bg-indigo-700 text-white rounded-full transition-colors cursor-pointer shrink-0"
          >
            <Send className="w-4 h-4 -ml-0.5" />
          </button>
        </form>
      </div>

      {/* ═══ 5. Free-floating Regions (No borders) ═══ */}
      <div className="relative z-20 w-full h-full flex flex-col">
        
        {/* ─── Top: 面试准备与考点速查 ─── */}
        <div className="flex-1 flex items-center justify-center pt-8 px-10 pb-32">
          <div
            onClick={() => navigate('/general-chat?prompt=帮我做针对性面试备战与高频考点预测')}
            className="w-full max-w-xl flex flex-col items-center text-center cursor-pointer group"
          >
            <div className="bg-white/40 backdrop-blur-sm border border-white/60 p-3 rounded-2xl shadow-sm mb-4 group-hover:scale-105 transition-transform group-hover:bg-white/60">
              <BookOpen size={24} className="text-blue-600" />
            </div>
            <h3 className="text-lg font-bold text-slate-900 group-hover:text-blue-700 transition-colors mb-2 drop-shadow-sm">
              面试准备与考点速查
            </h3>
            <p className="text-[13px] font-medium text-slate-600 leading-relaxed mb-4 max-w-md drop-shadow-sm">
              智能解析目标岗位 JD、深挖业务背景、提炼核心追问考点与 STAR 结构化应答指南。
            </p>
            <div className="flex items-center justify-center gap-2 text-[11px] font-bold text-slate-500">
              <span className="px-3 py-1 rounded-full bg-white/60 backdrop-blur-md border border-white/80 shadow-sm">JD 考点拆解</span>
              <span className="px-3 py-1 rounded-full bg-white/60 backdrop-blur-md border border-white/80 shadow-sm">STAR 训练</span>
              <span className="px-3 py-1 rounded-full bg-white/60 backdrop-blur-md border border-white/80 shadow-sm">业务深挖模拟</span>
            </div>
          </div>
        </div>

        {/* ─── Bottom Half ─── */}
        <div className="flex-1 w-full flex">
          
          {/* Bottom-Left: 真实面试深度复盘 */}
          <div className="flex-1 flex items-center justify-center pl-10 pt-28 pb-10 pr-24">
            <div
              onClick={() => setSearchParams({ tab: 'review' })}
              className="w-full max-w-[320px] flex flex-col items-start cursor-pointer group"
            >
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2.5 rounded-xl bg-emerald-100/50 backdrop-blur-sm text-emerald-600 group-hover:bg-emerald-100 transition-colors shadow-sm border border-white/40">
                  <FileBarChart2 size={20} />
                </div>
                <h3 className="text-base font-bold text-slate-900 group-hover:text-emerald-700 transition-colors drop-shadow-sm">
                  真实面试深度复盘
                </h3>
              </div>
              <p className="text-[13px] font-medium text-slate-600 leading-relaxed mb-4 drop-shadow-sm">
                一键导入实战录音，WhisperX 极速逐字转写，AI 多维诊断、答题结构优化与证据链沉淀。
              </p>
              <span className="text-[11px] text-emerald-700 font-bold flex items-center gap-1 group-hover:translate-x-1 transition-transform drop-shadow-sm">
                进入复盘 <ArrowUpRight className="w-3 h-3" />
              </span>
            </div>
          </div>

          {/* Bottom-Right: 模拟面试实战对练 */}
          <div className="flex-1 flex items-center justify-center pr-10 pt-28 pb-10 pl-24">
            <div
              onClick={() => setSearchParams({ tab: 'mock' })}
              className="w-full max-w-[320px] flex flex-col items-start cursor-pointer group"
            >
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2.5 rounded-xl bg-purple-100/50 backdrop-blur-sm text-purple-600 group-hover:bg-purple-100 transition-colors shadow-sm border border-white/40">
                  <Mic2 size={20} />
                </div>
                <h3 className="text-base font-bold text-slate-900 group-hover:text-purple-700 transition-colors drop-shadow-sm">
                  模拟面试实战对练
                </h3>
              </div>
              <p className="text-[13px] font-medium text-slate-600 leading-relaxed mb-4 drop-shadow-sm">
                沉浸式多轮语音或文本对练，AI 考官实时深度追问考核，即时出具雷达评分与诊断。
              </p>
              <span className="text-[11px] text-purple-700 font-bold flex items-center gap-1 group-hover:translate-x-1 transition-transform drop-shadow-sm">
                进入模拟 <ArrowUpRight className="w-3 h-3" />
              </span>
            </div>
          </div>

        </div>

      </div>
    </div>
  );
}
