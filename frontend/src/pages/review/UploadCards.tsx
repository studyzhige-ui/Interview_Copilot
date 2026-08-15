import { useRef, useState, DragEvent } from 'react';
import {
  FileText,
  Briefcase,
  CheckCircle2,
  Loader2,
  Sparkles,
  Tag,
  ArrowRight,
  FileAudio,
  Radio,
} from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { startAnalyze, updateInterviewRecord, uploadAudio } from '@/api/interview';
import { uploadFileAsset } from '@/api/fileAssets';
import type { AnalysisProgress } from './AnalysisRunner';
import { JobOpportunitySelect } from '@/pages/career/JobOpportunitySelect';

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
  analysis: AnalysisProgress | null;
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
  const [language, setLanguage] = useState<'zh' | 'en' | 'auto'>('zh');
  const [jobOpportunityId, setJobOpportunityId] = useState('');

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
      else if (k === 'resume') uploadId = await uploadFileAsset(f, 'resume');
      else uploadId = await uploadFileAsset(f, 'jd');
      update(k, { filename: f.name, uploadId, uploading: false });
    } catch {
      update(k, { filename: '', uploadId: undefined, uploading: false });
      toast.error('上传失败，请重试');
    }
  };

  const canStart =
    !!slots.audio.uploadId && !!slots.resume.uploadId && !starting && analysis === null;

  const onStartClick = async () => {
    setStarting(true);
    try {
      const r = await startAnalyze({
        upload_id: slots.audio.uploadId!,
        resume_file_asset_id: slots.resume.uploadId!,
        jd_file_asset_id: slots.jd.uploadId,
        job_opportunity_id: jobOpportunityId || undefined,
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

  // ── While analyzing (Futuristic Gemini Pipeline) ──────────────────────────
  if (analysis !== null) {
    const percent = Math.min(Math.max(analysis.percent, 0), 100);
    const statusText = analysis.status || '正在进行 AI 深度多维分析';

    return (
      <div className="max-w-3xl mx-auto p-6 md:p-12 flex flex-col items-center justify-center min-h-[520px]">
        <div className="w-full bg-white/90 backdrop-blur-xl border border-slate-200/90 rounded-3xl shadow-xl p-8 md:p-10 relative overflow-hidden">
          {/* Top glowing ambient line */}
          <div className="absolute top-0 left-0 right-0 h-1.5 bg-gradient-to-r from-blue-500 via-purple-500 to-pink-500 animate-pulse" />

          <div className="flex items-center gap-3.5 mb-6">
            <div className="w-12 h-12 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center shadow-inner">
              <Loader2 size={24} className="animate-spin text-blue-600" />
            </div>
            <div>
              <div className="text-base font-bold text-slate-800 flex items-center gap-2">
                <span>AI 正在全力解析面试录音…</span>
                <span className="text-xs px-2.5 py-0.5 rounded-full bg-blue-100 text-blue-700 font-mono font-bold">
                  {percent}%
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-0.5">{statusText}</p>
            </div>
          </div>

          {/* Progress Track */}
          <div className="w-full h-3 bg-slate-100 rounded-full overflow-hidden mb-6 p-0.5 shadow-inner">
            <div
              className="h-full bg-gradient-to-r from-blue-500 via-purple-500 to-rose-500 rounded-full transition-all duration-500 ease-out"
              style={{ width: `${Math.max(percent, 5)}%` }}
            />
          </div>

          {/* 4-Step Pipeline Visualizer */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            {[
              { title: '1. 语音转写', desc: 'Whisper 提取时间戳', active: percent >= 20 },
              { title: '2. 问答拆解', desc: '多轮对话意图抽取', active: percent >= 50 },
              { title: '3. STAR 诊断', desc: '能力雷达与扣分点', active: percent >= 80 },
              { title: '4. 知识沉淀', desc: '最佳回答与知识库', active: percent >= 98 },
            ].map((step, idx) => (
              <div
                key={idx}
                className={`p-3 rounded-2xl border transition-all ${
                  step.active
                    ? 'bg-blue-50/60 border-blue-200 text-blue-900 shadow-xs'
                    : 'bg-slate-50/70 border-slate-200/60 text-slate-400'
                }`}
              >
                <div className="text-xs font-bold mb-1 flex items-center gap-1">
                  {step.active ? (
                    <CheckCircle2 size={13} className="text-blue-600 shrink-0" />
                  ) : (
                    <Radio size={13} className="text-slate-400 shrink-0" />
                  )}
                  <span>{step.title}</span>
                </div>
                <div className="text-[11px] opacity-80">{step.desc}</div>
              </div>
            ))}
          </div>

          <div className="text-xs text-slate-400 text-center bg-slate-50 rounded-2xl py-2.5 px-4">
            💡 提示：你可以自由切换至其他对话或页面，后台任务将持续运行，完成后会自动同步更新。
          </div>
        </div>
      </div>
    );
  }

  // ── Gemini Studio Drop Hub ──────────────────────────────────────────────
  return (
    <div className="max-w-4xl mx-auto p-6 md:p-10 space-y-8 animate-in fade-in duration-300">
      {/* Hero Welcome Header */}
      <div className="text-center space-y-2">
        <div className="inline-flex items-center gap-2 px-3.5 py-1 rounded-full bg-blue-50 border border-blue-100 text-blue-700 text-xs font-semibold shadow-xs">
          <Sparkles size={14} className="text-blue-600" />
          <span>智能面试复盘与全景诊断</span>
        </div>
        <h2 className="text-2xl md:text-3xl font-bold text-slate-900 tracking-tight">
          开启一场全新的面试深度诊断
        </h2>
        <p className="text-sm text-slate-500 max-w-xl mx-auto leading-relaxed">
          上传面试录音、简历及目标岗位 JD，AI 将为你还原对话全貌、深度评估候选人表现并输出 STAR 优化指南。
        </p>
      </div>

      {/* Main Metadata Config Pill */}
      <div className="bg-white rounded-3xl border border-slate-200/90 shadow-sm p-4 flex flex-col md:flex-row items-center gap-3">
        <div className="flex-1 w-full relative">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="为本次面试复盘命名（如：腾讯二面 / 阿里后端研发专场）"
            className="w-full px-4 py-2.5 bg-slate-50 hover:bg-slate-100/70 focus:bg-white border border-slate-200/80 rounded-2xl text-sm font-medium text-slate-800 placeholder-slate-400 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all"
          />
        </div>

        <div className="flex items-center gap-2 w-full md:w-auto">
          <div className="relative flex-1 md:w-40">
            <Tag size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
            <select
              value={tag}
              onChange={(e) => setTag(e.target.value as TagOpt | '')}
              className="w-full pl-8 pr-7 py-2.5 bg-slate-50 hover:bg-slate-100/70 focus:bg-white border border-slate-200/80 rounded-2xl text-xs font-semibold text-slate-700 outline-none focus:border-blue-400 transition-all appearance-none cursor-pointer"
            >
              <option value="">选择专业标签</option>
              {TAGS.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* 3 Dropzone Cards (Audio + Resume + JD) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <UploadCard
          icon={<FileAudio size={22} />}
          title="上传面试录音 / 视频"
          subtitle="MP3 / M4A / WAV / MP4 格式"
          state={slots.audio}
          accept="audio/*,video/*"
          inputRef={audioRef}
          onPick={(f) => onPick('audio', f)}
          required
        />

        <UploadCard
          icon={<FileText size={22} />}
          title="上传个人简历"
          subtitle="PDF / DOCX 格式，用于对齐经历"
          state={slots.resume}
          accept=".pdf,.doc,.docx,.txt,.md"
          inputRef={resumeRef}
          onPick={(f) => onPick('resume', f)}
          required
        />

        <UploadCard
          icon={<Briefcase size={22} />}
          title="关联岗位 JD（可选）"
          subtitle="TXT / MD / PDF，精准定位要求"
          state={slots.jd}
          accept=".pdf,.doc,.docx,.txt,.md"
          inputRef={jdRef}
          onPick={(f) => onPick('jd', f)}
        />
      </div>

      {/* Associated Job Opportunity Selector & Language Setup */}
      <div className="bg-white/80 rounded-3xl border border-slate-200/80 p-5 space-y-4 shadow-xs">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex-1">
            <label className="block text-xs font-semibold text-slate-700 mb-1.5">
              关联求职机会（可选）
            </label>
            <JobOpportunitySelect
              value={jobOpportunityId}
              onChange={setJobOpportunityId}
              ariaLabel="录音复盘关联岗位"
              emptyLabel="不关联具体岗位"
            />
          </div>

          <div className="shrink-0">
            <label className="block text-xs font-semibold text-slate-700 mb-1.5">
              转录语言偏好
            </label>
            <div className="inline-flex rounded-2xl border border-slate-200 p-1 bg-slate-50">
              {([
                { value: 'zh', label: '中文为主' },
                { value: 'en', label: 'English' },
                { value: 'auto', label: '智能检测' },
              ] as const).map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setLanguage(opt.value)}
                  className={`px-3 py-1 text-xs font-medium rounded-xl transition-all ${
                    language === opt.value
                      ? 'bg-white text-blue-700 shadow-xs font-semibold'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Start Button Hero */}
      <div className="flex flex-col items-center justify-center pt-2">
        <Btn
          kind="sparkle"
          size="lg"
          disabled={!canStart}
          loading={starting}
          onClick={onStartClick}
          className="px-8 py-3.5 text-base font-semibold shadow-lg shadow-purple-500/20"
        >
          <Sparkles size={18} />
          <span>
            {canStart
              ? '开始分析'
              : slots.audio.uploadId && slots.resume.uploadId
              ? '处理中…'
              : '请先完成必填上传'}
          </span>
          <ArrowRight size={16} />
        </Btn>

        <p className="text-xs text-slate-400 mt-3">
          * 必填项：面试录音 + 个人简历。数据严格加密传输，保护个人隐私。
        </p>
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
  inputRef: React.RefObject<HTMLInputElement | null>;
  onPick: (f: File) => void;
  required?: boolean;
}) {
  const done = !!state.uploadId;
  const [isDragOver, setIsDragOver] = useState(false);

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) onPick(file);
  };

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
      className={[
        'group relative p-6 bg-white rounded-3xl cursor-pointer transition-all duration-200 border-2',
        isDragOver
          ? 'border-blue-500 bg-blue-50/50 scale-[1.02]'
          : done
          ? 'border-emerald-300/80 bg-emerald-50/20 shadow-xs'
          : required
          ? 'border-dashed border-slate-300 hover:border-blue-400 hover:bg-slate-50/80'
          : 'border-dashed border-slate-200 hover:border-slate-300 hover:bg-slate-50/60',
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

      <div className="flex flex-col items-center text-center">
        <div
          className={[
            'w-14 h-14 rounded-2xl mb-3.5 flex items-center justify-center transition-all duration-200',
            done
              ? 'bg-emerald-100 text-emerald-700 shadow-sm'
              : required
              ? 'bg-blue-50 text-blue-600 group-hover:scale-110'
              : 'bg-slate-100 text-slate-500 group-hover:scale-110',
          ].join(' ')}
        >
          {state.uploading ? (
            <Spinner size={20} />
          ) : done ? (
            <CheckCircle2 size={24} className="text-emerald-600" />
          ) : (
            icon
          )}
        </div>

        <div className="text-sm font-bold text-slate-800 flex items-center gap-1">
          {title}
          {required && <span className="text-red-500 font-normal">*</span>}
        </div>

        <div className="text-xs text-slate-400 mt-1">{subtitle}</div>

        {done && state.filename ? (
          <div className="mt-3 px-3 py-1 rounded-full bg-emerald-100/70 text-emerald-800 text-[11.5px] font-medium truncate max-w-full">
            ✓ {state.filename}
          </div>
        ) : (
          <div className="mt-3 text-[11.5px] font-semibold text-blue-600 opacity-0 group-hover:opacity-100 transition-opacity">
            点击或拖拽文件到此处
          </div>
        )}
      </div>
    </div>
  );
}
