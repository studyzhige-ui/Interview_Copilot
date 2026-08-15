import { useEffect, useRef, useState } from 'react';
import {
  FileText,
  Briefcase,
  CheckCircle2,
  Mic,
  FileUp,
  Volume2,
  Radio,
  ArrowRight,
  UserCheck,
} from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import {
  createResumeFromFile,
  listResumes,
  waitForResumeUsable,
  type PersonalResume,
} from '@/api/resumes';
import { parseJdForMock } from '@/api/mock';
import type { MockClientUiResult, MockPrefillPayload } from '@/types/clientAction';
import { JobOpportunitySelect } from '@/pages/career/JobOpportunitySelect';

export type InterviewerStyle = 'friendly' | 'professional' | 'rigorous' | 'pressure';
export type TargetQuestionCount = 15 | 20 | 30;
export type TtsVoice =
  | 'zh-CN-YunxiNeural'
  | 'zh-CN-XiaoxiaoNeural'
  | 'zh-CN-YunjianNeural'
  | 'zh-CN-XiaoyiNeural';

interface Props {
  onReady: (payload: {
    resume_id: string;
    jd_text: string;
    interviewer_style: InterviewerStyle;
    tts_voice: TtsVoice;
    target_question_count: TargetQuestionCount;
    job_opportunity_id?: string;
  }) => void;
  starting: boolean;
  prefill?: MockPrefillPayload;
  onPrefillApplied?: (result: MockClientUiResult) => void;
}

const STYLE_OPTIONS: Array<{ id: InterviewerStyle; label: string; desc: string }> = [
  { id: 'friendly', label: '友善引导型', desc: '给思考时间多、肯定为主、温和追问' },
  { id: 'professional', label: '专业平稳型', desc: '标准节奏、就事论事（默认）' },
  { id: 'rigorous', label: '严谨挑剔型', desc: '追问尖锐、追究边界 case' },
  { id: 'pressure', label: '高压面试官', desc: '连珠追问、质疑回答、压力面' },
];

const VOICE_PREF_KEY = 'mock.ttsVoice';
const VOICE_OPTIONS: Array<{ id: TtsVoice; label: string }> = [
  { id: 'zh-CN-YunxiNeural', label: '云希 · 沉稳男声' },
  { id: 'zh-CN-XiaoxiaoNeural', label: '晓晓 · 自然女声' },
  { id: 'zh-CN-YunjianNeural', label: '云健 · 专业男声' },
  { id: 'zh-CN-XiaoyiNeural', label: '晓伊 · 温和女声' },
];

const LENGTH_OPTIONS: Array<{
  id: TargetQuestionCount;
  label: string;
  desc: string;
}> = [
  { id: 15, label: '快速面试', desc: '约 15 题' },
  { id: 20, label: '标准面试', desc: '约 20 题 · 默认' },
  { id: 30, label: '深入面试', desc: '约 30 题' },
];

export function loadPreferredVoice(): TtsVoice {
  try {
    const stored = localStorage.getItem(VOICE_PREF_KEY);
    const option = VOICE_OPTIONS.find((item) => item.id === stored);
    if (option) return option.id;
  } catch {
    // Storage may be unavailable in privacy-restricted browsers.
  }
  return 'zh-CN-YunxiNeural';
}

interface ResumeState {
  filename: string;
  id: string | null;
  loading: boolean;
}

interface JdState {
  filename: string;
  parsing: boolean;
}

const EMPTY_RESUME: ResumeState = { filename: '', id: null, loading: false };
const EMPTY_JD: JdState = { filename: '', parsing: false };

