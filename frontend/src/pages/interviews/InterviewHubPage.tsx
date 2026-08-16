import { useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Mic2,
  FileBarChart2,
  BookOpen,
  Sparkles,
  ArrowRight,
  CornerDownLeft,
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
      <div className="h-full flex flex-col">
        <div className="px-6 py-2.5 bg-white border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSearchParams({ tab: 'hub' })}
              className="text-xs font-semibold text-slate-500 hover:text-blue-600 cursor-pointer"
            >
              ← 返回面试中枢
            </button>
            <span className="text-slate-300">/</span>
            <span className="text-xs font-bold text-slate-800">模拟面试对练</span>
          </div>
        </div>
        <div className="flex-1 min-h-0">
          <MockPage />
        </div>
      </div>
    );
  }

  if (tab === 'review') {
    return (
      <div className="h-full flex flex-col">
        <div className="px-6 py-2.5 bg-white border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSearchParams({ tab: 'hub' })}
              className="text-xs font-semibold text-slate-500 hover:text-blue-600 cursor-pointer"
            >
              ← 返回面试中枢
            </button>
            <span className="text-slate-300">/</span>
            <span className="text-xs font-bold text-slate-800">真实面试深度复盘</span>
          </div>
        </div>
        <div className="flex-1 min-h-0">
          <ReviewPage />
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6 lg:p-8 bg-[#F8FAFC] flex flex-col justify-center select-none">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        {/* Header */}
        <header className="text-center space-y-1.5 pb-2">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-50 text-blue-700 text-xs font-semibold mb-1">
            <Mic2 size={13} />
            <span>全流程智能面试中枢</span>
          </div>
          <h1 className="text-2xl md:text-3xl font-black text-slate-900 tracking-tight">
            面试备战 · 对练 · 复盘
          </h1>
          <p className="text-xs md:text-sm text-slate-500 max-w-xl mx-auto">
            以目标岗位为核心，全方位覆盖考前准备冲刺、真实模拟实战对练与实战录音深度诊断。
          </p>
        </header>

        {/* Center Copilot Preparation Island */}
        <div className="max-w-2xl mx-auto w-full p-5 rounded-3xl bg-white border border-slate-200/90 shadow-sm space-y-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-bold text-slate-800 flex items-center gap-1.5">
              <Sparkles size={14} className="text-blue-600" />
              <span>Copilot 针对性面试备战</span>
            </span>
            <span className="text-slate-400">输入目标公司、职位或技术考点</span>
          </div>

          <form onSubmit={handleStartPrep} className="relative flex items-center">
            <input
              type="text"
              value={prepPrompt}
              onChange={(e) => setPrepPrompt(e.target.value)}
              placeholder="例如：准备腾讯后端技术一面高频系统设计考点与应对策略…"
              className="w-full pl-4 pr-24 py-3 rounded-2xl bg-slate-50 hover:bg-slate-100/80 focus:bg-white text-xs md:text-sm text-slate-800 placeholder-slate-400 border border-slate-200/90 focus:border-blue-500 outline-none transition-all"
            />
            <button
              type="submit"
              className="absolute right-1.5 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold transition-all shadow-xs flex items-center gap-1 cursor-pointer"
            >
              <span>生成备战指南</span>
              <CornerDownLeft size={12} />
            </button>
          </form>
        </div>

        {/* Three Radiating Core Workspaces */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5 pt-2">
          {/* Section 1: 面试准备 (Interview Preparation) */}
          <div
            onClick={() => navigate('/general-chat?prompt=帮我做针对性面试备战与高频考点预测')}
            className="group rounded-3xl bg-white border border-slate-200/90 p-6 shadow-2xs hover:border-blue-300 hover:shadow-md transition-all cursor-pointer flex flex-col justify-between space-y-4"
          >
            <div className="space-y-3">
              <div className="w-12 h-12 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center group-hover:scale-105 transition-transform shadow-2xs">
                <BookOpen size={24} />
              </div>
              <div>
                <h3 className="text-base font-bold text-slate-900 group-hover:text-blue-600 transition-colors">
                  面试准备与考点速查
                </h3>
                <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                  智能解析目标岗位 JD、深挖业务背景、提炼核心追问考点与 STAR 结构化应答指南。
                </p>
              </div>
            </div>

            <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs font-semibold text-blue-600">
              <span>进入备战空间</span>
              <ArrowRight size={14} className="group-hover:translate-x-1 transition-transform" />
            </div>
          </div>

          {/* Section 2: 模拟面试 (Mock Interview) */}
          <div
            onClick={() => setSearchParams({ tab: 'mock' })}
            className="group rounded-3xl bg-gradient-to-b from-purple-50/40 via-white to-white border border-purple-200/90 p-6 shadow-2xs hover:border-purple-300 hover:shadow-md transition-all cursor-pointer flex flex-col justify-between space-y-4"
          >
            <div className="space-y-3">
              <div className="w-12 h-12 rounded-2xl bg-purple-50 text-purple-600 flex items-center justify-center group-hover:scale-105 transition-transform shadow-2xs">
                <Mic2 size={24} />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-base font-bold text-slate-900 group-hover:text-purple-700 transition-colors">
                    模拟面试实战对练
                  </h3>
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 text-purple-800">
                    实战
                  </span>
                </div>
                <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                  沉浸式多轮语音/文本对练，AI 面试官随机追问与应变考核，即时生成答题评分。
                </p>
              </div>
            </div>

            <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs font-semibold text-purple-700">
              <span>开始对练</span>
              <ArrowRight size={14} className="group-hover:translate-x-1 transition-transform" />
            </div>
          </div>

          {/* Section 3: 面试复盘 (Interview Review) */}
          <div
            onClick={() => setSearchParams({ tab: 'review' })}
            className="group rounded-3xl bg-gradient-to-b from-emerald-50/40 via-white to-white border border-emerald-200/90 p-6 shadow-2xs hover:border-emerald-300 hover:shadow-md transition-all cursor-pointer flex flex-col justify-between space-y-4"
          >
            <div className="space-y-3">
              <div className="w-12 h-12 rounded-2xl bg-emerald-50 text-emerald-600 flex items-center justify-center group-hover:scale-105 transition-transform shadow-2xs">
                <FileBarChart2 size={24} />
              </div>
              <div>
                <h3 className="text-base font-bold text-slate-900 group-hover:text-emerald-700 transition-colors">
                  真实面试深度复盘
                </h3>
                <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                  一键导入实战录音，WhisperX 极速逐字转写，AI 多维诊断、答题结构优化与证据链沉淀。
                </p>
              </div>
            </div>

            <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs font-semibold text-emerald-700">
              <span>进入复盘工作区</span>
              <ArrowRight size={14} className="group-hover:translate-x-1 transition-transform" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
