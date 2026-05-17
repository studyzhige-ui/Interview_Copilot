import { useEffect, useRef, useState } from 'react';
import { Upload, FileText, Briefcase, CheckCircle2, Mic, FileUp, ClipboardPaste, History } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { listStoredResumes, uploadResume, type StoredResume } from '@/api/interview';
import { parseJdForMock } from '@/api/mock';

export type InterviewerStyle = 'friendly' | 'professional' | 'rigorous' | 'pressure';
export type VoiceMode = 'text' | 'voice' | 'hybrid';

interface Props {
  onReady: (payload: {
    resume_upload_id: string;
    jd_text: string;
    interviewer_style: InterviewerStyle;
    voice_mode: VoiceMode;
  }) => void;
  starting: boolean;
}

const STYLE_OPTIONS: Array<{ id: InterviewerStyle; label: string; desc: string }> = [
  { id: 'friendly', label: '友善引导型', desc: '给思考时间多、肯定为主、温和追问' },
  { id: 'professional', label: '专业平稳型', desc: '标准节奏、就事论事（默认）' },
  { id: 'rigorous', label: '严谨挑剔型', desc: '追问尖锐、追究边界 case' },
  { id: 'pressure', label: '高压面试官', desc: '连珠追问、质疑回答、压力面' },
];

type CardKey = 'resume' | 'jd';

interface CardState {
  filename: string;
  uploadId?: string;
  uploading?: boolean;
}

const empty: CardState = { filename: '' };

