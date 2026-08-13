import { useEffect, useRef, useState } from 'react';
import { Upload, FileText, Briefcase, CheckCircle2, Mic, FileUp, ClipboardPaste, History } from 'lucide-react';
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
        const usable = rs.filter((resume) => resume.has_text || resume.parse_status === 'ready');
        const selected = prefill
          ? usable.find((resume) => resume.id === prefill.resume_id)
          : (usable.find((resume) => resume.is_default) ?? usable[0]);
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
      .catch(() => { /* non-fatal — just hide the picker */ })
      .finally(() => { if (alive) setLoadingResumes(false); });
    return () => { alive = false; };
  }, [onPrefillApplied, prefill]);

  useEffect(() => {
    try {
      localStorage.setItem(VOICE_PREF_KEY, ttsVoice);
    } catch {
      // The interview still works when preference persistence is unavailable.
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
      // Saves a NEW personal resume entity (parsed into sections server-side);
      // its id is what the mock uses as resume context.
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
        // Two-active-resume limit hit — guide the user to pick an existing one.
        toast.error('已有两份简历，请从“选已有”中选择，或到“资料 > 资料库”管理');
        setResumeMode('existing');
      } else if ((e as Error)?.message?.includes('解析')) {
        toast.error('简历处理未完成，请到“资料 > 资料库”查看或替换');
        setResumeMode('existing');
      } else {
        toast.error('简历上传失败');
      }
    }
  };

  const onJd = async (f: File) => {
    // Mock-interview JD is single-use and must NOT join the personal library.
    // We send it to a stateless parse endpoint that returns text only.
    setJdDocument({ filename: f.name, parsing: true });
    try {
      const { text } = await parseJdForMock(f);
      if (!text.trim()) {
        setJdDocument(EMPTY_JD);
        toast.error('JD 解析为空，请换一份或粘贴文本');
        return;
      }
      setJdText(text);
      setJdMode('paste'); // surface the parsed text so the user can review/edit
      setJdDocument({ filename: f.name, parsing: false });
      toast.success(`JD 已解析（${text.length} 字符）· 仅用于本次模拟`);
    } catch {
      setJdDocument(EMPTY_JD);
      toast.error('JD 解析失败');
    }
  };

  // JD always reduces to plain text — either the user pasted it directly,
  // or parseJdForMock returned text from their uploaded file.
  const jdReady = jdText.trim().length >= 20;
  const ready = resume.id !== null && !resume.loading && jdReady;

  return (
    <div className="h-full flex items-center justify-center px-4 md:px-6 py-8 overflow-y-auto">
      <div className="max-w-[720px] w-full mx-auto flex flex-col items-center">
        {/* Header: clean, single hierarchy — title + subtitle, both centered. */}
        <header className="mb-9 text-center">
          <h2 className="text-[26px] font-semibold text-stone-800 leading-tight">
            开始之前，先准备两份材料
          </h2>
          <p className="text-stone-500 text-[15px] mt-2.5 leading-relaxed">
            上传简历和岗位 JD 后，AI 面试官会根据你的背景定制问题。
          </p>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 w-full">
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

        <div className="w-full mt-8 space-y-4">
          <PrefGroup
            label="面试官风格"
            options={STYLE_OPTIONS}
            value={style}
            onChange={setStyle}
          />
          <PrefGroup
            label="预计题量"
            options={LENGTH_OPTIONS}
            value={targetQuestionCount}
            onChange={setTargetQuestionCount}
            columns={3}
          />
          <p className="px-1 text-[12px] leading-relaxed text-stone-500">
            预计题量只用于控制面试节奏，实际题数可能因回答和追问有所变化。
          </p>
          <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-[0_2px_10px_rgba(15,23,42,0.04)]">
            <label className="text-[16px] font-semibold text-stone-800">关联岗位机会（可选）</label>
            <p className="mt-1 text-[12px] text-stone-500">选择后，本次模拟面试及后续复盘会关联到该求职进展。</p>
            <div className="mt-3">
              <JobOpportunitySelect
                value={jobOpportunityId}
                onChange={setJobOpportunityId}
                ariaLabel="模拟面试关联岗位"
                emptyLabel="不关联岗位"
              />
            </div>
          </div>
          <div className="bg-white border border-stone-200 rounded-2xl p-5 shadow-[0_2px_10px_rgba(15,23,42,0.04)]">
            <label htmlFor="tts-voice" className="text-[16px] font-semibold text-stone-800">
              面试官音色
            </label>
            <select
              id="tts-voice"
              value={ttsVoice}
              onChange={(event) => setTtsVoice(event.target.value as TtsVoice)}
              className="mt-3 w-full px-3 py-2.5 bg-white border border-stone-300 rounded-lg text-[14px] text-stone-800 outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
            >
              {VOICE_OPTIONS.map((option) => (
                <option key={option.id} value={option.id}>{option.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-9 flex justify-center">
          <Btn
            size="lg"
            icon={ready ? <Mic size={16} /> : <Upload size={16} />}
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
          >
            {ready ? '开始模拟面试' : '请先完成上传'}
          </Btn>
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
      style={{ minHeight: 210 }}
      className={[
        'p-5 bg-white rounded-2xl transition-all border-2 border-dashed shadow-[0_2px_10px_rgba(15,23,42,0.04)] flex flex-col',
        done ? 'border-success-500' : 'border-stone-300 hover:border-primary-300',
      ].join(' ')}
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

      <div className="flex items-center gap-3 mb-3">
        <div
          className={[
            'w-11 h-11 rounded-xl flex items-center justify-center shrink-0',
            done ? 'bg-success-50 text-success-700' : 'bg-primary-50 text-primary-600',
          ].join(' ')}
        >
          {state.loading ? <Spinner size={18} /> : done ? <CheckCircle2 size={20} /> : <FileText size={20} />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[16px] font-semibold text-stone-800 flex items-center gap-1.5 leading-tight">
            上传简历
            <span className="text-[11px] text-danger-500">*</span>
          </div>
          <div className="text-[12px] text-stone-500 mt-0.5">用于个性化提问</div>
        </div>
      </div>

      {/* Mode toggle: existing vs new upload */}
      {hasStored && (
        <div className="inline-flex p-0.5 bg-primary-50 border border-primary-100 rounded-lg mb-2.5 text-[13px]">
          <button
            type="button"
            onClick={() => setMode('existing')}
            className={[
              'inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md transition-colors',
              mode === 'existing'
                ? 'bg-primary-500 text-white font-medium shadow-sm'
                : 'text-primary-700 hover:bg-primary-100',
            ].join(' ')}
          >
            <History size={12} />
            选已有 ({storedResumes.length})
          </button>
          <button
            type="button"
            onClick={() => setMode('upload')}
            className={[
              'inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md transition-colors',
              mode === 'upload'
                ? 'bg-primary-500 text-white font-medium shadow-sm'
                : 'text-primary-700 hover:bg-primary-100',
            ].join(' ')}
          >
            <FileUp size={12} />
            上传新文件
          </button>
        </div>
      )}

      {/* Content area — fixed height so switching mode doesn't make the
        * card jump. Vertical scroll if content exceeds the area. */}
      <div className="flex-1 flex flex-col">
        {mode === 'existing' && hasStored ? (
          <div className="flex flex-col gap-2">
            <select
              value={state.id ?? ''}
              onChange={(e) => {
                const r = storedResumes.find((x) => x.id === e.target.value);
                if (r) onPickExisting(r);
              }}
              className="w-full px-3 py-2.5 bg-white border border-stone-300 rounded-lg text-[14px] text-stone-800 outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
            >
              <option value="">— 选一份简历 —</option>
              {storedResumes.map((r) => (
                <option
                  key={r.id}
                  value={r.id}
                  disabled={!r.has_text && r.parse_status !== 'ready'}
                >
                  {r.title}{r.is_default ? '（默认）' : ''}
                  {!r.has_text && r.parse_status !== 'ready'
                    ? r.parse_status === 'failed' ? '（解析失败）' : '（解析中）'
                    : ''}
                  {' · '}{(r.created_at || '').slice(0, 10)}
                </option>
              ))}
            </select>
            {done && (
              <div className="text-[12px] text-success-700 truncate">
                ✓ 当前：{state.filename}
              </div>
            )}
          </div>
        ) : (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className={[
              'w-full text-left px-3 py-2.5 rounded-lg transition-colors text-[14px]',
              done
                ? 'bg-success-50 text-success-700 hover:bg-success-100'
                : 'bg-primary-50 text-primary-700 hover:bg-primary-100',
            ].join(' ')}
          >
            {done ? (
              <span className="truncate inline-block max-w-full">
                {state.filename || '已上传'} · 点击替换
              </span>
            ) : loadingResumes ? (
              <span className="inline-flex items-center gap-1.5">
                <Spinner size={12} />
                加载已有简历…
              </span>
            ) : (
              <span className="flex items-center gap-2 leading-tight">
                <Upload size={14} className="shrink-0" />
                <span className="flex flex-col">
                  <span className="text-[14px]">点击选择文件</span>
                  <span className="text-[11px] text-primary-500/70 font-mono mt-0.5">
                    PDF · DOCX · TXT · MD
                  </span>
                </span>
              </span>
            )}
          </button>
        )}
      </div>
    </div>
  );
}

function PrefGroup<T extends string | number>({
  label,
  options,
  value,
  onChange,
  columns = 2,
}: {
  label: string;
  options: Array<{ id: T; label: string; desc: string }>;
  value: T;
  onChange: (v: T) => void;
  columns?: 2 | 3;
}) {
  return (
    <div className="bg-white border border-stone-200 rounded-2xl p-5 shadow-[0_2px_10px_rgba(15,23,42,0.04)]">
      <div className="text-[16px] font-semibold text-stone-800 mb-3.5">{label}</div>
      <div className={`grid gap-2.5 ${columns === 3 ? 'grid-cols-1 sm:grid-cols-3' : 'grid-cols-2'}`}>
        {options.map((opt) => {
          const active = opt.id === value;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => onChange(opt.id)}
              className={[
                'text-left px-3.5 py-2.5 rounded-xl border transition-colors',
                active
                  ? 'border-primary-300 bg-primary-50'
                  : 'border-stone-200 hover:border-stone-300 hover:bg-stone-50',
              ].join(' ')}
            >
              <div className="text-[14px] font-medium text-stone-800 flex items-center gap-2 leading-tight">
                <span
                  className={[
                    'w-3 h-3 rounded-full border shrink-0',
                    active ? 'border-primary-500 bg-primary-500' : 'border-stone-300',
                  ].join(' ')}
                />
                {opt.label}
              </div>
              <div className="text-[12px] text-stone-500 mt-1 ml-5 leading-snug">{opt.desc}</div>
            </button>
          );
        })}
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
  const doneText = text.trim().length >= 20;
  const doneUpload = state.filename !== '' && doneText;
  const done = mode === 'upload' ? doneUpload : doneText;
  return (
    <div
      style={{ minHeight: 210 }}
      className={[
        'p-5 bg-white rounded-2xl transition-all border-2 border-dashed shadow-[0_2px_10px_rgba(15,23,42,0.04)] flex flex-col',
        done ? 'border-success-500' : 'border-stone-300 hover:border-primary-300',
      ].join(' ')}
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
      <div className="flex items-center gap-3 mb-3">
        <div
          className={[
            'w-11 h-11 rounded-xl flex items-center justify-center shrink-0',
            done ? 'bg-success-50 text-success-700' : 'bg-primary-50 text-primary-600',
          ].join(' ')}
        >
          {state.parsing ? <Spinner size={18} /> : done ? <CheckCircle2 size={20} /> : <Briefcase size={20} />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[16px] font-semibold text-stone-800 flex items-center gap-1.5 leading-tight">
            上传岗位 JD
            <span className="text-[11px] text-danger-500">*</span>
          </div>
          <div className="text-[12px] text-stone-500 mt-0.5">用于定位提问方向</div>
        </div>
      </div>

      {/* Mode toggle: upload file OR paste text */}
      <div className="inline-flex p-0.5 bg-primary-50 border border-primary-100 rounded-lg mb-2.5 text-[13px]">
        <button
          type="button"
          onClick={() => setMode('upload')}
          className={[
            'inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md transition-colors',
            mode === 'upload'
              ? 'bg-primary-500 text-white font-medium shadow-sm'
              : 'text-primary-700 hover:bg-primary-100',
          ].join(' ')}
        >
          <FileUp size={12} />
          上传文件
        </button>
        <button
          type="button"
          onClick={() => setMode('paste')}
          className={[
            'inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md transition-colors',
            mode === 'paste'
              ? 'bg-primary-500 text-white font-medium shadow-sm'
              : 'text-primary-700 hover:bg-primary-100',
          ].join(' ')}
        >
          <ClipboardPaste size={12} />
          粘贴文本
        </button>
      </div>

      <div className="flex-1 flex flex-col">
      {mode === 'upload' ? (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className={[
            'w-full text-left px-3 py-2.5 rounded-lg transition-colors text-[14px]',
            doneUpload
              ? 'bg-success-50 text-success-700 hover:bg-success-100'
              : 'bg-primary-50 text-primary-700 hover:bg-primary-100',
          ].join(' ')}
        >
          {doneUpload ? (
            <span className="truncate inline-block max-w-full">
              {state.filename || '已上传'} · 点击替换
            </span>
          ) : (
            <span className="flex items-center gap-2 leading-tight">
              <Upload size={14} className="shrink-0" />
              <span className="flex flex-col">
                <span className="text-[14px]">点击选择文件</span>
                <span className="text-[11px] text-primary-500/70 font-mono mt-0.5">
                  PDF · DOCX · TXT · MD
                </span>
              </span>
            </span>
          )}
        </button>
      ) : (
        <>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="把 JD 全文粘贴到这里…（≥ 20 字才算有效）"
            rows={3}
            className="w-full px-3 py-2 bg-white border border-stone-300 rounded-lg text-[13px] text-stone-700 outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100 resize-y leading-[1.55]"
          />
          <div className="text-[12px] text-stone-500 mt-1 flex justify-between">
            <span className={doneText ? 'text-success-700 font-medium' : ''}>
              {doneText ? '✓ 已就绪' : `当前 ${text.trim().length}/20 字`}
            </span>
            {text && (
              <button type="button" onClick={() => setText('')} className="hover:text-danger-500">
                清空
              </button>
            )}
          </div>
        </>
      )}
      </div>
    </div>
  );
}
