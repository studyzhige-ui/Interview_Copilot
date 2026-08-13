import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowUpRight, Brain, Pencil, ShieldOff, Trash2 } from 'lucide-react';
import {
  deleteAgentMemory,
  getAgentMemories,
  getAgentMemorySettings,
  getCopilotPreference,
  invalidateAgentMemory,
  promoteAgentMemoryToPreference,
  updateAgentMemory,
  updateAgentMemorySettings,
} from '@/api/personalization';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { Modal } from '@/components/ui/Modal';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { FormItem, TextArea, TextInput, csv, displayDate } from '@/pages/career/CareerFields';
import { toast } from '@/store/uiStore';
import type {
  AgentMemory,
  AgentMemorySettings,
  AgentMemoryStatus,
  AgentMemoryValence,
} from '@/types/personalization';

export const AGENT_MEMORY_SETTINGS_KEY = ['personalization', 'agent-memory-settings'] as const;
export const AGENT_MEMORIES_KEY = ['personalization', 'agent-memories'] as const;
const PREFERENCE_KEY = ['personalization', 'copilot-preference'] as const;

function isConflict(error: unknown): boolean {
  return (error as { response?: { status?: number } })?.response?.status === 409;
}

const statusLabel: Record<AgentMemoryStatus, string> = {
  active: '有效',
  invalidated: '已失效',
  deleted: '已删除',
};

const valenceLabel: Record<AgentMemoryValence, string> = {
  effective: '曾有效',
  ineffective: '曾无效',
  mixed: '效果不一',
};

function statusTone(status: AgentMemoryStatus): 'success' | 'warn' | 'neutral' {
  if (status === 'active') return 'success';
  if (status === 'invalidated') return 'warn';
  return 'neutral';
}

function defaultPromotionInstruction(memory: AgentMemory): string {
  const applicability = memory.applicability.trim();
  const contextualPrefix = /[时当]$/.test(applicability)
    ? `在${applicability}`
    : `在${applicability}时`;
  return `${contextualPrefix}，${memory.content}`;
}

export function AgentMemorySettingsSection() {
  const settingsQuery = useQuery({
    queryKey: AGENT_MEMORY_SETTINGS_KEY,
    queryFn: getAgentMemorySettings,
  });
  const memoriesQuery = useQuery({
    queryKey: AGENT_MEMORIES_KEY,
    queryFn: () => getAgentMemories(true),
  });

  return (
    <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
      <div className="flex items-start gap-3">
        <Brain size={18} className="mt-0.5 shrink-0 text-primary-600" />
        <div>
          <h2 className="text-sm font-semibold text-stone-800">Long-term Agent Memory</h2>
          <p className="mt-1 text-xs leading-relaxed text-stone-500">
            这里只保存过去协作中对你有帮助或无帮助的软性经验。它不是个人事实、业务记录、历史原文、指令或项目级 Memory；需要事实时 Agent 仍会读取权威所有者。
          </p>
        </div>
      </div>

      {settingsQuery.isLoading ? (
        <div className="mt-4 flex items-center gap-2 text-xs text-stone-500"><Spinner size={13} />正在读取 Memory 控制…</div>
      ) : settingsQuery.data ? (
        <MemorySettingsForm
          key={settingsQuery.data.version}
          initial={settingsQuery.data}
        />
      ) : (
        <div role="alert" className="mt-4 rounded-lg border border-danger-200 bg-danger-50 px-3 py-2 text-xs text-danger-700">
          {extractErr(settingsQuery.error, 'Memory 控制暂时无法读取')}
        </div>
      )}

      <div className="mt-6 border-t border-stone-100 pt-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-medium text-stone-800">已形成的 Memory</h3>
            <p className="mt-1 text-xs text-stone-500">包含有效、失效和已删除状态；已删除内容不会被自动恢复。</p>
          </div>
          <Btn kind="ghost" size="sm" onClick={() => memoriesQuery.refetch()}>刷新</Btn>
        </div>

        {memoriesQuery.isLoading ? (
          <div className="mt-4 flex items-center gap-2 text-xs text-stone-500"><Spinner size={13} />正在读取唯一用户级 Memory…</div>
        ) : memoriesQuery.isError ? (
          <div role="alert" className="mt-4 rounded-lg border border-danger-200 bg-danger-50 px-3 py-2 text-xs text-danger-700">
            {extractErr(memoriesQuery.error, 'Memory 列表暂时无法读取')}
          </div>
        ) : (memoriesQuery.data ?? []).length === 0 ? (
          <div className="mt-4 rounded-lg bg-stone-50 px-4 py-5 text-center text-xs text-stone-500">
            还没有形成长期协作经验。只有在你允许贡献、对话完成且出现明确有效/无效反馈时，系统才可能生成 Memory。
          </div>
        ) : (
          <MemoryList memories={memoriesQuery.data ?? []} />
        )}
      </div>
    </section>
  );
}

