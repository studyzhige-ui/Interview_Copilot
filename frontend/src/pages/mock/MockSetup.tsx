import { useRef, useState } from 'react';
import { Upload, FileText, Briefcase, CheckCircle2, Mic } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { uploadResume } from '@/api/interview';
import { uploadKnowledgeFile } from '@/api/knowledge';

interface Props {
  onReady: (payload: { resume_upload_id: string; jd_doc_id: string }) => void;
  starting: boolean;
}

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
    update('jd', { filename: f.name, uploading: true });
    try {
      const doc = await uploadKnowledgeFile(f, { category: 'jd', source_type: 'official_docs' });
      update('jd', { uploadId: doc.id, uploading: false });
      toast.success('JD 已入库');
    } catch {
      update('jd', empty);
      toast.error('JD 上传失败');
    }
  };

  const ready = !!cards.resume.uploadId && !!cards.jd.uploadId;

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
          <UploadCard
            icon={<Briefcase size={20} />}
            title="上传岗位 JD"
            subtitle="TXT / MD · 仅支持文本，定位提问方向"
            state={cards.jd}
            accept=".pdf,.doc,.docx,.txt,.md"
            inputRef={jdRef}
            onPick={onJd}
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
                jd_doc_id: cards.jd.uploadId!,
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
