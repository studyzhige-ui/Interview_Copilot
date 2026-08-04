import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { FileText, RefreshCw, Star, Trash2, Upload } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { Pill } from '@/components/ui/Pill';
import { extractErr } from '@/api/client';
import {
  createResumeFromFile,
  deleteResume,
  listResumes,
  replaceResumeFromFile,
  setDefaultResume,
  type PersonalResume,
} from '@/api/resumes';
import { toast } from '@/store/uiStore';

const RESUME_ACCEPT = '.pdf,.doc,.docx,.txt,.md';

function statusMeta(status: string, hasText: boolean): {
  label: string;
  tone: 'success' | 'warn' | 'danger' | 'neutral';
} {
  if (status === 'success' || status === 'completed' || status === 'ready') return { label: '可使用', tone: 'success' };
  if (hasText) return { label: '可使用 · 索引中', tone: 'warn' };
  if (status === 'failed') return { label: '解析失败', tone: 'danger' };
  if (status === 'pending' || status === 'processing') return { label: '解析中', tone: 'warn' };
  return { label: status, tone: 'neutral' };
}

export function ResumeSection() {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [replaceTarget, setReplaceTarget] = useState<PersonalResume | null>(null);
  const [deleting, setDeleting] = useState<PersonalResume | null>(null);
  const [busy, setBusy] = useState(false);
  const query = useQuery({
    queryKey: ['resumes'],
    queryFn: ({ signal }) => listResumes({ signal }),
    refetchInterval: ({ state }) => state.data?.some(
      (resume) => resume.parse_status === 'pending' || resume.parse_status === 'processing',
    ) ? 2500 : false,
  });
  const resumes = query.data ?? [];

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['resumes'] });

  const openPicker = (target: PersonalResume | null = null) => {
    setReplaceTarget(target);
    fileRef.current?.click();
  };

  const upload = async (file: File) => {
    setBusy(true);
    try {
      if (replaceTarget) {
        await replaceResumeFromFile(replaceTarget.id, file);
        toast.success('简历已替换');
      } else {
        await createResumeFromFile(file, { make_default: resumes.length === 0 });
        toast.success('简历已上传，正在解析');
      }
      await refresh();
    } catch (error) {
      toast.error(extractErr(error, '简历上传失败'));
    } finally {
      setReplaceTarget(null);
      setBusy(false);
    }
  };

  const makeDefault = async (resume: PersonalResume) => {
    setBusy(true);
    try {
      await setDefaultResume(resume.id);
      toast.success('已设为默认简历');
      await refresh();
    } catch (error) {
      toast.error(extractErr(error, '设置失败'));
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    setBusy(true);
    try {
      await deleteResume(deleting.id);
      toast.success('简历已删除');
      setDeleting(null);
      await refresh();
    } catch (error) {
      toast.error(extractErr(error, '删除失败'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="mb-4 flex flex-wrap items-start gap-3">
        <div>
          <p className="text-sm font-medium text-stone-800">面试使用的个人简历</p>
          <p className="mt-1 text-xs text-stone-500">最多保留两份；默认简历会优先用于面试上下文，不会进入 RAG 知识库。</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => refresh()}
            className="rounded-md p-2 text-stone-500 hover:bg-stone-100"
            aria-label="刷新简历列表"
          >
            <RefreshCw size={14} />
          </button>
          <Btn
            icon={<Upload size={14} />}
            onClick={() => openPicker()}
            disabled={busy || resumes.length >= 2}
          >
            上传简历
          </Btn>
          <input
            ref={fileRef}
            type="file"
            accept={RESUME_ACCEPT}
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
              event.target.value = '';
            }}
          />
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-stone-200 bg-white shadow-xs">
        {query.isPending ? (
          <div className="p-8 text-center text-sm text-stone-500">正在载入简历…</div>
        ) : query.isError ? (
          <EmptyState
            icon={<FileText size={28} />}
            title="简历加载失败"
            description="请检查服务状态后重试。"
            action={<Btn kind="outline" onClick={() => refresh()}>重新加载</Btn>}
          />
        ) : resumes.length === 0 ? (
          <EmptyState
            icon={<FileText size={28} />}
            title="还没有个人简历"
            description="上传后可在模拟面试和面试复盘中复用，无需每次重新选择文件。"
            action={<Btn onClick={() => openPicker()}>上传第一份简历</Btn>}
          />
        ) : (
          <div className="divide-y divide-stone-100">
            {resumes.map((resume) => {
              const status = statusMeta(resume.parse_status, resume.has_text);
              return (
                <div key={resume.id} className="flex flex-wrap items-center gap-3 px-4 py-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary-50 text-primary-600">
                    <FileText size={18} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate font-medium text-stone-800">{resume.title}</span>
                      {resume.is_default && <Pill tone="primary"><Star size={10} />默认</Pill>}
                      <Pill tone={status.tone}>{status.label}</Pill>
                    </div>
                    <div className="mt-1 text-xs text-stone-400">
                      更新于 {resume.updated_at.slice(0, 19).replace('T', ' ')}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {!resume.is_default && (
                      <Btn kind="ghost" size="sm" disabled={busy} onClick={() => void makeDefault(resume)}>
                        设为默认
                      </Btn>
                    )}
                    <Btn kind="outline" size="sm" disabled={busy} onClick={() => openPicker(resume)}>
                      替换
                    </Btn>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setDeleting(resume)}
                      className="rounded-md p-2 text-danger-500 hover:bg-danger-50 disabled:opacity-40"
                      aria-label={`删除${resume.title}`}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!deleting}
        danger
        title="删除简历"
        description={`确认删除「${deleting?.title}」？${deleting?.is_default && resumes.length > 1 ? '另一份简历会自动成为默认简历。' : ''}`}
        confirmText="删除"
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      />
    </>
  );
}