export function MockSetup({ onReady, starting, prefill, onPrefillApplied }: Props) {
  const [resume, setResume] = useState<ResumeState>(EMPTY_RESUME);
  const [jdDocument, setJdDocument] = useState<JdState>(EMPTY_JD);
  const [resumeMode, setResumeMode] = useState<'upload' | 'existing'>('existing');
  const [storedResumes, setStoredResumes] = useState<PersonalResume[]>([]);
  const [loadingResumes, setLoadingResumes] = useState(true);
  const [jdMode, setJdMode] = useState<'upload' | 'paste'>(prefill ? 'paste' : 'upload');
  const [jdText, setJdText] = useState(prefill?.jd_text ?? '');
  const [style, setStyle] = useState<InterviewerStyle>(
    prefill?.interviewer_style ?? 'professional',
  );
  const [ttsVoice, setTtsVoice] = useState<TtsVoice>(loadPreferredVoice);
  const [targetQuestionCount, setTargetQuestionCount] =
    useState<TargetQuestionCount>(prefill?.target_question_count ?? 20);
  const [jobOpportunityId, setJobOpportunityId] = useState(prefill?.job_opportunity_id ?? '');
  const resumeRef = useRef<HTMLInputElement | null>(null);
  const jdRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let alive = true;
    listResumes()
      .then((rs) => {
        if (!alive) return;
        setStoredResumes(rs);
        const usable = rs.filter((r) => r.has_text || r.parse_status === 'ready');
        const selected = prefill
          ? usable.find((r) => r.id === prefill.resume_id)
          : (usable.find((r) => r.is_default) ?? usable[0]);
        setResumeMode(selected ? 'existing' : 'upload');
        if (selected) {
          setResume({ filename: selected.title, id: selected.id, loading: false });
          if (prefill) onPrefillApplied?.({ outcome: 'acknowledged' });
        } else if (prefill) {
          onPrefillApplied?.({
            outcome: 'failed',
            reason: '预填引用的简历在当前客户端已不可用',
          });
        }
      })
      .catch(() => { /* non-fatal */ })
      .finally(() => { if (alive) setLoadingResumes(false); });
    return () => { alive = false; };
  }, [onPrefillApplied, prefill]);

  useEffect(() => {
    try {
      localStorage.setItem(VOICE_PREF_KEY, ttsVoice);
    } catch {
      // ignore
    }
  }, [ttsVoice]);

  const pickExistingResume = (r: PersonalResume) => {
    if (!r.has_text && r.parse_status !== 'ready') {
      toast.error(r.parse_status === 'failed' ? '这份简历解析失败，请替换后重试' : '这份简历仍在解析');
      return;
    }
    setResume({ filename: r.title, id: r.id, loading: false });
  };

  const onResume = async (f: File) => {
    setResume({ filename: f.name, id: null, loading: true });
    try {
      const r = await createResumeFromFile(f);
      setStoredResumes((current) => [r, ...current.filter((item) => item.id !== r.id)]);
      const usable = await waitForResumeUsable(r.id);
      setStoredResumes((current) => [usable, ...current.filter((item) => item.id !== usable.id)]);
      setResume({ filename: usable.title, id: usable.id, loading: false });
      toast.success('简历已解析，可以开始面试');
    } catch (e) {
      setResume(EMPTY_RESUME);
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 409) {
        toast.error('已有两份简历，请从“选已有”中选择');
        setResumeMode('existing');
      } else {
        toast.error('简历上传失败');
      }
    }
  };

  const onJd = async (f: File) => {
    setJdDocument({ filename: f.name, parsing: true });
    try {
      const { text } = await parseJdForMock(f);
      if (!text.trim()) {
        setJdDocument(EMPTY_JD);
        toast.error('JD 解析为空，请换一份或粘贴文本');
        return;
      }
      setJdText(text);
      setJdMode('paste');
      setJdDocument({ filename: f.name, parsing: false });
      toast.success(`JD 已解析（${text.length} 字符）`);
    } catch {
      setJdDocument(EMPTY_JD);
      toast.error('JD 解析失败');
    }
  };

  const jdReady = jdText.trim().length >= 20;
  const ready = resume.id !== null && !resume.loading && jdReady;

  return (
    <div className="h-full overflow-y-auto p-4 md:p-8 flex items-center justify-center">
      <div className="max-w-4xl w-full mx-auto space-y-6 animate-in fade-in duration-300">
        {/* Studio Hero Banner */}
        <div className="text-center space-y-2.5">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-blue-50 border border-blue-100 text-blue-700 text-xs font-semibold shadow-xs">
            <Radio size={14} className="text-blue-600 animate-pulse" />
            <span>AI 模拟面试实战舱</span>
          </div>
          <h2 className="text-2xl md:text-3xl font-bold text-slate-900 tracking-tight">
            模拟面试实战 · 实时对练
          </h2>
          <p className="text-sm md:text-base text-slate-600 max-w-xl mx-auto leading-relaxed">
            上传个人简历与目标岗位 JD，AI 考官将以标准大厂语调向你提问，支持实时双向语音对练。
          </p>
        </div>

        {/* 1. Unified Materials Capsule (Split Card: Resume + JD) with Readable Fonts */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ResumeCard
            mode={resumeMode}
            setMode={setResumeMode}
            state={resume}
            storedResumes={storedResumes}
            loadingResumes={loadingResumes}
            inputRef={resumeRef}
            onPickFile={onResume}
            onPickExisting={pickExistingResume}
          />
          <JdCard
            mode={jdMode}
            setMode={setJdMode}
            state={jdDocument}
            text={jdText}
            setText={setJdText}
            inputRef={jdRef}
            onPick={onJd}
          />
        </div>

        {/* 2. Cohesive Interviewer Preferences Panel */}
        <div className="p-6 md:p-8 rounded-3xl bg-white/90 backdrop-blur-md border border-slate-200/90 shadow-sm space-y-6">
          {/* Style Options */}
          <div className="space-y-3">
            <div className="text-xs font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
              <UserCheck size={15} className="text-blue-600" />
              <span>面试官风格偏好</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {STYLE_OPTIONS.map((opt) => {
                const active = style === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setStyle(opt.id)}
                    className={`p-3.5 rounded-2xl border text-left transition-all cursor-pointer ${
                      active
                        ? 'bg-blue-50/80 border-blue-300 text-blue-900 shadow-2xs ring-1 ring-blue-200'
                        : 'bg-slate-50/50 border-slate-200/80 text-slate-700 hover:bg-slate-100/70'
                    }`}
                  >
                    <div className="text-sm font-bold">{opt.label}</div>
                    <div className="text-xs text-slate-500 mt-1 leading-snug">{opt.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Length & Question Count */}
          <div className="space-y-3">
            <div className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              预计面试题量
            </div>
            <div className="grid grid-cols-3 gap-3">
              {LENGTH_OPTIONS.map((opt) => {
                const active = targetQuestionCount === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setTargetQuestionCount(opt.id)}
                    className={`p-3 rounded-2xl border text-center transition-all cursor-pointer ${
                      active
                        ? 'bg-blue-50/80 border-blue-300 text-blue-900 shadow-2xs ring-1 ring-blue-200 font-bold'
                        : 'bg-slate-50/50 border-slate-200/80 text-slate-700 hover:bg-slate-100/70 text-sm font-medium'
                    }`}
                  >
                    <div className="text-sm font-bold">{opt.label}</div>
                    <div className="text-xs text-slate-500 mt-0.5">{opt.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Inline dropdowns: Voice + Opportunity Link */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-3 border-t border-slate-100">
            <div className="space-y-1.5">
              <label htmlFor="tts-voice" className="text-sm font-semibold text-slate-700 flex items-center gap-1.5">
                <Volume2 size={15} className="text-purple-600" />
                <span>考官播报音色</span>
              </label>
              <select
                id="tts-voice"
                value={ttsVoice}
                onChange={(e) => setTtsVoice(e.target.value as TtsVoice)}
                className="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200/80 rounded-2xl text-sm font-semibold text-slate-800 outline-none focus:border-blue-400 cursor-pointer"
              >
                {VOICE_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-semibold text-slate-700 flex items-center gap-1.5">
                <Briefcase size={15} className="text-blue-600" />
                <span>关联求职机会（可选）</span>
              </label>
              <JobOpportunitySelect
                value={jobOpportunityId}
                onChange={setJobOpportunityId}
                ariaLabel="模拟面试关联岗位"
                emptyLabel="不关联岗位"
              />
            </div>
          </div>
        </div>

        {/* Start Button Hero with comfortable sizing */}
        <div className="flex flex-col items-center justify-center pt-2">
          <Btn
            kind="sparkle"
            size="lg"
            disabled={!ready || starting}
            loading={starting}
            onClick={() =>
              onReady({
                resume_id: resume.id!,
                jd_text: jdText.trim(),
                interviewer_style: style,
                tts_voice: ttsVoice,
                target_question_count: targetQuestionCount,
                job_opportunity_id: jobOpportunityId || undefined,
              })
            }
            className="px-10 py-3.5 text-base font-semibold shadow-lg shadow-purple-500/20"
          >
            <Mic size={18} />
            <span>{ready ? '开始模拟面试' : '请先完成上传'}</span>
            <ArrowRight size={16} />
          </Btn>
          <p className="text-xs text-slate-400 mt-2.5">
            * 准备完成后点击即可进入全真实时模拟面试
          </p>
        </div>
      </div>
    </div>
  );
}

function ResumeCard({
  mode,
  setMode,
  state,
  storedResumes,
  loadingResumes,
  inputRef,
  onPickFile,
  onPickExisting,
}: {
  mode: 'upload' | 'existing';
  setMode: (m: 'upload' | 'existing') => void;
  state: ResumeState;
  storedResumes: PersonalResume[];
  loadingResumes: boolean;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onPickFile: (f: File) => void;
  onPickExisting: (r: PersonalResume) => void;
}) {
  const done = state.id !== null;
  const hasStored = storedResumes.length > 0;

  return (
    <div
      className={`p-5 md:p-6 bg-white rounded-3xl border-2 transition-all shadow-xs flex flex-col justify-between ${
        done ? 'border-emerald-300/80 bg-emerald-50/15' : 'border-slate-200/90 hover:border-blue-300'
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.doc,.docx,.txt,.md"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onPickFile(f);
          e.target.value = '';
        }}
      />

      <div>
        <div className="flex items-center justify-between mb-3.5">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center">
              <FileText size={18} />
            </div>
            <div>
              <div className="text-sm font-bold text-slate-900">个人简历 *</div>
              <div className="text-xs text-slate-500">用于提炼经历与个性化提问</div>
            </div>
          </div>

          {hasStored && (
            <div className="flex p-0.5 bg-slate-100 rounded-xl">
              <button
                type="button"
                onClick={() => setMode('existing')}
                className={`px-3 py-1 text-xs font-semibold rounded-lg transition-all ${
                  mode === 'existing'
                    ? 'bg-white text-blue-700 shadow-2xs'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                选已有 ({storedResumes.length})
              </button>
              <button
                type="button"
                onClick={() => setMode('upload')}
                className={`px-3 py-1 text-xs font-semibold rounded-lg transition-all ${
                  mode === 'upload'
                    ? 'bg-white text-blue-700 shadow-2xs'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                重新上传
              </button>
            </div>
          )}
        </div>

        {mode === 'existing' && hasStored ? (
          <div className="space-y-2 max-h-40 overflow-y-auto pt-1">
            {loadingResumes ? (
              <div className="p-4 text-center text-slate-400 text-sm">
                <Spinner size={16} /> 载入简历中…
              </div>
            ) : (
              storedResumes.map((r) => {
                const isSelected = state.id === r.id;
                return (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => onPickExisting(r)}
                    className={`w-full p-3 rounded-2xl border text-left flex items-center justify-between transition-all cursor-pointer ${
                      isSelected
                        ? 'border-emerald-300 bg-emerald-50 text-emerald-900 font-semibold'
                        : 'border-slate-100 bg-slate-50/50 hover:bg-slate-100/70 text-slate-700'
                    }`}
                  >
                    <span className="text-sm truncate">{r.title}</span>
                    {isSelected && <CheckCircle2 size={16} className="text-emerald-600 shrink-0" />}
                  </button>
                );
              })
            )}
          </div>
        ) : (
          <div
            onClick={() => inputRef.current?.click()}
            className="p-6 border-2 border-dashed border-slate-200 hover:border-blue-400 rounded-2xl flex flex-col items-center justify-center cursor-pointer transition-colors bg-slate-50/50 hover:bg-blue-50/30 text-center"
          >
            {state.loading ? (
              <div className="flex items-center gap-2 text-sm text-blue-600 font-medium">
                <Spinner size={16} /> 正在智能解析简历…
              </div>
            ) : done ? (
              <div className="text-sm font-semibold text-emerald-700 flex items-center gap-1.5">
                <CheckCircle2 size={16} />
                <span>已就绪：{state.filename}</span>
              </div>
            ) : (
              <>
                <FileUp size={24} className="text-slate-400 mb-1.5" />
                <span className="text-sm font-semibold text-slate-700">点击选择简历文件</span>
                <span className="text-xs text-slate-400 mt-0.5">支持 PDF、DOCX、TXT、MD 格式</span>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function JdCard({
  mode,
  setMode,
  state,
  text,
  setText,
  inputRef,
  onPick,
}: {
  mode: 'upload' | 'paste';
  setMode: (m: 'upload' | 'paste') => void;
  state: JdState;
  text: string;
  setText: (t: string) => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onPick: (f: File) => void;
}) {
  const ready = text.trim().length >= 20;

  return (
    <div
      className={`p-5 md:p-6 bg-white rounded-3xl border-2 transition-all shadow-xs flex flex-col justify-between ${
        ready ? 'border-emerald-300/80 bg-emerald-50/15' : 'border-slate-200/90 hover:border-blue-300'
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.doc,.docx,.txt,.md"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onPick(f);
          e.target.value = '';
        }}
      />

      <div>
        <div className="flex items-center justify-between mb-3.5">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-2xl bg-purple-50 text-purple-600 flex items-center justify-center">
              <Briefcase size={18} />
            </div>
            <div>
              <div className="text-sm font-bold text-slate-900">目标岗位 JD *</div>
              <div className="text-xs text-slate-500">用于定位考题难度与技术方向</div>
            </div>
          </div>

          <div className="flex p-0.5 bg-slate-100 rounded-xl">
            <button
              type="button"
              onClick={() => setMode('upload')}
              className={`px-3 py-1 text-xs font-semibold rounded-lg transition-all ${
                mode === 'upload'
                  ? 'bg-white text-blue-700 shadow-2xs'
                  : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              上传文件
            </button>
            <button
              type="button"
              onClick={() => setMode('paste')}
              className={`px-3 py-1 text-xs font-semibold rounded-lg transition-all ${
                mode === 'paste'
                  ? 'bg-white text-blue-700 shadow-2xs'
                  : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              粘贴文本
            </button>
          </div>
        </div>

        {mode === 'paste' ? (
          <div className="pt-1">
            <textarea
              rows={4}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="把 JD 全文粘贴到这里（如岗位职责、任职要求等，至少20字）..."
              className="w-full p-3.5 bg-slate-50 border border-slate-200/80 rounded-2xl text-sm text-slate-800 placeholder-slate-400 outline-none focus:border-blue-400 focus:bg-white transition-all leading-relaxed resize-none"
            />
            {ready && (
              <div className="text-xs text-emerald-700 font-semibold mt-1.5 flex items-center gap-1.5">
                <CheckCircle2 size={14} />
                <span>JD 内容已就绪 ({text.trim().length} 字)</span>
              </div>
            )}
          </div>
        ) : (
          <div
            onClick={() => inputRef.current?.click()}
            className="p-6 border-2 border-dashed border-slate-200 hover:border-blue-400 rounded-2xl flex flex-col items-center justify-center cursor-pointer transition-colors bg-slate-50/50 hover:bg-blue-50/30 text-center"
          >
            {state.parsing ? (
              <div className="flex items-center gap-2 text-sm text-blue-600 font-medium">
                <Spinner size={16} /> 正在智能解析 JD...
              </div>
            ) : ready ? (
              <div className="text-sm font-semibold text-emerald-700 flex items-center gap-1.5">
                <CheckCircle2 size={16} />
                <span>已就绪：{state.filename || `${text.slice(0, 15)}...`}</span>
              </div>
            ) : (
              <>
                <FileUp size={24} className="text-slate-400 mb-1.5" />
                <span className="text-sm font-semibold text-slate-700">点击选择 JD 文件</span>
                <span className="text-xs text-slate-400 mt-0.5">支持 PDF、DOCX、TXT、MD 格式</span>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
