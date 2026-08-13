import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  CalendarClock,
  CirclePause,
  CirclePlay,
  ExternalLink,
  History,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  Zap,
} from 'lucide-react';
import {
  changePersistentTaskState,
  createPersistentTask,
  deletePersistentTask,
  getPersistentTask,
  listPersistentTaskEligibleTools,
  listPersistentTasks,
  listPersistentTaskTriggers,
  triggerPersistentTask,
  updatePersistentTask,
} from '@/api/persistentTasks';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { Modal } from '@/components/ui/Modal';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import {
  FormItem,
  SelectInput,
  TextArea,
  TextInput,
  csv,
  displayDate,
} from '@/pages/career/CareerFields';
import { ChatPanel } from '@/pages/review/chat/ChatPanel';
import { toast } from '@/store/uiStore';
import type {
  PersistentTask,
  PersistentTaskDefinitionInput,
  PersistentTaskEligibleTool,
  PersistentTaskTrigger,
  PersistentTaskTriggerAdmission,
  PersistentTaskTriggerSpec,
} from '@/types/persistentTask';

const TASKS_KEY = ['persistent-tasks'] as const;

const TOOL_LABELS: Record<string, string> = {
  web_search: '搜索公开网页', read_url: '读取公开网页', search_jobs: '搜索岗位',
  read_interview_history: '读取面试历史', search_knowledge: '检索个人资料',
  read_resume: '读取个人简历', read_career_context: '读取求职档案与进展',
  read_artifacts: '读取已保存材料', read_file: '读取已授权附件内容',
  gmail_search_messages: '搜索已连接 Gmail',
};

interface EditorForm {
  title: string;
  instruction: string;
  triggerKind: 'scheduled' | 'event';
  schedule: string;
  timezone: string;
  connector: string;
  eventTypes: string;
  readScope: string;
  actionScope: string;
  allowedToolNames: string[];
}

