import { useState } from 'react';
import { useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';
import { Brain } from 'lucide-react';
import {
  getConversationMemoryControls,
  updateConversationMemoryControls,
} from '@/api/personalization';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { Modal } from '@/components/ui/Modal';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { FormItem, SelectInput } from '@/pages/career/CareerFields';
import { toast } from '@/store/uiStore';
import type { ConversationMemoryControls } from '@/types/personalization';

type OverrideValue = 'inherit' | 'enabled' | 'disabled';

export function conversationMemoryControlsKey(sessionId: string) {
  return ['personalization', 'conversation-memory-controls', sessionId] as const;
}

function toSelectValue(value: boolean | null): OverrideValue {
  if (value === null) return 'inherit';
  return value ? 'enabled' : 'disabled';
}

function fromSelectValue(value: OverrideValue): boolean | null {
  if (value === 'inherit') return null;
  return value === 'enabled';
}

function isConflict(error: unknown): boolean {
  return (error as { response?: { status?: number } })?.response?.status === 409;
}

export function ConversationMemoryControlsButton({ sessionId }: { sessionId: string | null }) {
  const [open, setOpen] = useState(false);
  const controlsQuery = useQuery({
    queryKey: conversationMemoryControlsKey(sessionId ?? ''),
    queryFn: () => getConversationMemoryControls(sessionId!),
    enabled: Boolean(sessionId),
  });
  const controls = controlsQuery.data;

  return (
    <>
      <button
        type="button"
        disabled={!sessionId}
        onClick={() => setOpen(true)}
        title="控制当前对话是否使用已有 Memory、是否贡献新的 Memory"
        className="inline-flex items-center gap-1 rounded-full border border-stone-200 bg-white px-2.5 py-1 text-[11px] font-medium text-stone-600 hover:border-primary-200 hover:text-primary-700 disabled:opacity-50"
      >
        <Brain size={11} />
        Memory
        {controls && (
          <span className="text-stone-400">
            · 用{controls.effective_recall_enabled ? '开' : '关'}/贡{controls.effective_contribution_enabled ? '开' : '关'}
          </span>
        )}
      </button>
      {open && sessionId && (
        <ConversationMemoryControlsModal
          sessionId={sessionId}
          controlsQuery={controlsQuery}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function ConversationMemoryControlsModal({
  sessionId,
  controlsQuery,
  onClose,
}: {
  sessionId: string;
  controlsQuery: UseQueryResult<ConversationMemoryControls, Error>;
  onClose: () => void;
}) {
  if (controlsQuery.isLoading) {
    return (
      <Modal open onClose={onClose} title="当前对话的 Memory 控制" width={560}>
        <div className="flex items-center gap-2 py-8 text-sm text-stone-500"><Spinner size={15} />正在读取当前对话控制…</div>
      </Modal>
    );
  }
  if (!controlsQuery.data) {
    return (
      <Modal open onClose={onClose} title="当前对话的 Memory 控制" width={560}>
        <div role="alert" className="py-6 text-sm text-danger-600">{extractErr(controlsQuery.error, '当前对话 Memory 控制暂时无法读取')}</div>
      </Modal>
    );
  }
  return (
    <ConversationMemoryControlsForm
      key={`${sessionId}:${controlsQuery.data.version}`}
      sessionId={sessionId}
      initial={controlsQuery.data}
      onClose={onClose}
    />
  );
}

function ConversationMemoryControlsForm({
  sessionId,
  initial,
  onClose,
}: {
  sessionId: string;
  initial: ConversationMemoryControls;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [recall, setRecall] = useState<OverrideValue>(toSelectValue(initial.recall_override));
  const [contribution, setContribution] = useState<OverrideValue>(
    toSelectValue(initial.contribution_override),
  );
  const [version, setVersion] = useState(initial.version);
  const [saving, setSaving] = useState(false);
  const dirty = recall !== toSelectValue(initial.recall_override)
    || contribution !== toSelectValue(initial.contribution_override);

  const save = async () => {
    setSaving(true);
    try {
      const saved = await updateConversationMemoryControls(
        sessionId,
        version,
        fromSelectValue(recall),
        fromSelectValue(contribution),
      );
      queryClient.setQueryData(conversationMemoryControlsKey(sessionId), saved);
      toast.success('当前对话的 Memory 控制已保存');
      onClose();
    } catch (error) {
      if (isConflict(error)) {
        const latest = await getConversationMemoryControls(sessionId);
        setVersion(latest.version);
        toast.error('当前对话 Memory 控制已在其他页面更新；已刷新版本，你的选择仍保留，请再次保存');
      } else {
        toast.error(extractErr(error, '当前对话 Memory 控制保存失败'));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="当前对话的 Memory 控制"
      width={560}
      footer={<>
        <Btn kind="ghost" disabled={saving} onClick={onClose}>取消</Btn>
        <Btn loading={saving} disabled={!dirty} onClick={() => { void save(); }}>保存当前对话控制</Btn>
      </>}
    >
      <div className="space-y-4">
        <p className="text-xs leading-relaxed text-stone-500">
          这里仅覆盖当前 Conversation 是否使用用户级 Memory、是否让已完成 Turn 贡献 Memory；不会创建 Conversation、Debrief 或 Project scoped Memory。
        </p>
        <div className="flex flex-wrap gap-2 rounded-lg bg-stone-50 px-3 py-2.5">
          <Pill tone={initial.effective_recall_enabled ? 'success' : 'neutral'}>
            当前有效：使用{initial.effective_recall_enabled ? '开启' : '关闭'}
          </Pill>
          <Pill tone={initial.effective_contribution_enabled ? 'success' : 'neutral'}>
            当前有效：贡献{initial.effective_contribution_enabled ? '开启' : '关闭'}
          </Pill>
        </div>
        {!initial.producer_available && (
          <div className="rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-xs text-warning-800">
            当前部署未启用自动 Memory 生产器；贡献不会实际生效，但仍可关闭或改回继承。
          </div>
        )}
        <FormItem label="使用已有 Memory" hint="继承时跟随账户设置；即使关闭贡献，也可以单独开启使用。">
          <SelectInput
            aria-label="当前对话使用 Memory"
            value={recall}
            onChange={(event) => setRecall(event.target.value as OverrideValue)}
          >
            <option value="inherit">继承账户设置</option>
            <option value="enabled">仅在当前对话开启</option>
            <option value="disabled">仅在当前对话关闭</option>
          </SelectInput>
        </FormItem>
        <FormItem label="贡献新的 Memory" hint="仅当对话完成且存在明确的有效/无效反馈时才可能生成。">
          <SelectInput
            aria-label="当前对话贡献 Memory"
            value={contribution}
            onChange={(event) => setContribution(event.target.value as OverrideValue)}
          >
            <option value="inherit">继承账户设置</option>
            <option value="enabled" disabled={!initial.producer_available}>仅在当前对话开启</option>
            <option value="disabled">仅在当前对话关闭</option>
          </SelectInput>
        </FormItem>
        <div className="text-[11px] text-stone-400">Conversation {sessionId} · 控制版本 v{version}</div>
      </div>
    </Modal>
  );
}