function MemorySettingsForm({ initial }: { initial: AgentMemorySettings }) {
  const queryClient = useQueryClient();
  const [recallEnabled, setRecallEnabled] = useState(initial.recall_enabled);
  const [contributionEnabled, setContributionEnabled] = useState(initial.contribution_enabled);
  const [version, setVersion] = useState(initial.version);
  const [saving, setSaving] = useState(false);
  const dirty = recallEnabled !== initial.recall_enabled
    || contributionEnabled !== initial.contribution_enabled;

  const save = async () => {
    setSaving(true);
    try {
      const saved = await updateAgentMemorySettings(
        version,
        recallEnabled,
        contributionEnabled,
      );
      queryClient.setQueryData(AGENT_MEMORY_SETTINGS_KEY, saved);
      toast.success('Memory 使用与贡献控制已保存');
    } catch (error) {
      if (isConflict(error)) {
        const latest = await getAgentMemorySettings();
        setVersion(latest.version);
        toast.error('Memory 控制已在其他页面更新；已刷新版本，你的选择仍保留，请再次保存');
      } else {
        toast.error(extractErr(error, 'Memory 控制保存失败'));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={`cursor-pointer rounded-lg border p-4 transition ${recallEnabled ? 'border-primary-300 bg-primary-50' : 'border-stone-200 hover:bg-stone-50'}`}>
          <span className="flex items-center gap-2 text-sm font-medium text-stone-800">
            <input
              type="checkbox"
              checked={recallEnabled}
              onChange={(event) => setRecallEnabled(event.target.checked)}
            />
            在未来对话中使用 Memory
          </span>
          <span className="mt-2 block text-xs leading-relaxed text-stone-500">
            只选择性召回与当前请求相关的软性经验；关闭不会删除已保存 Memory。
          </span>
        </label>
        <label className={`cursor-pointer rounded-lg border p-4 transition ${contributionEnabled ? 'border-accent-300 bg-accent-50' : 'border-stone-200 hover:bg-stone-50'}`}>
          <span className="flex items-center gap-2 text-sm font-medium text-stone-800">
            <input
              type="checkbox"
              checked={contributionEnabled}
              disabled={!initial.producer_available && !contributionEnabled}
              onChange={(event) => setContributionEnabled(event.target.checked)}
            />
            允许已完成对话贡献 Memory
          </span>
          <span className="mt-2 block text-xs leading-relaxed text-stone-500">
            {initial.producer_available
              ? '贡献与使用相互独立。关闭后不会从新对话生成 Memory，但仍可选择使用已有 Memory。'
              : '当前部署未启用自动 Memory 生产器，因此不能开启新贡献；已有 Memory 的使用不受影响。'}
          </span>
        </label>
      </div>
      {!initial.producer_available && (
        <div className="mt-3 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-xs text-warning-800">
          自动 Memory 生产器当前不可用。账户中的贡献意愿不会被误显示为实际生效。
        </div>
      )}
      <div className="mt-3 flex items-center justify-between gap-3">
        <span className="text-xs text-stone-400">账户级控制 · v{version}</span>
        <Btn loading={saving} disabled={!dirty} onClick={() => { void save(); }}>保存 Memory 控制</Btn>
      </div>
    </div>
  );
}

function MemoryList({ memories }: { memories: AgentMemory[] }) {
  const queryClient = useQueryClient();
  const preferenceQuery = useQuery({ queryKey: PREFERENCE_KEY, queryFn: getCopilotPreference });
  const [editTarget, setEditTarget] = useState<AgentMemory | null>(null);
  const [invalidateTarget, setInvalidateTarget] = useState<AgentMemory | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AgentMemory | null>(null);
  const [promotionTarget, setPromotionTarget] = useState<AgentMemory | null>(null);
  const [busy, setBusy] = useState(false);

  const replaceMemory = (saved: AgentMemory) => {
    queryClient.setQueryData<AgentMemory[]>(AGENT_MEMORIES_KEY, (current = []) => (
      current.map((item) => item.id === saved.id ? saved : item)
    ));
  };

  const refreshAfterConflict = async () => {
    setEditTarget(null);
    setInvalidateTarget(null);
    setDeleteTarget(null);
    setPromotionTarget(null);
    await queryClient.invalidateQueries({ queryKey: AGENT_MEMORIES_KEY });
    toast.error('这条 Memory 已在其他页面更新；已刷新，请根据最新版本重试');
  };

  const invalidate = async () => {
    if (!invalidateTarget) return;
    setBusy(true);
    try {
      replaceMemory(await invalidateAgentMemory(
        invalidateTarget.id,
        invalidateTarget.version,
        'user_invalidated_from_settings',
      ));
      setInvalidateTarget(null);
      toast.success('Memory 已失效，之后不会被召回');
    } catch (error) {
      if (isConflict(error)) await refreshAfterConflict();
      else toast.error(extractErr(error, 'Memory 失效失败'));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      replaceMemory(await deleteAgentMemory(
        deleteTarget.id,
        deleteTarget.version,
        'user_deleted_from_settings',
      ));
      setDeleteTarget(null);
      toast.success('Memory 已删除且不会被自动恢复');
    } catch (error) {
      if (isConflict(error)) await refreshAfterConflict();
      else toast.error(extractErr(error, 'Memory 删除失败'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 space-y-3">
      {memories.map((memory) => (
        <article key={memory.id} className="rounded-lg border border-stone-200 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone={statusTone(memory.status)}>{statusLabel[memory.status]}</Pill>
                <Pill>{valenceLabel[memory.valence]}</Pill>
                <span className="text-[11px] text-stone-400">置信度 {Math.round(memory.confidence * 100)}%</span>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-stone-800">{memory.content}</p>
              <p className="mt-2 text-xs leading-relaxed text-stone-500">
                <span className="font-medium text-stone-600">适用条件：</span>{memory.applicability}
              </p>
              {memory.tags.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {memory.tags.map((tag) => <Pill key={tag}>{tag}</Pill>)}
                </div>
              )}
            </div>
            {memory.status !== 'deleted' && (
              <div className="flex flex-wrap gap-1.5">
                <Btn kind="ghost" size="sm" icon={<Pencil size={12} />} onClick={() => setEditTarget(memory)}>
                  {memory.status === 'active' ? '编辑' : '修订并恢复'}
                </Btn>
                {memory.status === 'active' && (
                  <>
                    <Btn
                      kind="outline"
                      size="sm"
                      icon={<ArrowUpRight size={12} />}
                      disabled={!preferenceQuery.data}
                      title={preferenceQuery.data ? undefined : '正在读取全局协作偏好版本'}
                      onClick={() => setPromotionTarget(memory)}
                    >晋升为偏好</Btn>
                    <Btn kind="ghost" size="sm" icon={<ShieldOff size={12} />} onClick={() => setInvalidateTarget(memory)}>失效</Btn>
                  </>
                )}
                <Btn kind="danger" size="sm" icon={<Trash2 size={12} />} onClick={() => setDeleteTarget(memory)}>删除</Btn>
              </div>
            )}
          </div>

          <dl className="mt-4 grid gap-2 border-t border-stone-100 pt-3 text-[11px] text-stone-500 sm:grid-cols-2">
            <div><dt className="inline font-medium text-stone-600">形成时间：</dt><dd className="inline">{displayDate(memory.formed_at)}</dd></div>
            <div><dt className="inline font-medium text-stone-600">最近确认：</dt><dd className="inline">{displayDate(memory.last_confirmed_at)}</dd></div>
            <div><dt className="inline font-medium text-stone-600">最近召回：</dt><dd className="inline">{displayDate(memory.last_recalled_at)}（{memory.recall_count} 次）</dd></div>
            <div><dt className="inline font-medium text-stone-600">最近更新：</dt><dd className="inline">{displayDate(memory.updated_at)} · v{memory.version}</dd></div>
          </dl>
          {memory.status_reason && (
            <p className="mt-2 text-[11px] text-stone-500">状态原因：{memory.status_reason}</p>
          )}
          <div className="mt-3 rounded-lg bg-stone-50 px-3 py-2.5">
            <div className="text-[11px] font-medium text-stone-600">来源 History（{memory.sources.length}）</div>
            {memory.sources.length === 0 ? (
              <div className="mt-1 text-[11px] text-stone-400">原始来源已不可用</div>
            ) : (
              <ul className="mt-1.5 space-y-1.5">
                {memory.sources.map((source) => (
                  <li key={`${source.source_conversation_identity}:${source.source_turn_identity}`} className="text-[11px] text-stone-500">
                    <span className="font-mono text-stone-600">Conversation {source.source_conversation_identity}</span>
                    {' · '}
                    <span className="font-mono text-stone-600">Turn {source.source_turn_identity}</span>
                    {' · '}{displayDate(source.observed_at)}
                    {source.source_deleted_at && <span className="ml-1 text-warning-700">（来源已删除）</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </article>
      ))}

      {editTarget && (
        <MemoryEditDialog
          key={`${editTarget.id}:${editTarget.version}`}
          memory={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={(saved) => { replaceMemory(saved); setEditTarget(null); }}
          onConflict={refreshAfterConflict}
        />
      )}
      {promotionTarget && preferenceQuery.data && (
        <MemoryPromotionDialog
          key={`${promotionTarget.id}:${promotionTarget.version}:${preferenceQuery.data.version}`}
          memory={promotionTarget}
          preferenceVersion={preferenceQuery.data.version}
          onClose={() => setPromotionTarget(null)}
          onPromoted={(result) => {
            replaceMemory(result.memory);
            queryClient.setQueryData(PREFERENCE_KEY, result.preference);
            setPromotionTarget(null);
          }}
          onConflict={async () => {
            setPromotionTarget(null);
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: AGENT_MEMORIES_KEY }),
              queryClient.invalidateQueries({ queryKey: PREFERENCE_KEY }),
            ]);
            toast.error('Memory 或全局偏好版本已变化；已刷新，请重试');
          }}
        />
      )}
      <ConfirmDialog
        open={Boolean(invalidateTarget)}
        title="让这条 Memory 失效？"
        description="失效后不会再被召回。你仍能看到来源与状态，也可以在修订内容和适用条件后恢复。"
        confirmText="确认失效"
        loading={busy}
        onCancel={() => { if (!busy) setInvalidateTarget(null); }}
        onConfirm={() => { void invalidate(); }}
      />
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        danger
        title="删除这条 Memory？"
        description="删除后它不会被自动生成流程恢复；状态与来源身份仍保留用于审计。"
        confirmText="永久删除"
        loading={busy}
        onCancel={() => { if (!busy) setDeleteTarget(null); }}
        onConfirm={() => { void remove(); }}
      />
    </div>
  );
}

function MemoryEditDialog({
  memory,
  onClose,
  onSaved,
  onConflict,
}: {
  memory: AgentMemory;
  onClose: () => void;
  onSaved: (saved: AgentMemory) => void;
  onConflict: () => Promise<void>;
}) {
  const [content, setContent] = useState(memory.content);
  const [applicability, setApplicability] = useState(memory.applicability);
  const [tags, setTags] = useState(memory.tags.join(', '));
  const [saving, setSaving] = useState(false);
  const normalizedTags = [...new Set(csv(tags).map((tag) => tag.toLocaleLowerCase()))];
  const tagsInvalid = normalizedTags.length > 12
    || normalizedTags.some((tag) => tag.length > 40);

  const save = async () => {
    setSaving(true);
    try {
      const saved = await updateAgentMemory(
        memory.id,
        memory.version,
        content.trim(),
        applicability.trim(),
        normalizedTags,
      );
      onSaved(saved);
      toast.success(memory.status === 'active' ? 'Memory 已修订' : 'Memory 已修订并恢复');
    } catch (error) {
      if (isConflict(error)) await onConflict();
      else toast.error(extractErr(error, 'Memory 修订失败'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={memory.status === 'active' ? '编辑 Memory' : '修订并恢复 Memory'}
      width={620}
      footer={<>
        <Btn kind="ghost" disabled={saving} onClick={onClose}>取消</Btn>
        <Btn
          loading={saving}
          disabled={!content.trim() || !applicability.trim() || tagsInvalid}
          onClick={() => { void save(); }}
        >保存</Btn>
      </>}
    >
      <div className="space-y-4">
        <FormItem label="软性经验" hint="只描述过去什么协作方式有效或无效，不要填写个人事实、记录或指令。">
          <TextArea aria-label="Memory 内容" rows={4} maxLength={800} value={content} onChange={(event) => setContent(event.target.value)} />
        </FormItem>
        <FormItem label="适用条件">
          <TextArea aria-label="Memory 适用条件" rows={3} maxLength={400} value={applicability} onChange={(event) => setApplicability(event.target.value)} />
        </FormItem>
        <FormItem label="标签" hint="用逗号分隔，最多 12 个；每个标签最多 40 个字符。">
          <TextInput aria-label="Memory 标签" maxLength={600} value={tags} onChange={(event) => setTags(event.target.value)} />
        </FormItem>
        {tagsInvalid && <p className="text-xs text-danger-600">请将标签控制在 12 个以内，且每个不超过 40 个字符。</p>}
      </div>
    </Modal>
  );
}

function MemoryPromotionDialog({
  memory,
  preferenceVersion,
  onClose,
  onPromoted,
  onConflict,
}: {
  memory: AgentMemory;
  preferenceVersion: number;
  onClose: () => void;
  onPromoted: (result: Awaited<ReturnType<typeof promoteAgentMemoryToPreference>>) => void;
  onConflict: () => Promise<void>;
}) {
  const [instruction, setInstruction] = useState(defaultPromotionInstruction(memory));
  const [saving, setSaving] = useState(false);

  const promote = async () => {
    setSaving(true);
    try {
      onPromoted(await promoteAgentMemoryToPreference(
        memory.id,
        memory.version,
        preferenceVersion,
        instruction.trim(),
      ));
      toast.success('已加入全局协作偏好；原 Memory 已失效以避免重复');
    } catch (error) {
      if (isConflict(error)) await onConflict();
      else toast.error(extractErr(error, 'Memory 晋升失败'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="晋升为全局协作偏好"
      width={620}
      footer={<>
        <Btn kind="ghost" disabled={saving} onClick={onClose}>取消</Btn>
        <Btn loading={saving} disabled={!instruction.trim()} onClick={() => { void promote(); }}>确认晋升</Btn>
      </>}
    >
      <div className="space-y-4">
        <p className="text-xs leading-relaxed text-stone-500">
          晋升会把你确认后的措辞写入全局 CopilotPreference，并让这条软性 Memory 失效，避免同一规则从两个所有者重复进入上下文。
        </p>
        <FormItem label="全局协作规则">
          <TextArea aria-label="晋升后的全局协作规则" rows={5} maxLength={1000} value={instruction} onChange={(event) => setInstruction(event.target.value)} />
        </FormItem>
      </div>
    </Modal>
  );
}