function operationId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `ui-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function blankForm(): EditorForm {
  return {
    title: '',
    instruction: '',
    triggerKind: 'scheduled',
    schedule: '0 9 * * 1-5',
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai',
    connector: '',
    eventTypes: '',
    readScope: '',
    actionScope: '',
    allowedToolNames: [],
  };
}

function formFromTask(task: PersistentTask): EditorForm {
  const trigger = task.trigger_spec_json;
  return {
    title: task.title,
    instruction: task.instruction,
    triggerKind: trigger.kind,
    schedule: trigger.kind === 'scheduled' ? trigger.schedule : '0 9 * * 1-5',
    timezone: trigger.kind === 'scheduled' ? trigger.timezone : (Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai'),
    connector: trigger.kind === 'event' ? trigger.connector : '',
    eventTypes: trigger.kind === 'event' ? trigger.event_types.join(', ') : '',
    readScope: task.read_scope_json.join(', '),
    actionScope: task.action_scope_json.join(', '),
    allowedToolNames: task.allowed_tool_names_json,
  };
}

function definitionFromForm(form: EditorForm): PersistentTaskDefinitionInput {
  const trigger: PersistentTaskTriggerSpec = form.triggerKind === 'scheduled'
    ? { kind: 'scheduled', schedule: form.schedule.trim(), timezone: form.timezone.trim() }
    : { kind: 'event', connector: form.connector.trim(), event_types: csv(form.eventTypes) };
  return {
    title: form.title.trim(),
    instruction: form.instruction.trim(),
    trigger,
    readScope: csv(form.readScope),
    actionScope: csv(form.actionScope),
    allowedToolNames: form.allowedToolNames,
  };
}

function triggerText(trigger: PersistentTaskTriggerSpec): string {
  if (trigger.kind === 'scheduled') return `${trigger.schedule} · ${trigger.timezone}`;
  return `${trigger.connector} · ${trigger.event_types.join('、')}`;
}

function admissionText(admission: PersistentTaskTriggerAdmission): string {
  if (admission.status === 'admitted') return '本次执行已进入专属对话。';
  if (admission.status === 'already_admitted') return '同一本次请求已经接纳，没有重复创建执行。';
  if (admission.status === 'pending') return `本次触发已保留，将在当前工作结束后执行（待处理 ${admission.pending_trigger_count} 条）。`;
  return '本次触发没有产生需要执行的内容。';
}

export function PersistentTasksPage() {
  const { taskId } = useParams<{ taskId?: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const listQuery = useQuery({ queryKey: TASKS_KEY, queryFn: listPersistentTasks });
  const tasks = listQuery.data ?? [];
  const selectedId = taskId ?? tasks[0]?.id ?? null;
  const detailQuery = useQuery({
    queryKey: ['persistent-task', selectedId],
    queryFn: () => getPersistentTask(selectedId!),
    enabled: Boolean(selectedId),
  });
  const triggersQuery = useQuery({
    queryKey: ['persistent-task', selectedId, 'triggers'],
    queryFn: () => listPersistentTaskTriggers(selectedId!),
    enabled: Boolean(selectedId),
  });
  const selected = detailQuery.data ?? tasks.find((task) => task.id === selectedId) ?? null;
  const [editor, setEditor] = useState<'create' | 'edit' | null>(null);
  const [busy, setBusy] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualSummary, setManualSummary] = useState('从页面手动检查一次最新变化');
  const [admission, setAdmission] = useState<PersistentTaskTriggerAdmission | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<PersistentTask | null>(null);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: TASKS_KEY });
    if (selectedId) {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['persistent-task', selectedId], exact: true }),
        queryClient.invalidateQueries({ queryKey: ['persistent-task', selectedId, 'triggers'] }),
      ]);
    }
  };

  const run = async (operation: () => Promise<unknown>, success: string) => {
    setBusy(true);
    try {
      await operation();
      await refresh();
      toast.success(success);
      return true;
    } catch (error) {
      toast.error(extractErr(error));
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (listQuery.isLoading) {
    return <div className="flex items-center gap-2 p-6 text-sm text-stone-500"><Spinner size={15} />正在加载持续任务…</div>;
  }

  if (listQuery.isError) {
    return (
      <div className="p-6">
        <EmptyState
          icon={<CalendarClock size={32} />}
          title="持续任务暂时无法加载"
          description={extractErr(listQuery.error)}
          action={<Btn onClick={() => listQuery.refetch()}>重试</Btn>}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl p-4 md:p-6">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-stone-800">持续任务</h1>
          <p className="mt-1 text-sm text-stone-500">只有你明确创建的任务才会在云端持续运行；无人值守时只使用已列出的只读 Tool。</p>
        </div>
        <div className="flex gap-2">
          <Btn kind="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={() => { void refresh(); }}>刷新</Btn>
          <Btn size="sm" icon={<Plus size={14} />} onClick={() => setEditor('create')}>新建持续任务</Btn>
        </div>
      </header>

      <div className="grid min-h-[560px] gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="overflow-hidden rounded-xl border border-stone-200 bg-white shadow-xs">
          <div className="border-b border-stone-100 px-4 py-3 text-sm font-semibold text-stone-800">任务 · {tasks.length}</div>
          {tasks.length === 0 ? (
            <EmptyState
              icon={<CalendarClock size={30} />}
              title="还没有持续任务"
              description="创建后，每个任务都会拥有独立的专属对话。"
              action={<Btn size="sm" onClick={() => setEditor('create')}>创建第一个任务</Btn>}
            />
          ) : (
            <div className="divide-y divide-stone-100">
              {tasks.map((task) => (
                <button
                  key={task.id}
                  type="button"
                  onClick={() => navigate(`/persistent-tasks/${encodeURIComponent(task.id)}`)}
                  className={`w-full px-4 py-3 text-left transition ${selectedId === task.id ? 'bg-primary-50' : 'hover:bg-stone-50'}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="truncate text-sm font-medium text-stone-800">{task.title}</span>
                    <Pill tone={task.state === 'active' ? 'success' : 'neutral'}>{task.state === 'active' ? '运行中' : '已暂停'}</Pill>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-stone-500">{task.instruction}</p>
                </button>
              ))}
            </div>
          )}
        </aside>

        <main className="min-w-0">
          {!selected ? (
            <div className="rounded-xl border border-stone-200 bg-white">
              <EmptyState icon={<Zap size={30} />} title="选择一个持续任务查看详情" />
            </div>
          ) : (
            <TaskDetail
              task={selected}
              loading={detailQuery.isFetching}
              busy={busy}
              admission={admission}
              triggers={triggersQuery.data ?? []}
              triggersLoading={triggersQuery.isLoading || triggersQuery.isFetching}
              triggersError={triggersQuery.error}
              onRetryTriggers={() => { void triggersQuery.refetch(); }}
              onEdit={() => setEditor('edit')}
              onStateChange={(state) => {
                void run(
                  () => changePersistentTaskState(selected, state, operationId()),
                  state === 'paused' ? '持续任务已暂停' : '持续任务已恢复',
                );
              }}
              onManual={() => setManualOpen(true)}
              onDelete={() => setDeleteTarget(selected)}
            />
          )}
        </main>
      </div>

      {editor && <TaskEditor
        key={editor === 'edit' ? selected?.id ?? 'edit' : 'create'}
        task={editor === 'edit' ? selected : null}
        busy={busy}
        onClose={() => setEditor(null)}
        onSave={async (definition) => {
          setBusy(true);
          try {
            const saved = editor === 'edit' && selected
              ? await updatePersistentTask(selected, definition, operationId())
              : await createPersistentTask(definition, operationId());
            await queryClient.invalidateQueries({ queryKey: TASKS_KEY });
            queryClient.setQueryData(['persistent-task', saved.id], saved);
            navigate(`/persistent-tasks/${encodeURIComponent(saved.id)}`);
            setEditor(null);
            toast.success(editor === 'edit' ? '持续任务已更新' : '持续任务已创建');
          } catch (error) {
            toast.error(extractErr(error));
          } finally {
            setBusy(false);
          }
        }}
      />}

      <Modal
        open={manualOpen}
        onClose={() => setManualOpen(false)}
        title="手动运行一次"
        width={560}
        footer={<>
          <Btn kind="ghost" onClick={() => setManualOpen(false)}>取消</Btn>
          <Btn
            loading={busy}
            disabled={!manualSummary.trim() || !selected}
            onClick={async () => {
              if (!selected) return;
              setBusy(true);
              try {
                const result = await triggerPersistentTask(selected.id, manualSummary.trim(), operationId());
                setAdmission(result);
                await queryClient.invalidateQueries({
                  queryKey: ['persistent-task', selected.id, 'triggers'],
                });
                setManualOpen(false);
                toast.success(admissionText(result));
              } catch (error) {
                toast.error(extractErr(error));
              } finally {
                setBusy(false);
              }
            }}
          >
            确认运行
          </Btn>
        </>}
      >
        <FormItem label="本次触发说明" hint="这只描述本次运行，不会修改任务定义。">
          <TextArea rows={4} value={manualSummary} onChange={(event) => setManualSummary(event.target.value)} />
        </FormItem>
      </Modal>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="删除这个持续任务？"
        description="任务定义、未运行的排队输入、触发历史和专属对话会被删除；已保存到产品其他位置的资产不会随之删除。若任务正在运行，服务端会拒绝本次删除，请先停止该次运行。"
        confirmText="删除任务"
        danger
        loading={busy}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (!deleteTarget) return;
          void (async () => {
            setBusy(true);
            try {
              await deletePersistentTask(deleteTarget, operationId());
              queryClient.removeQueries({ queryKey: ['persistent-task', deleteTarget.id] });
              await queryClient.invalidateQueries({ queryKey: TASKS_KEY });
              setDeleteTarget(null);
              setAdmission(null);
              navigate('/persistent-tasks');
              toast.success('持续任务已删除');
            } catch (error) {
              toast.error(extractErr(error, '持续任务删除失败'));
            } finally {
              setBusy(false);
            }
          })();
        }}
      />
    </div>
  );
}

