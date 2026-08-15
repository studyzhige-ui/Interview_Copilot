import { useState } from 'react';
import { Sun, Globe, Bell, Keyboard, Check } from 'lucide-react';
import { toast } from '@/store/uiStore';

export function GeneralSettingsTab() {
  const [theme, setTheme] = useState<'light' | 'system'>('light');
  const [lang, setLang] = useState<'zh-CN' | 'en-US'>('zh-CN');
  const [notifications, setNotifications] = useState(true);
  const [smartSuggestions, setSmartSuggestions] = useState(true);

  const handleSave = () => {
    toast.success('常规设置已自动保存');
  };

  return (
    <div className="space-y-6 text-slate-800 animate-in fade-in duration-200">
      <div>
        <h3 className="text-lg font-bold text-slate-900 tracking-tight">常规设置</h3>
        <p className="text-xs text-slate-500 mt-1">管理你的基础系统偏好、界面外观及快捷键设定。</p>
      </div>

      <div className="divide-y divide-slate-100">
        {/* Appearance */}
        <div className="py-4 flex items-center justify-between gap-4">
          <div className="space-y-0.5">
            <div className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              <Sun size={16} className="text-blue-600" />
              <span>外观主题</span>
            </div>
            <div className="text-xs text-slate-500">选择 Interview Copilot 的整体视觉模式</div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => { setTheme('light'); handleSave(); }}
              className={`px-3.5 py-1.5 rounded-full text-xs font-semibold border transition-all ${
                theme === 'light'
                  ? 'bg-blue-50 border-blue-300 text-blue-700 shadow-xs'
                  : 'bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100'
              }`}
            >
              Google 极简浅色
            </button>
            <button
              type="button"
              onClick={() => { setTheme('system'); handleSave(); }}
              className={`px-3.5 py-1.5 rounded-full text-xs font-semibold border transition-all ${
                theme === 'system'
                  ? 'bg-blue-50 border-blue-300 text-blue-700 shadow-xs'
                  : 'bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100'
              }`}
            >
              跟随系统
            </button>
          </div>
        </div>

        {/* Language */}
        <div className="py-4 flex items-center justify-between gap-4">
          <div className="space-y-0.5">
            <div className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              <Globe size={16} className="text-purple-600" />
              <span>界面语言</span>
            </div>
            <div className="text-xs text-slate-500">选择 Copilot 提示词与交互语言</div>
          </div>
          <select
            value={lang}
            onChange={(e) => { setLang(e.target.value as any); handleSave(); }}
            className="px-3.5 py-1.5 bg-slate-50 border border-slate-200/80 rounded-2xl text-xs font-semibold text-slate-700 outline-none focus:border-blue-400 cursor-pointer"
          >
            <option value="zh-CN">简体中文 (Chinese)</option>
            <option value="en-US">English (US)</option>
          </select>
        </div>

        {/* System Notifications */}
        <div className="py-4 flex items-center justify-between gap-4">
          <div className="space-y-0.5">
            <div className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              <Bell size={16} className="text-amber-600" />
              <span>桌面通知与进度提醒</span>
            </div>
            <div className="text-xs text-slate-500">在面试录音分析完成或后台自动化任务发现新邮件时提醒我</div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={notifications}
              onChange={(e) => { setNotifications(e.target.checked); handleSave(); }}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
          </label>
        </div>

        {/* Smart Context Suggestions */}
        <div className="py-4 flex items-center justify-between gap-4">
          <div className="space-y-0.5">
            <div className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              <Check size={16} className="text-emerald-600" />
              <span>智能追问联想</span>
            </div>
            <div className="text-xs text-slate-500">在复盘 QA 对或对话中自动给出相关的深度追问方向</div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={smartSuggestions}
              onChange={(e) => { setSmartSuggestions(e.target.checked); handleSave(); }}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
          </label>
        </div>

        {/* Keyboard Shortcuts */}
        <div className="py-4 flex items-start justify-between gap-4">
          <div className="space-y-0.5">
            <div className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              <Keyboard size={16} className="text-slate-600" />
              <span>常用快捷键</span>
            </div>
            <div className="text-xs text-slate-500">提升操作效率的全局按键组合</div>
          </div>
          <div className="space-y-1.5 text-right">
            <div className="text-xs text-slate-600">
              <span className="font-mono bg-slate-100 px-2 py-0.5 rounded-md border border-slate-200 mr-2">Shift + Enter</span>
              输入框换行
            </div>
            <div className="text-xs text-slate-600">
              <span className="font-mono bg-slate-100 px-2 py-0.5 rounded-md border border-slate-200 mr-2">Ctrl + Enter</span>
              保存修改 / 发送
            </div>
            <div className="text-xs text-slate-600">
              <span className="font-mono bg-slate-100 px-2 py-0.5 rounded-md border border-slate-200 mr-2">Esc</span>
              退出全屏 / 关闭弹窗
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
