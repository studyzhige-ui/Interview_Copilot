import { useRef, useState } from 'react';
import { Upload, FileText, Briefcase, Mic2, CheckCircle2, Loader2, Play, Tag } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { startAnalyze, updateInterviewRecord, uploadAudio, uploadResume } from '@/api/interview';
import { uploadKnowledgeFile } from '@/api/knowledge';
import type { AnalysisProgress } from './AnalysisRunner';

interface SlotState {
  filename?: string;
  uploadId?: string;
  uploading?: boolean;
}

type SlotKey = 'audio' | 'resume' | 'jd';

const TAGS = ['Backend', 'Frontend', 'Algorithm', 'System', 'HR'] as const;
type TagOpt = typeof TAGS[number];

interface Props {
  initialTitle?: string;
  /** Externally-managed analysis state for THIS card's session. */
  analysis: AnalysisProgress | null;
  /** Caller hooks up the SSE runner; we just notify when /analyze succeeds. */
  onStart: (payload: {
    record_id: string;
    title: string;
    tag?: string;
  }) => void;
}

export function UploadCards({ initialTitle, analysis, onStart }: Props) {
  const [slots, setSlots] = useState<Record<SlotKey, SlotState>>({
    audio: {},
    resume: {},
    jd: {},
  });
  const [title, setTitle] = useState(initialTitle ?? '');
  const [tag, setTag] = useState<TagOpt | ''>('');
  const [starting, setStarting] = useState(false);
  // Whisper language hint. Forcing the language is the single biggest
  // accuracy win on clean monolingual audio. Default 中文 because that's
  // what 95% of our users record in; users with English interviews flip
  // this once.
  const [language, setLanguage] = useState<'zh' | 'en' | 'auto'>('zh');

  const audioRef = useRef<HTMLInputElement | null>(null);
  const resumeRef = useRef<HTMLInputElement | null>(null);
  const jdRef = useRef<HTMLInputElement | null>(null);

  const update = (k: SlotKey, patch: Partial<SlotState>) =>
    setSlots((s) => ({ ...s, [k]: { ...s[k], ...patch } }));

  const onPick = async (k: SlotKey, f: File) => {
    update(k, { filename: f.name, uploading: true });
    try {
      let uploadId = '';
      if (k === 'audio') uploadId = (await uploadAudio(f)).upload_id;
      else if (k === 'resume') uploadId = (await uploadResume(f)).upload_id;
      else uploadId = (await uploadKnowledgeFile(f, { category: 'jd', source_kind: 'official_docs' })).id;
      update(k, { filename: f.name, uploadId, uploading: false });
    } catch {
      update(k, { filename: '', uploadId: undefined, uploading: false });
      toast.error('上传失败');
    }
  };

  const canStart =
    !!slots.audio.uploadId && !!slots.resume.uploadId && !starting && analysis === null;

  const onStartClick = async () => {
    setStarting(true);
    try {
      const r = await startAnalyze({
        upload_id: slots.audio.uploadId!,
        resume_upload_id: slots.resume.uploadId!,
        jd_upload_id: slots.jd.uploadId,
        language,
      });
      onStart({
        record_id: r.record_id,
        title: title.trim() || '面试录音复盘',
        tag: tag || undefined,
      });
    } catch {
      toast.error('启动分析失败');
    } finally {
      setStarting(false);
    }
  };

  // ── While analyzing ──────────────────────────────────────────────────
  if (analysis !== null) {
    return (
      <div className="max-w-3xl mx-auto p-10">
        <div className="bg-white border border-stone-200 rounded-2xl shadow-sm p-10">
          <div className="flex items-center gap-3 mb-4">
            <Loader2 size={20} className="text-primary-500 animate-spin" />
            <div className="text-sm text-primary-700 font-mono">
              ● 正在转录与分析… {analysis.percent}%
            </div>
          </div>
          <div className="w-full h-2 bg-stone-100 rounded-full overflow-hidden mb-3">
            <div
              className="h-full bg-primary-500 transition-all duration-300 ease-out"
              style={{ width: `${analysis.percent}%` }}
            />
          </div>
          <div className="text-xs text-stone-500">
            {analysis.phase === 'progress'
              ? `阶段：${analysis.status ?? '处理中'}`
              : analysis.phase === 'connecting'
              ? '建立 SSE 连接中…'
              : analysis.phase === 'error'
              ? `连接错误：${analysis.message ?? ''}`
              : '等待后端推送进度'}
          </div>
          <div className="text-[11px] text-stone-400 mt-3">
            可以切换到其他面试 / 对话页面，分析任务会继续在后台运行；左侧列表会显示「分析中」状态。
          </div>
        </div>
      </div>
    );
  }

  // ── Upload state ─────────────────────────────────────────────────────
  return (
    <div className="max-w-3xl mx-auto p-8">
      <div className="flex items-center gap-3 mb-5">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="给这次面试起个名字（例：字节后端二面）"
          className="flex-1 px-3 py-2 bg-white border border-stone-200 rounded-lg text-sm text-stone-800 outline-none focus:border-primary-300"
        />
        <div className="relative">
          <Tag size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-stone-400 pointer-events-none" />
          <select
            value={tag}
            onChange={(e) => setTag(e.target.value as TagOpt | '')}
            className="pl-7 pr-7 py-2 bg-white border border-stone-200 rounded-lg text-xs text-stone-700 outline-none focus:border-primary-300 appearance-none"
          >
            <option value="">选标签（可选）</option>
            {TAGS.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3.5 mb-4">
        <UploadCard
          icon={<Mic2 size={18} />}
          title="上传音视频"
          subtitle="MP3 / MP4 / WAV · 自动转录"
          state={slots.audio}
          accept="audio/*,video/*"
          inputRef={audioRef}
          onPick={(f) => onPick('audio', f)}
          required
        />
        <UploadCard
          icon={<FileText size={18} />}
          title="上传简历"
          subtitle="PDF / DOCX · 用于分析背景"
          state={slots.resume}
          accept=".pdf,.doc,.docx,.txt,.md"
          inputRef={resumeRef}
          onPick={(f) => onPick('resume', f)}
          required
        />
        <UploadCard
          icon={<Briefcase size={18} />}
          title="上传岗位 JD"
          subtitle="TXT / MD · 可选，定位方向"
          state={slots.jd}
          accept=".pdf,.doc,.docx,.txt,.md"
          inputRef={jdRef}
          onPick={(f) => onPick('jd', f)}
        />
      </div>

      <div className="px-4 py-3 rounded-xl bg-primary-50 text-primary-700 text-[13px] flex items-center gap-2.5 mb-4">
        <span className="w-1.5 h-1.5 rounded-full bg-primary-500" />
        需要音视频 + 简历才能开始分析；岗位 JD 可选，提供后分析会更精准。
      </div>

      {/* Whisper language picker — sits next to the start button so users
          set it intentionally per upload. Forcing the language (vs auto)
          is the single biggest accuracy win on clean monolingual audio. */}
      <div className="flex flex-col items-center gap-3">
        <div className="flex items-center gap-3 text-[13px] text-stone-600">
          <span>转录语言：</span>
          <div className="inline-flex rounded-lg border border-stone-200 bg-white overflow-hidden">
            {([
              { value: 'zh',   label: '中文'   },
              { value: 'en',   label: 'English' },
              { value: 'auto', label: '自动'   },
            ] as const).map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setLanguage(opt.value)}
                className={[
                  'px-3 py-1.5 text-[13px] transition-colors',
                  language === opt.value
                    ? 'bg-primary-50 text-primary-700 font-medium'
                    : 'text-stone-600 hover:bg-stone-50',
                ].join(' ')}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <span className="text-stone-400 text-[11px]">
            {language === 'auto'
              ? '让 Whisper 自动检测（仅当录音中英混杂时推荐）'
              : '强制指定语言可显著提升单语录音的转写质量'}
          </span>
        </div>
        <Btn
          size="lg"
          icon={<Play size={16} />}
          disabled={!canStart}
          loading={starting}
          onClick={onStartClick}
        >
          {canStart ? '开始分析' : slots.audio.uploadId && slots.resume.uploadId ? '处理中…' : '请先完成必填上传'}
        </Btn>
      </div>
    </div>
  );
}

export async function applyDraftMetadata(
  recordId: string,
  patch: { title?: string; tag?: string },
): Promise<void> {
  if (!patch.title && !patch.tag) return;
  try {
    await updateInterviewRecord(recordId, patch);
  } catch {
    // non-fatal
  }
}

function UploadCard({
  icon,
  title,
  subtitle,
  state,
  accept,
  inputRef,
  onPick,
  required,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  state: SlotState;
  accept: string;
  inputRef: React.RefObject<HTMLInputElement>;
  onPick: (f: File) => void;
  required?: boolean;
}) {
  const done = !!state.uploadId;
  return (
    <div
      onClick={() => inputRef.current?.click()}
      className={[
        'p-5 bg-white rounded-2xl cursor-pointer transition-all border-2 border-dashed',
        done
          ? 'border-success-500'
          : required
          ? 'border-primary-300'
          : 'border-stone-300',
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
          'w-10 h-10 rounded-lg mb-3 flex items-center justify-center',
          done ? 'bg-success-50 text-success-700' : 'bg-primary-50 text-primary-600',
        ].join(' ')}
      >
        {state.uploading ? <Spinner size={16} /> : done ? <CheckCircle2 size={18} /> : icon}
      </div>
      <div className="text-sm font-semibold text-stone-800 flex items-center gap-1">
        {title}
        {required && <span className="text-[10px] text-danger-500">*</span>}
      </div>
      <div className="text-xs text-stone-500 mt-1">{subtitle}</div>
      {done && state.filename && (
        <div className="text-[11px] text-success-700 mt-2 truncate">{state.filename}</div>
      )}
      {!done && !state.uploading && (
        <div className="text-[11px] text-stone-400 mt-2 inline-flex items-center gap-1">
          <Upload size={11} />
          点击上传
        </div>
      )}
    </div>
  );
}
