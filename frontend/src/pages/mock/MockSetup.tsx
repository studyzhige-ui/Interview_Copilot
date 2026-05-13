import { useRef, useState } from 'react';
import { Upload, FileText, Briefcase, CheckCircle2, Mic, FileUp, ClipboardPaste } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { uploadResume } from '@/api/interview';
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

const VOICE_OPTIONS: Array<{ id: VoiceMode; label: string; desc: string }> = [
  { id: 'hybrid', label: '语音 + 文字（默认）', desc: '面试官 TTS，我自由切换打字 / 语音' },
  { id: 'voice', label: '全程语音', desc: '面试官 TTS，我语音回答' },
  { id: 'text', label: '全程文字', desc: '完全打字交互' },
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
  const [jdMode, setJdMode] = useState<'upload' | 'paste'>('upload');
  const [jdText, setJdText] = useState('');
  const [style, setStyle] = useState<InterviewerStyle>('professional');
  const [voiceMode, setVoiceMode] = useState<VoiceMode>('hybrid');
  const resumeRef = useRef<HTMLInputElement | null>(null);
  const jdRef = useRef<HTMLInputElement | null>(null);

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
    <div className="h-full overflow-y-auto">
      <div className="max-w-[760px] mx-auto px-9 py-16 flex flex-col items-center">
        <div className="eyebrow text-[11px] font-medium uppercase tracking-wider text-stone-500">模拟面试</div>
        <h2 className="text-2xl font-semibold text-stone-800 text-center mt-1.5">
          开始之前，先准备两份材料
        </h2>
        <p className="text-stone-500 text-sm mt-1 mb-8 text-center">
          上传简历和岗位 JD 后，AI 面试官会根据你的背景定制问题。
        </p>

        <div className="grid grid-cols-2 gap-4 w-full">
          <UploadCard
            icon={<FileText size={20} />}
            title="上传简历"
            subtitle="PDF / DOCX · 用于个性化提问"
            state={cards.resume}
            accept=".pdf,.doc,.docx,.txt,.md"
            inputRef={resumeRef}
            onPick={onResume}
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

        {/* Preferences */}
        <div className="w-full mt-7 grid grid-cols-2 gap-4">
          <PrefGroup
            label="面试官风格"
            options={STYLE_OPTIONS}
            value={style}
            onChange={setStyle}
          />
          <PrefGroup
            label="语音模式"
            options={VOICE_OPTIONS}
            value={voiceMode}
            onChange={setVoiceMode}
          />
        </div>

        <div className="mt-8">
          <Btn
            size="lg"
            icon={<Mic size={16} />}
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

function UploadCard({
  icon,
  title,
  subtitle,
  state,
  accept,
  inputRef,
  onPick,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  state: CardState;
  accept: string;
  inputRef: React.RefObject<HTMLInputElement>;
  onPick: (f: File) => void;
}) {
  const done = !!state.uploadId;
  return (
    <div
      onClick={() => inputRef.current?.click()}
      className={[
        'p-[22px] bg-white rounded-2xl cursor-pointer transition-all border-2 border-dashed',
        done ? 'border-success-500' : 'border-stone-300 hover:border-primary-300',
      ].join(' ')}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onPick(f);
          e.target.value = '';
        }}
      />
      <div
        className={[
          'w-11 h-11 rounded-xl mb-3.5 flex items-center justify-center',
          done ? 'bg-success-50 text-success-700' : 'bg-primary-50 text-primary-600',
        ].join(' ')}
      >
        {state.uploading ? <Spinner size={18} /> : done ? <CheckCircle2 size={20} /> : icon}
      </div>
      <div className="text-[15px] font-semibold text-stone-800 flex items-center gap-1.5">
        {title}
        <span className="text-[10px] text-danger-500">*</span>
      </div>
      <div className="text-xs text-stone-500 mt-1">{subtitle}</div>
      {done && (
        <div className="text-[11px] text-success-700 mt-2.5 truncate">
          {state.filename || '已上传'} · 点击替换
        </div>
      )}
      {!done && !state.uploading && (
        <div className="text-[11px] text-stone-400 mt-2.5 inline-flex items-center gap-1">
          <Upload size={11} />
          点击上传
        </div>
      )}
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
    <div className="bg-white border border-stone-200 rounded-2xl p-4">
      <div className="text-xs font-semibold text-stone-600 mb-2.5">{label}</div>
      <div className="flex flex-col gap-1.5">
        {options.map((opt) => {
          const active = opt.id === value;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => onChange(opt.id)}
              className={[
                'text-left px-3 py-2 rounded-lg border transition-colors',
                active
                  ? 'border-primary-300 bg-primary-50'
                  : 'border-stone-200 hover:border-stone-300 hover:bg-stone-50',
              ].join(' ')}
            >
              <div className="text-[13px] font-medium text-stone-800 flex items-center gap-2">
                <span
                  className={[
                    'w-3 h-3 rounded-full border',
                    active ? 'border-primary-500 bg-primary-500' : 'border-stone-300',
                  ].join(' ')}
                />
                {opt.label}
              </div>
              <div className="text-[11px] text-stone-500 mt-0.5 ml-5">{opt.desc}</div>
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
      className={[
        'p-[22px] bg-white rounded-2xl transition-all border-2 border-dashed',
        done ? 'border-success-500' : 'border-stone-300',
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
      <div className="flex items-center gap-2 mb-3">
        <div
          className={[
            'w-11 h-11 rounded-xl flex items-center justify-center',
            done ? 'bg-success-50 text-success-700' : 'bg-primary-50 text-primary-600',
          ].join(' ')}
        >
          {state.uploading ? <Spinner size={18} /> : done ? <CheckCircle2 size={20} /> : <Briefcase size={20} />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[15px] font-semibold text-stone-800 flex items-center gap-1.5">
            上传岗位 JD
            <span className="text-[10px] text-danger-500">*</span>
          </div>
          <div className="text-xs text-stone-500 mt-0.5">用于定位提问方向</div>
        </div>
      </div>

      {/* Mode toggle: upload file OR paste text */}
      <div className="inline-flex p-0.5 bg-stone-100 rounded-md mb-3 text-xs">
        <button
          type="button"
          onClick={() => setMode('upload')}
          className={[
            'inline-flex items-center gap-1 px-2.5 py-1 rounded',
            mode === 'upload'
              ? 'bg-white text-stone-800 font-medium shadow-xs'
              : 'text-stone-500 hover:text-stone-700',
          ].join(' ')}
        >
          <FileUp size={11} />
          上传文件
        </button>
        <button
          type="button"
          onClick={() => setMode('paste')}
          className={[
            'inline-flex items-center gap-1 px-2.5 py-1 rounded',
            mode === 'paste'
              ? 'bg-white text-stone-800 font-medium shadow-xs'
              : 'text-stone-500 hover:text-stone-700',
          ].join(' ')}
        >
          <ClipboardPaste size={11} />
          粘贴文本
        </button>
      </div>

      {mode === 'upload' ? (
        <div
          onClick={() => inputRef.current?.click()}
          className="cursor-pointer text-xs"
        >
          {doneUpload ? (
            <div className="text-success-700 truncate">{state.filename || '已上传'} · 点击替换</div>
          ) : (
            <div className="text-stone-400 inline-flex items-center gap-1">
              <Upload size={11} />
              点击上传 PDF / DOCX / TXT / MD
            </div>
          )}
        </div>
      ) : (
        <>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="把 JD 全文粘贴到这里…（≥ 20 字才算有效）"
            rows={5}
            className="w-full px-3 py-2 bg-stone-50 border border-stone-200 rounded-md text-xs text-stone-700 outline-none focus:border-primary-300 resize-y leading-[1.6]"
          />
          <div className="text-[11px] text-stone-400 mt-1 flex justify-between">
            <span>{doneText ? '✓ 已就绪' : `当前 ${text.trim().length}/20 字`}</span>
            {text && (
              <button type="button" onClick={() => setText('')} className="hover:text-danger-500">
                清空
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
