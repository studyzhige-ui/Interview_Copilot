import { useState, useRef, useEffect, KeyboardEvent, ReactNode } from 'react';
import { ArrowUp, Sparkles, Paperclip, Mic, ChevronDown, Check } from 'lucide-react';

export interface GeminiModelOption {
  id: string;
  name: string;
  badge?: string;
}

interface GeminiPillInputProps {
  placeholder?: string;
  value: string;
  onChange: (val: string) => void;
  onSubmit: () => void;
  loading?: boolean;
  disabled?: boolean;
  models?: GeminiModelOption[];
  selectedModel?: string;
  onSelectModel?: (id: string) => void;
  onAttachFile?: () => void;
  onVoiceInput?: () => void;
  isRecording?: boolean;
  customActions?: ReactNode;
  className?: string;
}

const DEFAULT_MODELS: GeminiModelOption[] = [
  { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash', badge: '极速' },
  { id: 'gemini-2.5-pro', name: 'Gemini 2.5 Pro', badge: '深度思考' },
  { id: 'deepseek-r1', name: 'DeepSeek R1', badge: '推理' },
];

export function GeminiPillInput({
  placeholder = '输入任何求职疑问，或上传简历与岗位 JD...',
  value,
  onChange,
  onSubmit,
  loading = false,
  disabled = false,
  models = DEFAULT_MODELS,
  selectedModel,
  onSelectModel,
  onAttachFile,
  onVoiceInput,
  isRecording = false,
  customActions,
  className = '',
}: GeminiPillInputProps) {
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const activeModel = models.find((m) => m.id === selectedModel) ?? models[0];

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setModelDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Auto-grow textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [value]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!loading && !disabled && value.trim()) {
        onSubmit();
      }
    }
  };

  return (
    <div className={`relative w-full max-w-4xl mx-auto ${className}`}>
      {/* Floating pill container */}
      <div className="relative flex flex-col bg-white rounded-3xl border border-slate-200/90 shadow-lg shadow-slate-200/50 hover:border-slate-300 focus-within:border-blue-400 focus-within:shadow-xl focus-within:shadow-blue-500/5 transition-all duration-200">
        {/* Text Input Row */}
        <div className="flex items-start px-5 pt-3.5 pb-1 gap-3">
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            className="flex-1 max-h-44 resize-none bg-transparent text-slate-800 placeholder-slate-400 text-sm md:text-[15px] leading-relaxed outline-none pt-1"
          />
        </div>

        {/* Action Controls Bottom Row */}
        <div className="flex items-center justify-between px-4 py-2.5 border-t border-slate-100/80">
          {/* Left Side: Model Selector + Attachments */}
          <div className="flex items-center gap-2">
            {models.length > 0 && onSelectModel && (
              <div className="relative" ref={dropdownRef}>
                <button
                  type="button"
                  onClick={() => setModelDropdownOpen((v) => !v)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-100 hover:bg-slate-200/80 text-slate-700 text-xs font-medium transition-colors"
                >
                  <Sparkles size={13} className="text-blue-600" />
                  <span>{activeModel?.name ?? '模型'}</span>
                  <ChevronDown size={12} className="text-slate-400" />
                </button>

                {modelDropdownOpen && (
                  <div className="absolute left-0 bottom-full mb-2 w-56 bg-white rounded-2xl shadow-xl border border-slate-200 p-1.5 z-50">
                    <div className="px-3 py-1.5 text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                      选择 AI 思考模型
                    </div>
                    {models.map((m) => (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => {
                          onSelectModel(m.id);
                          setModelDropdownOpen(false);
                        }}
                        className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors ${
                          m.id === activeModel?.id
                            ? 'bg-blue-50 text-blue-700 font-medium'
                            : 'text-slate-700 hover:bg-slate-50'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <span>{m.name}</span>
                          {m.badge && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-slate-100 text-slate-500">
                              {m.badge}
                            </span>
                          )}
                        </div>
                        {m.id === activeModel?.id && <Check size={14} className="text-blue-600" />}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {onAttachFile && (
              <button
                type="button"
                onClick={onAttachFile}
                title="添加附件或简历"
                className="p-1.5 rounded-full text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors"
              >
                <Paperclip size={16} />
              </button>
            )}

            {customActions}
          </div>

          {/* Right Side: Voice & Send */}
          <div className="flex items-center gap-2">
            {onVoiceInput && (
              <button
                type="button"
                onClick={onVoiceInput}
                title={isRecording ? '点击停止语音输入' : '按住或点击语音输入'}
                className={`p-2 rounded-full transition-all ${
                  isRecording
                    ? 'bg-red-500 text-white animate-pulse'
                    : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'
                }`}
              >
                <Mic size={16} />
              </button>
            )}

            <button
              type="button"
              onClick={onSubmit}
              disabled={disabled || loading || !value.trim()}
              aria-label="发送"
              className={`w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                value.trim() && !loading && !disabled
                  ? 'bg-blue-600 hover:bg-blue-700 text-white shadow-sm shadow-blue-500/30 active:scale-95'
                  : 'bg-slate-100 text-slate-400 cursor-not-allowed'
              }`}
            >
              {loading ? (
                <span className="w-3.5 h-3.5 border-2 border-slate-400 border-r-transparent rounded-full animate-spin" />
              ) : (
                <ArrowUp size={16} strokeWidth={2.5} />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
