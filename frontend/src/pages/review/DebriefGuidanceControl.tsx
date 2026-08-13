import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { NotebookPen } from 'lucide-react';
import { getDebriefGuidance, updateDebriefGuidance } from '@/api/personalization';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { Modal } from '@/components/ui/Modal';
import { Spinner } from '@/components/ui/Spinner';
import { FormItem, TextArea } from '@/pages/career/CareerFields';
import { toast } from '@/store/uiStore';
import type { ScopedGuidance } from '@/types/personalization';

function debriefKey(interviewId: string) {
  return ['personalization', 'debrief-guidance', interviewId] as const;
}

function isConflict(error: unknown): boolean {
  return (error as { response?: { status?: number } })?.response?.status === 409;
}

export function DebriefGuidanceControl({ interviewId }: { interviewId: string }) {
  const [open, setOpen] = useState(false);
  const guidanceQuery = useQuery({
    queryKey: debriefKey(interviewId),
    queryFn: () => getDebriefGuidance(interviewId),
  });
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium ${guidanceQuery.data?.guidance ? 'border-primary-200 bg-primary-50 text-primary-700' : 'border-stone-200 bg-white text-stone-600 hover:border-primary-200'}`}
      >
        <NotebookPen size={11} /> 本次复盘指导
      </button>
      {open && (
        <DebriefGuidanceModal
          key={interviewId}
          interviewId={interviewId}
          value={guidanceQuery.data ?? null}
          loading={guidanceQuery.isLoading}
          error={guidanceQuery.error}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function DebriefGuidanceModal({
  interviewId,
  value,
  loading,
  error,
  onClose,
}: {
  interviewId: string;
  value: ScopedGuidance | null;
  loading: boolean;
  error: unknown;
  onClose: () => void;
}) {
  if (loading) {
    return (
      <Modal open onClose={onClose} title="本次复盘指导" width={600}>
        <div className="flex items-center gap-2 py-8 text-sm text-stone-500"><Spinner size={15} />正在读取本次复盘指导…</div>
      </Modal>
    );
  }
  if (!value) {
    return (
      <Modal open onClose={onClose} title="本次复盘指导" width={600}>
        <div className="py-6 text-sm text-danger-600">{extractErr(error, '本次复盘指导暂时无法读取')}</div>
      </Modal>
    );
  }
  return (
    <DebriefGuidanceForm
      key={value.version}
      interviewId={interviewId}
      initial={value}
      onClose={onClose}
    />
  );
}

function DebriefGuidanceForm({
  interviewId,
  initial,
  onClose,
}: {
  interviewId: string;
  initial: ScopedGuidance;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [guidance, setGuidance] = useState(initial.guidance ?? '');
  const [saving, setSaving] = useState(false);
  const [version, setVersion] = useState(initial.version);

  const persist = async (next: string | null) => {
    setSaving(true);
    try {
      const saved = await updateDebriefGuidance(
        interviewId,
        version,
        next,
        null,
      );
      queryClient.setQueryData(debriefKey(interviewId), saved);
      toast.success(next ? '本次复盘指导已保存' : '本次复盘指导已清除');
      onClose();
    } catch (error) {
      if (isConflict(error)) {
        const latest = await getDebriefGuidance(interviewId);
        setVersion(latest.version);
        toast.error('本次复盘指导已在其他页面更新；已刷新版本，你的草稿仍保留，请再次保存');
      } else {
        toast.error(extractErr(error, '本次复盘指导保存失败'));
      }
    } finally {
      setSaving(false);
    }
  };

  const normalized = guidance.trim();
  return (
    <Modal
      open
      onClose={onClose}
      title="本次复盘指导"
      width={600}
      footer={<>
        {initial.guidance && <Btn kind="outline" disabled={saving} onClick={() => { void persist(null); }}>清除指导</Btn>}
        <Btn kind="ghost" disabled={saving} onClick={onClose}>取消</Btn>
        <Btn loading={saving} disabled={!normalized} onClick={() => { void persist(normalized); }}>保存到本次复盘</Btn>
      </>}
    >
      <div className="space-y-4">
        <p className="text-xs leading-relaxed text-stone-500">
          这条指导由当前 InterviewRecord 拥有，在它的全部复盘对话中生效；不会扩展到其他面试或全局。
        </p>
        <FormItem label="复盘协作指导" hint="例如：本次重点追问系统设计取舍，回答先指出事实缺口。">
          <TextArea
            aria-label="本次复盘指导"
            rows={6}
            maxLength={4000}
            value={guidance}
            onChange={(event) => setGuidance(event.target.value)}
          />
        </FormItem>
      </div>
    </Modal>
  );
}