function TaskDetail({
  task,
  loading,
  busy,
  admission,
  triggers,
  triggersLoading,
  triggersError,
  onRetryTriggers,
  onEdit,
  onStateChange,
  onManual,
  onDelete,
}: {
  task: PersistentTask;
  loading: boolean;
  busy: boolean;
  admission: PersistentTaskTriggerAdmission | null;
  triggers: PersistentTaskTrigger[];
  triggersLoading: boolean;
  triggersError: unknown;
  onRetryTriggers: () => void;
  onEdit: () => void;
  onStateChange: (state: 'active' | 'paused') => void;
  onManual: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold text-stone-800">{task.title}</h2>
              <Pill tone={task.state === 'active' ? 'success' : 'neutral'}>{task.state === 'active' ? '运行中' : '已暂停'}</Pill>
              <Pill>v{task.version}</Pill>
              {loading && <Spinner size={12} />}
            </div>
            <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-stone-700">{task.instruction}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to={`/persistent-tasks/${encodeURIComponent(task.id)}/conversation`}>
              <Btn kind="outline" size="sm" icon={<ExternalLink size={14} />}>打开专属对话</Btn>
            </Link>
            <Btn kind="outline" size="sm" icon={<Pencil size={14} />} onClick={onEdit}>编辑</Btn>
            {task.state === 'active' ? (
              <Btn kind="ghost" size="sm" icon={<CirclePause size={14} />} disabled={busy} onClick={() => onStateChange('paused')}>暂停未来运行</Btn>
            ) : (
              <Btn kind="ghost" size="sm" icon={<CirclePlay size={14} />} disabled={busy} onClick={() => onStateChange('active')}>恢复运行</Btn>
            )}
            <Btn size="sm" icon={<Zap size={14} />} disabled={busy || task.state !== 'active'} onClick={onManual}>手动运行一次</Btn>
          </div>
        </div>
      </section>

      {admission && (
        <div className="rounded-xl border border-primary-200 bg-primary-50 px-4 py-3 text-sm text-primary-800">
          {admissionText(admission)}
        </div>
      )}

      <section className="grid gap-4 md:grid-cols-2">
        <InfoCard title="触发条件">
          <div>{triggerText(task.trigger_spec_json)}</div>
          <div className="mt-1 text-[11px] text-stone-400">{task.trigger_kind === 'scheduled' ? '定时触发' : '外部事件触发'}</div>
        </InfoCard>
        <InfoCard title="更新时间">
          <div>{displayDate(task.updated_at)}</div>
          <div className="mt-1 text-[11px] text-stone-400">创建于 {displayDate(task.created_at)}</div>
        </InfoCard>
        <InfoCard title="下次计划运行">
          <div>{task.next_due_at ? displayDate(task.next_due_at) : '当前没有已计算的下次时间'}</div>
          {task.compensation_blocked_at && (
            <div className="mt-1 text-[11px] text-warning-700">
              本次停止后的补偿运行已阻止：{displayDate(task.compensation_blocked_at)}
            </div>
          )}
        </InfoCard>
        <InfoCard title="允许的云端只读 Tool">
          {task.allowed_tool_names_json.length
            ? <div className="flex flex-wrap gap-1.5">{task.allowed_tool_names_json.map((tool) => <Pill key={tool}>{tool}</Pill>)}</div>
            : <span>未授权任何 Tool</span>}
        </InfoCard>
        <InfoCard title="数据与动作范围">
          <div>读取：{task.read_scope_json.join('、') || '未声明'}</div>
          <div className="mt-1">动作：{task.action_scope_json.join('、') || '无'}</div>
        </InfoCard>
      </section>

      <TriggerHistory
        task={task}
        triggers={triggers}
        loading={triggersLoading}
        error={triggersError}
        onRetry={onRetryTriggers}
      />

      <section className="rounded-xl border border-stone-200 bg-stone-50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-stone-700">删除任务</h3>
            <p className="mt-1 text-xs text-stone-500">删除会清理任务、触发历史和专属对话；正在运行的任务需要先停止本次运行。</p>
          </div>
          <Btn kind="danger" size="sm" icon={<Trash2 size={14} />} disabled={busy} onClick={onDelete}>删除任务</Btn>
        </div>
      </section>
    </div>
  );
}

