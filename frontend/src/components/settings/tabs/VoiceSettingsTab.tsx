import { useState } from 'react';
import { Volume2, Play, Square, Mic } from 'lucide-react';
import { toast } from '@/store/uiStore';
import { useTts } from '@/hooks/useTts';

export type TtsVoice =
  | 'zh-CN-YunxiNeural'
  | 'zh-CN-XiaoxiaoNeural'
  | 'zh-CN-YunjianNeural'
  | 'zh-CN-XiaoyiNeural';

const VOICE_OPTIONS: Array<{ id: TtsVoice; label: string; desc: string; sample: string }> = [
  {
    id: 'zh-CN-YunxiNeural',
    label: '云希 · 沉稳专业男声',
    desc: '语调沉稳自然，适合大厂技术面、系统架构面（默认推荐）',
    sample: '你好，欢迎参加本次技术面试。请你先用两分钟时间做个自我介绍。',
  },
  {
    id: 'zh-CN-XiaoxiaoNeural',
    label: '晓晓 · 自然亲和女声',
    desc: '清晰明快，适合 HR 面试、行为面试与沟通能力考察',
    sample: '请举一个你在团队合作中解决冲突的具体例子，以及最终的结果是什么。',
  },
  {
    id: 'zh-CN-YunjianNeural',
    label: '云健 · 严肃专业男声',
    desc: '严谨平稳，适合严格代码 Review、压力面场景',
    sample: '请分析一下这个算法的时间与空间复杂度，是否有更优的边界处理方案？',
  },
  {
    id: 'zh-CN-XiaoyiNeural',
    label: '晓伊 · 温和知性女声',
    desc: '温和细腻，适合产品经理、业务复盘与综合素质面试',
    sample: '如果产品上线后核心指标出现波动，你会通过哪些维度进行归因分析？',
  },
];

const VOICE_PREF_KEY = 'mock.ttsVoice';

export function VoiceSettingsTab() {
  const [selectedVoice, setSelectedVoice] = useState<TtsVoice>(() => {
    try {
      const v = localStorage.getItem(VOICE_PREF_KEY) as TtsVoice;
      if (VOICE_OPTIONS.some((o) => o.id === v)) return v;
    } catch {
      // ignore
    }
    return 'zh-CN-YunxiNeural';
  });

  const [playingVoice, setPlayingVoice] = useState<TtsVoice | null>(null);
  const tts = useTts({ enabled: true, voice: selectedVoice });

  const handleSelect = (id: TtsVoice) => {
    setSelectedVoice(id);
    try {
      localStorage.setItem(VOICE_PREF_KEY, id);
      toast.success('面试官音色偏好已保存');
    } catch {
      // ignore
    }
  };

  const handlePlaySample = (voice: typeof VOICE_OPTIONS[0]) => {
    if (playingVoice === voice.id) {
      tts.stop();
      setPlayingVoice(null);
    } else {
      setPlayingVoice(voice.id);
      void tts.speak(voice.sample).then(() => {
        setPlayingVoice(null);
      });
    }
  };

  return (
    <div className="space-y-6 text-slate-800 animate-in fade-in duration-200">
      <div>
        <h3 className="text-lg font-bold text-slate-900 tracking-tight">语音与音色设置</h3>
        <p className="text-xs text-slate-500 mt-1">配置模拟面试官发音人音色、语音合成引擎及语速偏好。</p>
      </div>

      <div className="space-y-3">
        <div className="text-xs font-bold text-slate-500 uppercase tracking-wider">
          面试官发音人音色
        </div>

        <div className="grid grid-cols-1 gap-3">
          {VOICE_OPTIONS.map((v) => {
            const isSelected = selectedVoice === v.id;
            const isPlaying = playingVoice === v.id;

            return (
              <div
                key={v.id}
                onClick={() => handleSelect(v.id)}
                className={`p-4 rounded-2xl border transition-all duration-150 cursor-pointer flex items-center justify-between gap-4 ${
                  isSelected
                    ? 'border-blue-300 bg-blue-50/40 shadow-xs'
                    : 'border-slate-200/80 bg-white hover:border-slate-300'
                }`}
              >
                <div className="flex items-center gap-3.5 min-w-0">
                  <div
                    className={`w-10 h-10 rounded-2xl flex items-center justify-center shrink-0 ${
                      isSelected ? 'bg-blue-600 text-white shadow-xs' : 'bg-slate-100 text-slate-600'
                    }`}
                  >
                    <Volume2 size={18} />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-bold text-slate-800 flex items-center gap-2">
                      <span>{v.label}</span>
                      {isSelected && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 font-semibold">
                          当前使用
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5 truncate">{v.desc}</div>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handlePlaySample(v);
                    }}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border transition-all ${
                      isPlaying
                        ? 'bg-blue-600 border-blue-600 text-white'
                        : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    {isPlaying ? <Square size={12} fill="currentColor" /> : <Play size={12} fill="currentColor" />}
                    <span>{isPlaying ? '停止试听' : '试听'}</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="pt-4 border-t border-slate-100 flex items-center justify-between">
        <div className="space-y-0.5">
          <div className="text-sm font-semibold text-slate-800 flex items-center gap-1.5">
            <Mic size={15} className="text-emerald-600" />
            <span>实时语音打断与高敏拾音</span>
          </div>
          <div className="text-xs text-slate-500">模拟面试中开口说话时自动停止面试官播报</div>
        </div>
        <span className="text-xs font-semibold text-blue-600 bg-blue-50 px-3 py-1 rounded-full border border-blue-100">
          已开启
        </span>
      </div>
    </div>
  );
}