export function MockSetup({ onReady, starting }: Props) {
  const [cards, setCards] = useState<Record<CardKey, CardState>>({
    resume: { ...empty },
    jd: { ...empty },
  });
  const [resumeMode, setResumeMode] = useState<'upload' | 'existing'>('existing');
  const [storedResumes, setStoredResumes] = useState<StoredResume[]>([]);
  const [loadingResumes, setLoadingResumes] = useState(false);
  const [jdMode, setJdMode] = useState<'upload' | 'paste'>('upload');
  const [jdText, setJdText] = useState('');
  const [style, setStyle] = useState<InterviewerStyle>('professional');
  // Voice mode is no longer user-configurable on Setup — defaults to hybrid
  // (TTS for interviewer + free text/voice input). Users mute / unmute mid-
  // interview via the speaker button in MockLive header.
  const voiceMode: VoiceMode = 'hybrid';
  const resumeRef = useRef<HTMLInputElement | null>(null);
  const jdRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let alive = true;
    setLoadingResumes(true);
    listStoredResumes()
      .then((rs) => {
        if (!alive) return;
        setStoredResumes(rs);
        // Default to "existing" if user has previous resumes; otherwise "upload".
        setResumeMode(rs.length > 0 ? 'existing' : 'upload');
      })
      .catch(() => { /* non-fatal — just hide the picker */ })
      .finally(() => { if (alive) setLoadingResumes(false); });
    return () => { alive = false; };
  }, []);

  const pickExistingResume = (r: StoredResume) => {
    setCards((c) => ({
      ...c,
      resume: { filename: r.filename, uploadId: r.upload_id, uploading: false },
    }));
  };

  const update = (k: CardKey, patch: Partial<CardState>) =>
    setCards((c) => ({ ...c, [k]: { ...c[k], ...patch } }));

  const onResume = async (f: File) => {
    update('resume', { filename: f.name, uploading: true });
    try {
      const r = await uploadResume(f);
      update('resume', { uploadId: r.upload_id, uploading: false });
      toast.success('简历已上传');
    } catch {
      update('resume', empty);
      toast.error('简历上传失败');
    }
  };

  const onJd = async (f: File) => {
    // Mock-interview JD is single-use and must NOT join the personal library.
    // We send it to a stateless parse endpoint that returns text only.
    update('jd', { filename: f.name, uploading: true });
    try {
      const { text } = await parseJdForMock(f);
      if (!text.trim()) {
        update('jd', empty);
        toast.error('JD 解析为空，请换一份或粘贴文本');
        return;
      }
      setJdText(text);
      setJdMode('paste'); // surface the parsed text so the user can review/edit
      update('jd', { filename: f.name, uploadId: undefined, uploading: false });
      toast.success(`JD 已解析（${text.length} 字符）· 仅用于本次模拟`);
    } catch {
      update('jd', empty);
      toast.error('JD 解析失败');
    }
  };

  // JD always reduces to plain text — either the user pasted it directly,
  // or parseJdForMock returned text from their uploaded file.
  const jdReady = jdText.trim().length >= 20;
  const ready = !!cards.resume.uploadId && jdReady;

  return (
    <div className="h-full flex items-center justify-center px-6 py-8 overflow-y-auto">
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

        <div className="grid grid-cols-2 gap-6 w-full">
          <ResumeCard
            mode={resumeMode}
            setMode={setResumeMode}
            state={cards.resume}
            storedResumes={storedResumes}
            loadingResumes={loadingResumes}
            inputRef={resumeRef}
            onPickFile={onResume}
            onPickExisting={pickExistingResume}
          />
          <JdCard
            mode={jdMode}
            setMode={setJdMode}
            state={cards.jd}
            text={jdText}
            setText={setJdText}
            inputRef={jdRef}
            onPick={onJd}
          />
        </div>

        {/* Preferences: just interviewer style. Voice is always hybrid
            (TTS + free text/voice answer), mute toggle lives inside MockLive. */}
        <div className="w-full mt-8">
          <PrefGroup
            label="面试官风格"
            options={STYLE_OPTIONS}
            value={style}
            onChange={setStyle}
          />
        </div>

        <div className="mt-9 flex justify-center">
          <Btn
            size="lg"
            icon={ready ? <Mic size={16} /> : <Upload size={16} />}
            disabled={!ready || starting}
            loading={starting}
            onClick={() =>
              onReady({
                resume_upload_id: cards.resume.uploadId!,
                jd_text: jdText.trim(),
                interviewer_style: style,
                voice_mode: voiceMode,
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
  state: CardState;
  storedResumes: StoredResume[];
  loadingResumes: boolean;
  inputRef: React.RefObject<HTMLInputElement>;
  onPickFile: (f: File) => void;
  onPickExisting: (r: StoredResume) => void;
}) {
  const done = !!state.uploadId;
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
          {state.uploading ? <Spinner size={18} /> : done ? <CheckCircle2 size={20} /> : <FileText size={20} />}
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
              value={state.uploadId ?? ''}
              onChange={(e) => {
                const r = storedResumes.find((x) => x.upload_id === e.target.value);
                if (r) onPickExisting(r);
              }}
              className="w-full px-3 py-2.5 bg-white border border-stone-300 rounded-lg text-[14px] text-stone-800 outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
            >
              <option value="">— 选一份简历 —</option>
              {storedResumes.map((r) => (
                <option key={r.upload_id} value={r.upload_id}>
                  {r.filename} · {(r.created_at || '').slice(0, 10)}
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

function PrefGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: Array<{ id: T; label: string; desc: string }>;
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="bg-white border border-stone-200 rounded-2xl p-5 shadow-[0_2px_10px_rgba(15,23,42,0.04)]">
      <div className="text-[16px] font-semibold text-stone-800 mb-3.5">{label}</div>
      <div className="grid grid-cols-2 gap-2.5">
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
  state: CardState;
  text: string;
  setText: (t: string) => void;
  inputRef: React.RefObject<HTMLInputElement>;
  onPick: (f: File) => void;
}) {
  const doneUpload = !!state.uploadId;
  const doneText = text.trim().length >= 20;
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
          {state.uploading ? <Spinner size={18} /> : done ? <CheckCircle2 size={20} /> : <Briefcase size={20} />}
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
