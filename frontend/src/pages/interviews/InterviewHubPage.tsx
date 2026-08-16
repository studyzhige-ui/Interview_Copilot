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
    <div className="relative w-full h-full overflow-hidden select-none font-sans bg-[#F8FAFC]">
      
      {/* ═══ 1. Aurora Radial Glow Background ═══ */}
      <div className="absolute inset-0 z-0 opacity-90 pointer-events-none">
        {/* Top: 淡蓝光 (#E0F2FE) */}
        <div className="absolute top-[-10%] left-1/2 -translate-x-1/2 w-[70%] h-[50%] rounded-full bg-[#E0F2FE]/80 blur-[140px]" />
        {/* Bottom-left: 薄荷绿 (#DCFCE7) */}
        <div className="absolute bottom-[-10%] left-[-10%] w-[60%] h-[60%] rounded-full bg-[#DCFCE7]/80 blur-[140px]" />
        {/* Bottom-right: 丁香紫 (#F3E8FF) */}
        <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] rounded-full bg-[#F3E8FF]/80 blur-[140px]" />
      </div>

      {/* ═══ 2. Central Nexus (White Core Depth Dropoff) ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[700px] rounded-full bg-white/70 blur-[100px] pointer-events-none z-10" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[450px] h-[450px] rounded-full bg-white/90 shadow-[0_0_80px_rgba(255,255,255,1)] blur-[40px] pointer-events-none z-10" />

      {/* ═══ 3. Central Copilot Island (Input Controls) ═══ */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30 flex flex-col items-center">
        <div className="w-[380px] backdrop-blur-2xl bg-white/80 border border-white/90 shadow-[0_8px_30px_rgba(0,0,0,0.04)] rounded-[2rem] p-3 flex flex-col items-center gap-2">
          <div className="w-full flex items-center justify-between px-3">
            <h2 className="text-sm font-bold text-slate-800 flex items-center gap-1.5">
              <Mic2 className="w-4 h-4 text-indigo-500" />
              智能面试中枢
            </h2>
            <p className="text-[10px] font-bold text-indigo-700 bg-indigo-50/80 px-2 py-0.5 rounded-full border border-indigo-200">
              全流程护航
            </p>
          </div>
          <form onSubmit={handleStartPrep} className="w-full relative">
            <input
              type="text"
              value={prepPrompt}
              onChange={(e) => setPrepPrompt(e.target.value)}
              placeholder="输入目标公司或考点开启特训…"
              className="w-full h-11 bg-white/60 border border-slate-200/50 rounded-2xl pl-4 pr-12 text-xs outline-none text-slate-700 placeholder-slate-400 focus:bg-white/90 transition-colors shadow-inner shadow-slate-100/50"
            />
            <button
              type="submit"
              className="absolute right-1.5 top-1.5 bottom-1.5 w-8 flex items-center justify-center bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl transition-colors cursor-pointer shadow-sm"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>
      </div>

      {/* ═══ 4. Three Partitions (Strict flex layout for perfect centering) ═══ */}
      <div className="relative z-20 w-full h-full flex flex-col">

        {/* ─── Top: 面试准备与考点速查 ─── */}
        <div className="flex-1 flex items-center justify-center pt-8 px-10 pb-24">
          <div
            onClick={() => navigate('/general-chat?prompt=帮我做针对性面试备战与高频考点预测')}
            className="w-full max-w-xl flex flex-col items-center text-center cursor-pointer group"
          >
            <div className="bg-white/50 border border-white/70 p-3 rounded-2xl shadow-sm mb-4 group-hover:scale-105 transition-transform">
              <BookOpen size={24} className="text-blue-600" />
            </div>
            <h3 className="text-lg font-bold text-slate-900 group-hover:text-blue-700 transition-colors mb-2">
              面试准备与考点速查
            </h3>
            <p className="text-xs text-slate-600 leading-relaxed mb-4 max-w-md">
              智能解析目标岗位 JD、深挖业务背景、提炼核心追问考点与 STAR 结构化应答指南。
            </p>
            <div className="flex items-center justify-center gap-2 text-[11px] font-bold text-slate-500">
              <span className="px-3 py-1 rounded-full bg-white/70 border border-white shadow-sm">JD 考点拆解</span>
              <span className="px-3 py-1 rounded-full bg-white/70 border border-white shadow-sm">STAR 训练</span>
              <span className="px-3 py-1 rounded-full bg-white/70 border border-white shadow-sm">业务深挖模拟</span>
            </div>
          </div>
        </div>

        {/* ─── Bottom Half ─── */}
        <div className="flex-1 flex">
          
          {/* Bottom-Left: 真实面试深度复盘 */}
          <div className="flex-1 flex items-center justify-center pl-10 pt-20 pb-10 pr-24">
            <div
              onClick={() => setSearchParams({ tab: 'review' })}
              className="w-full max-w-[320px] flex flex-col items-start cursor-pointer group bg-white/40 hover:bg-white/60 p-6 rounded-[2rem] border border-white/60 shadow-sm transition-colors"
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
          <div className="flex-1 flex items-center justify-center pr-10 pt-20 pb-10 pl-24">
            <div
              onClick={() => setSearchParams({ tab: 'mock' })}
              className="w-full max-w-[320px] flex flex-col items-start cursor-pointer group bg-white/40 hover:bg-white/60 p-6 rounded-[2rem] border border-white/60 shadow-sm transition-colors"
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

      </div>
    </div>
  );
}