function triggerKindText(kind: PersistentTaskTrigger['kind']): string {
  if (kind === 'manual') return '手动';
  if (kind === 'scheduled') return '定时';
  return '外部事件';
}

function TriggerHistory({
  task,
  triggers,
  loading,
  error,
  onRetry,
}: {
  task: PersistentTask;
  triggers: PersistentTaskTrigger[];
  loading: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 shadow-xs">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <History size={16} className="shrink-0 text-stone-400" />
          <div>
            <h3 className="text-sm font-medium text-stone-800">触发历史</h3>
            <p className="mt-0.5 text-xs text-stone-500">这里记录任务何时被触发及是否已接纳为 Turn；具体过程和结果在专属对话中。</p>
          </div>
        </div>
        {loading && <Spinner size={14} />}
      </div>

      {error ? (
        <div className="mt-4 rounded-lg border border-danger-200 bg-danger-50 px-3 py-2 text-xs text-danger-700">
          <div>{extractErr(error, '触发历史加载失败')}</div>
          <Btn className="mt-2" kind="ghost" size="sm" onClick={onRetry}>重试</Btn>
        </div>
      ) : triggers.length === 0 && !loading ? (
        <div className="mt-4 rounded-lg bg-stone-50 px-3 py-4 text-center text-xs text-stone-500">暂无触发记录</div>
      ) : (
        <div className="mt-4 divide-y divide-stone-100 border-y border-stone-100">
          {triggers.map((trigger) => (
            <div key={trigger.id} className="py-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Pill>{triggerKindText(trigger.kind)}</Pill>
                    <span className="text-sm text-stone-700">{trigger.summary}</span>
                  </div>
                  <div className="mt-1 text-[11px] text-stone-400">
                    发生于 {displayDate(trigger.occurred_at)} · 系统于 {displayDate(trigger.observed_at)} 观察到
                  </div>
                </div>
                {trigger.admitted_turn_id ? (
                  <Link
                    className="shrink-0 text-xs text-primary-600 hover:text-primary-700"
                    to={`/persistent-tasks/${encodeURIComponent(task.id)}/conversation`}
                  >
                    已接纳为 Turn
                  </Link>
                ) : (
                  <span className="shrink-0 text-xs text-warning-700">等待接纳</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function InfoCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 text-sm text-stone-700 shadow-xs">
      <h3 className="mb-2 text-xs font-medium text-stone-500">{title}</h3>
      {children}
    </section>
  );
}

function TaskEditor({
  task,
  busy,
  onClose,
  onSave,
}: {
  task: PersistentTask | null;
  busy: boolean;
  onClose: () => void;
  onSave: (definition: PersistentTaskDefinitionInput) => Promise<void>;
}) {
  const [form, setForm] = useState<EditorForm>(() => task ? formFromTask(task) : blankForm());
  const toolsQuery = useQuery({
    queryKey: ['persistent-tasks', 'eligible-tools'],
    queryFn: listPersistentTaskEligibleTools,
  });
  const tools = toolsQuery.data ?? [];
  const eligibleNames = new Set(tools.map((tool) => tool.name));
  const unavailableNames = form.allowedToolNames.filter((name) => !eligibleNames.has(name));
  const update = <K extends keyof EditorForm>(key: K, value: EditorForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  const valid = Boolean(
    form.title.trim()
    && form.instruction.trim()
    && form.allowedToolNames.length
    && toolsQuery.isSuccess
    && unavailableNames.length === 0
    && form.triggerKind === 'scheduled'
    && form.schedule.trim()
    && form.timezone.trim(),
  );
  return (
    <Modal
      open
      onClose={onClose}
      title={task ? '编辑持续任务' : '新建持续任务'}
      width={760}
      footer={<>
        <Btn kind="ghost" onClick={onClose}>取消</Btn>
        <Btn loading={busy} disabled={!valid} onClick={() => { void onSave(definitionFromForm(form)); }}>{task ? '保存修改' : '创建任务'}</Btn>
      </>}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2"><FormItem label="任务名称"><TextInput autoFocus value={form.title} onChange={(event) => update('title', event.target.value)} /></FormItem></div>
        <div className="sm:col-span-2"><FormItem label="持续任务说明" hint="写清要检查什么、何时汇报；Agent 不会自行扩大范围。"><TextArea rows={5} value={form.instruction} onChange={(event) => update('instruction', event.target.value)} /></FormItem></div>
        <FormItem label="触发方式">
          <SelectInput value={form.triggerKind} onChange={(event) => update('triggerKind', event.target.value as EditorForm['triggerKind'])}>
            <option value="scheduled">定时触发</option>
            <option value="event" disabled>外部事件触发（尚未接入）</option>
          </SelectInput>
        </FormItem>
        {form.triggerKind === 'scheduled' ? <>
          <FormItem label="时区"><TextInput value={form.timezone} onChange={(event) => update('timezone', event.target.value)} /></FormItem>
          <div className="sm:col-span-2"><FormItem label="调度表达式" hint="当前服务接受调度表达式；例如工作日 9 点：0 9 * * 1-5"><TextInput value={form.schedule} onChange={(event) => update('schedule', event.target.value)} /></FormItem></div>
        </> : <div className="sm:col-span-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          外部事件入口尚未接入真实 Connector 事件流，因此当前不能创建或修改此类任务。
        </div>}
        <div className="sm:col-span-2">
          <FormItem label="允许的云端只读 Tool" hint="无人值守阶段只能使用这里明确列出的只读能力。">
            <div className="grid gap-2 rounded-lg border border-stone-200 bg-stone-50 p-3 sm:grid-cols-2">
              {toolsQuery.isLoading && <div className="col-span-2 flex items-center gap-2 text-xs text-stone-500"><Spinner size={13} />正在读取当前可用 Tool…</div>}
              {toolsQuery.isError && <div role="alert" className="col-span-2 text-xs text-danger-700">{extractErr(toolsQuery.error, '当前可用 Tool 读取失败')}</div>}
              {toolsQuery.isSuccess && tools.length === 0 && <div className="col-span-2 text-xs text-stone-500">当前部署没有可用于无人值守任务的云端只读 Tool。</div>}
              {tools.map((tool: PersistentTaskEligibleTool) => (
                <label key={tool.name} title={tool.description} className="flex items-center gap-2 text-xs text-stone-700">
                  <input
                    type="checkbox"
                    checked={form.allowedToolNames.includes(tool.name)}
                    onChange={(event) => update('allowedToolNames', event.target.checked
                      ? [...form.allowedToolNames, tool.name]
                      : form.allowedToolNames.filter((name) => name !== tool.name))}
                  />
                  <span>{TOOL_LABELS[tool.name] ?? tool.description}</span><span className="font-mono text-[10px] text-stone-400">{tool.name}</span>
                </label>
              ))}
              {unavailableNames.map((name) => (
                <label key={name} className="col-span-2 flex items-center gap-2 text-xs text-danger-700">
                  <input
                    type="checkbox"
                    checked
                    onChange={() => update('allowedToolNames', form.allowedToolNames.filter((value) => value !== name))}
                  />
                  <span>已保存但当前不可用；取消选择后才能保存</span>
                  <span className="font-mono text-[10px]">{name}</span>
                </label>
              ))}
            </div>
          </FormItem>
        </div>
        <FormItem label="读取范围" hint="可选，逗号分隔的业务范围说明"><TextArea rows={2} value={form.readScope} onChange={(event) => update('readScope', event.target.value)} /></FormItem>
        <FormItem label="动作范围" hint="当前只读 Tool 通常留空"><TextArea rows={2} value={form.actionScope} onChange={(event) => update('actionScope', event.target.value)} /></FormItem>
      </div>
    </Modal>
  );
}

export function PersistentTaskConversationPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const taskQuery = useQuery({
    queryKey: ['persistent-task', taskId],
    queryFn: () => getPersistentTask(taskId!),
    enabled: Boolean(taskId),
  });
  if (taskQuery.isLoading) return <div className="flex items-center gap-2 p-6 text-sm text-stone-500"><Spinner size={15} />正在打开专属对话…</div>;
  if (!taskQuery.data) return <div className="p-6"><EmptyState icon={<CalendarClock size={30} />} title="无法打开专属对话" description={extractErr(taskQuery.error)} /></div>;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-stone-200 bg-white px-4 py-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-stone-800">{taskQuery.data.title}</div>
          <div className="text-[11px] text-stone-400">持续任务专属对话</div>
        </div>
        <Link to={`/persistent-tasks/${encodeURIComponent(taskQuery.data.id)}`}><Btn kind="ghost" size="sm">返回任务详情</Btn></Link>
      </div>
      <div className="flex min-h-0 flex-1">
        <ChatPanel
          sessionId={taskQuery.data.conversation_id}
          sessionTitle={`自动化 · ${taskQuery.data.title}`}
          fixedMode="AGENT"
          flexible
        />
      </div>
    </div>
  );
}
