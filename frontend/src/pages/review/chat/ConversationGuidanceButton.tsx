import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { MessageSquareText } from 'lucide-react';
import { getChatTranscript } from '@/api/chat';
import {
  getConversationGuidance,
  updateConversationGuidance,
} from '@/api/personalization';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { Modal } from '@/components/ui/Modal';
import { Spinner } from '@/components/ui/Spinner';
import { FormItem, TextArea } from '@/pages/career/CareerFields';
import { toast } from '@/store/uiStore';
import type { ChatMessageItem } from '@/types/api';
import type { ScopedGuidance } from '@/types/personalization';

function guidanceKey(sessionId: string) {
  return ['personalization', 'conversation-guidance', sessionId] as const;
}

function preview(message: ChatMessageItem): string {
  const content = message.content.replace(/\s+/g, ' ').trim();
  return content.length > 90 ? `${content.slice(0, 90)}…` : content;
}

function isConflict(error: unknown): boolean {
  return (error as { response?: { status?: number } })?.response?.status === 409;
}

export function ConversationGuidanceButton({ sessionId }: { sessionId: string | null }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        disabled={!sessionId}
        onClick={() => setOpen(true)}
        title="设置只属于当前对话的协作规则"
        className="inline-flex items-center gap-1 rounded-full border border-stone-200 bg-white px-2.5 py-1 text-[11px] font-medium text-stone-600 hover:border-primary-200 hover:text-primary-700 disabled:opacity-50"
      >
        <MessageSquareText size={11} /> 对话规则
      </button>
      {open && sessionId && (
        <ConversationGuidanceModal
          key={sessionId}
          sessionId={sessionId}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function ConversationGuidanceModal({
  sessionId,
  onClose,
}: {
  sessionId: string;
  onClose: () => void;
}) {
  const guidanceQuery = useQuery({
    queryKey: guidanceKey(sessionId),
    queryFn: () => getConversationGuidance(sessionId),
  });
  const transcriptQuery = useQuery({
    queryKey: ['chat', 'transcript', 'guidance-sources', sessionId],
    queryFn: ({ signal }) => getChatTranscript(sessionId, { signal }),
  });
  const loading = guidanceQuery.isLoading || transcriptQuery.isLoading;
  const error = guidanceQuery.error ?? transcriptQuery.error;

  if (loading) {
    return (
      <Modal open onClose={onClose} title="当前对话规则" width={620}>
        <div className="flex items-center gap-2 py-8 text-sm text-stone-500"><Spinner size={15} />正在读取当前对话与真实消息来源…</div>
      </Modal>
    );
  }
  if (!guidanceQuery.data || !transcriptQuery.data) {
    return (
      <Modal open onClose={onClose} title="当前对话规则" width={620}>
        <div className="py-6 text-sm text-danger-600">{extractErr(error, '当前对话规则暂时无法读取')}</div>
      </Modal>
    );
  }
  const userMessages = transcriptQuery.data.messages.filter(
    (message) => message.role.toLowerCase() === 'user' && Number.isInteger(message.id),
  );
  return (
    <ConversationGuidanceForm
      key={`${guidanceQuery.data.version}:${userMessages.map((message) => message.id).join(',')}`}
      sessionId={sessionId}
      initial={guidanceQuery.data}
      userMessages={userMessages}
      onClose={onClose}
    />
  );
}

function ConversationGuidanceForm({
  sessionId,
  initial,
  userMessages,
  onClose,
}: {
  sessionId: string;
  initial: ScopedGuidance;
  userMessages: ChatMessageItem[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const latestSourceId = userMessages.at(-1)?.id ?? null;
  const [guidance, setGuidance] = useState(initial.guidance ?? '');
  const [sourceMessageId, setSourceMessageId] = useState<number | null>(
    initial.source_message_id ?? latestSourceId,
  );
  const [version, setVersion] = useState(initial.version);
  const [saving, setSaving] = useState(false);
  const normalized = guidance.trim();

  const persist = async (nextGuidance: string | null, nextSourceId: number | null) => {
    setSaving(true);
    try {
      const saved = await updateConversationGuidance(
        sessionId,
        version,
        nextGuidance,
        nextSourceId,
      );
      queryClient.setQueryData(guidanceKey(sessionId), saved);
      toast.success(nextGuidance ? '当前对话规则已保存' : '当前对话规则已清除');
      onClose();
    } catch (error) {
      if (isConflict(error)) {
        const latest = await getConversationGuidance(sessionId);
        setVersion(latest.version);
        toast.error('当前对话规则已在其他页面更新；已刷新版本，你的草稿仍保留，请再次保存');
      } else {
        toast.error(extractErr(error, '当前对话规则保存失败'));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="当前对话规则"
      width={620}
      footer={<>
        {initial.guidance && (
          <Btn kind="outline" disabled={saving} onClick={() => { void persist(null, null); }}>清除规则</Btn>
        )}
        <Btn kind="ghost" disabled={saving} onClick={onClose}>取消</Btn>
        <Btn
          loading={saving}
          disabled={!normalized || sourceMessageId === null}
          onClick={() => { void persist(normalized, sourceMessageId); }}
        >
          保存到当前对话
        </Btn>
      </>}
    >
      <div className="space-y-4">
        <p className="text-xs leading-relaxed text-stone-500">
          规则只在当前 Conversation 生效。原始措辞仍归下面所选的真实用户消息所有，不会被复制成全局偏好或长期记忆。
        </p>
        <FormItem label="协作规则">
          <TextArea
            aria-label="当前对话规则"
            rows={5}
            maxLength={4000}
            value={guidance}
            onChange={(event) => setGuidance(event.target.value)}
          />
        </FormItem>
        <FormItem label="原始用户消息" hint="非空规则必须引用当前 Conversation 中一条真实用户消息。">
          {userMessages.length > 0 ? (
            <select
              aria-label="对话规则来源消息"
              value={sourceMessageId ?? ''}
              onChange={(event) => setSourceMessageId(Number(event.target.value))}
              className="w-full rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm text-stone-700 outline-none focus:border-primary-300"
            >
              {userMessages.map((message) => (
                <option key={message.id} value={message.id}>#{message.seq} · {preview(message) || '（空消息）'}</option>
              ))}
            </select>
          ) : (
            <div className="rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-xs text-warning-800">
              当前对话还没有已持久化的用户消息，因此只能清除已有规则，不能创建非空规则。
            </div>
          )}
        </FormItem>
      </div>
    </Modal>
  );
}
