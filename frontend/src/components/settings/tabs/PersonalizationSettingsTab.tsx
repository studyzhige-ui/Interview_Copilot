import { useState, useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ShieldCheck, Sparkles, Brain, Save } from 'lucide-react';
import { getMe, updateMe } from '@/api/auth';
import {
  getCopilotPreference,
  updateCopilotPreference,
  getAgentMemorySettings,
  updateAgentMemorySettings,
} from '@/api/personalization';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';

const PREFERENCE_KEY = ['personalization', 'copilot-preference'] as const;
const MEMORY_SETTINGS_KEY = ['personalization', 'memory-settings'] as const;
const PROFILE_KEY = ['auth', 'me'] as const;

export function PersonalizationSettingsTab() {
  const queryClient = useQueryClient();

  const profileQuery = useQuery({
    queryKey: PROFILE_KEY,
    queryFn: getMe,
  });

  const preferenceQuery = useQuery({
    queryKey: PREFERENCE_KEY,
    queryFn: getCopilotPreference,
  });

  const memoryQuery = useQuery({
    queryKey: MEMORY_SETTINGS_KEY,
    queryFn: getAgentMemorySettings,
  });

  const [mode, setMode] = useState<'standard' | 'auto'>('standard');
  const [backgroundPrompt, setBackgroundPrompt] = useState('');
  const [stylePrompt, setStylePrompt] = useState('');
  const [enableMemory, setEnableMemory] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (profileQuery.data?.default_execution_mode) {
      setMode(profileQuery.data.default_execution_mode);
    }
  }, [profileQuery.data]);

  useEffect(() => {
    if (preferenceQuery.data?.instructions) {
      const instructions = preferenceQuery.data.instructions;
      setBackgroundPrompt(instructions[0] || '');
      setStylePrompt(instructions.slice(1).join('\n') || '');
    }
  }, [preferenceQuery.data]);

  useEffect(() => {
    if (memoryQuery.data) {
      setEnableMemory(memoryQuery.data.recall_enabled && memoryQuery.data.contribution_enabled);
    }
  }, [memoryQuery.data]);

  const handleSave = async () => {
    setSaving(true);
    try {
      // 1. Update Default Execution Mode
      await updateMe({ default_execution_mode: mode });

      // 2. Update Custom Instructions
      const instructions = [
        backgroundPrompt.trim(),
        stylePrompt.trim(),
      ].filter(Boolean);

      const prefVersion = preferenceQuery.data?.version ?? 0;
      await updateCopilotPreference(prefVersion, instructions);

      // 3. Update Memory Settings
      if (memoryQuery.data) {
        await updateAgentMemorySettings(
          memoryQuery.data.version,
          enableMemory,
          enableMemory,
        );
      }

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: PROFILE_KEY }),
        queryClient.invalidateQueries({ queryKey: PREFERENCE_KEY }),
        queryClient.invalidateQueries({ queryKey: MEMORY_SETTINGS_KEY }),
      ]);

      toast.success('个性化偏好已保存');
    } catch (err) {
      toast.error(extractErr(err, '保存失败，请重试'));
    } finally {
      setSaving(false);
    }
  };

  const loading = profileQuery.isLoading || preferenceQuery.isLoading || memoryQuery.isLoading;

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center text-slate-400 gap-2 text-sm">
        <Spinner size={18} />
        <span>正在载入个性化偏好…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 text-slate-800 animate-in fade-in duration-200">
      <div>
        <h3 className="text-lg font-bold text-slate-900 tracking-tight">个性化偏好与定制指令</h3>
        <p className="text-xs text-slate-500 mt-1">
          设定 Copilot 对你的理解方式、沟通语气以及默认审批策略。
        </p>
      </div>

      {/* 1. Execution Mode Toggle */}
      <div className="space-y-2.5">
        <div className="text-xs font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
          <ShieldCheck size={14} className="text-blue-600" />
          <span>新对话默认执行模式</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <button
            type="button"
            onClick={() => setMode('standard')}
            className={`p-3.5 rounded-2xl border text-left transition-all cursor-pointer ${
              mode === 'standard'
                ? 'border-blue-300 bg-blue-50/50 shadow-xs ring-1 ring-blue-200'
                : 'border-slate-200/80 bg-white hover:border-slate-300'
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-bold text-slate-900">每次确认 (Standard)</span>
              {mode === 'standard' && (
                <span className="w-2 h-2 rounded-full bg-blue-600 inline-block" />
              )}
            </div>
            <p className="text-xs text-slate-500 mt-1">
              外部副作用（如邮件发送、持久修改）在执行前逐次请求确认。
            </p>
          </button>

          <button
            type="button"
            onClick={() => setMode('auto')}
            className={`p-3.5 rounded-2xl border text-left transition-all cursor-pointer ${
              mode === 'auto'
                ? 'border-blue-300 bg-blue-50/50 shadow-xs ring-1 ring-blue-200'
                : 'border-slate-200/80 bg-white hover:border-slate-300'
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-bold text-slate-900">自动审批 (Auto)</span>
              {mode === 'auto' && (
                <span className="w-2 h-2 rounded-full bg-blue-600 inline-block" />
              )}
            </div>
            <p className="text-xs text-slate-500 mt-1">
              在明确授权范围内减少普通审批，高风险动作仍会主动询问。
            </p>
          </button>
        </div>
      </div>

      {/* 2. Custom Instructions: Background & Style */}
      <div className="space-y-3.5 pt-2">
        <div className="text-xs font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
          <Sparkles size={14} className="text-purple-600" />
          <span>定制人设指令 (Custom Instructions)</span>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-slate-700">
            你希望 Copilot 如何了解你的背景与求职定位？
          </label>
          <textarea
            rows={2}
            value={backgroundPrompt}
            onChange={(e) => setBackgroundPrompt(e.target.value)}
            placeholder="例如：3年资深后端架构师，主要技术栈为 Go/Java，正在冲刺一线大厂或外企高薪岗位..."
            className="w-full p-3 bg-slate-50 border border-slate-200/90 rounded-2xl text-xs text-slate-800 placeholder-slate-400 outline-none focus:border-blue-400 focus:bg-white transition-all leading-relaxed"
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-slate-700">
            你希望 Copilot 采用怎样的回复与辅导风格？
          </label>
          <textarea
            rows={2}
            value={stylePrompt}
            onChange={(e) => setStylePrompt(e.target.value)}
            placeholder="例如：就事论事、直接犀利指出漏洞、严格按照 STAR 范式给出高分改写答案..."
            className="w-full p-3 bg-slate-50 border border-slate-200/90 rounded-2xl text-xs text-slate-800 placeholder-slate-400 outline-none focus:border-blue-400 focus:bg-white transition-all leading-relaxed"
          />
        </div>
      </div>

      {/* 3. Cross-Session Memory Switch */}
      <div className="p-4 rounded-2xl bg-slate-50 border border-slate-200/80 flex items-center justify-between gap-4">
        <div className="space-y-0.5">
          <div className="text-sm font-semibold text-slate-800 flex items-center gap-1.5">
            <Brain size={16} className="text-indigo-600" />
            <span>智能记忆与沉淀 (Agent Memory)</span>
          </div>
          <div className="text-xs text-slate-500">
            允许 Copilot 在对话中自动提炼你的项目亮点与偏好，并在后续面试中持续强化
          </div>
        </div>

        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={enableMemory}
            onChange={(e) => setEnableMemory(e.target.checked)}
            className="sr-only peer"
          />
          <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
        </label>
      </div>

      {/* Save Button */}
      <div className="flex justify-end pt-2">
        <Btn
          kind="primary"
          size="md"
          loading={saving}
          onClick={handleSave}
          className="px-6 py-2 rounded-full font-semibold shadow-xs"
        >
          <Save size={15} />
          <span>保存个性化设置</span>
        </Btn>
      </div>
    </div>
  );
}
