import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, SlidersHorizontal, Trash2 } from 'lucide-react';
import { getMe, updateMe } from '@/api/auth';
import { getCopilotPreference, updateCopilotPreference } from '@/api/personalization';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { EmptyState } from '@/components/ui/EmptyState';
import { Spinner } from '@/components/ui/Spinner';
import { FormItem, TextArea } from '@/pages/career/CareerFields';
import { toast } from '@/store/uiStore';
import type { CopilotPreference } from '@/types/personalization';
import { AgentMemorySettingsSection } from './AgentMemorySettingsSection';

const PREFERENCE_KEY = ['personalization', 'copilot-preference'] as const;
const PROFILE_KEY = ['auth', 'me'] as const;
type ExecutionMode = 'standard' | 'auto';

function normalizedInstructions(values: string[]): string[] {
  const result: string[] = [];
  for (const value of values) {
    const item = value.trim();
    if (item && !result.includes(item)) result.push(item);
  }
  return result;
}

function isConflict(error: unknown): boolean {
  return (error as { response?: { status?: number } })?.response?.status === 409;
}

export function CopilotPreferencesPage() {
  const profileQuery = useQuery({
    queryKey: PROFILE_KEY,
    queryFn: getMe,
  });
  const preferenceQuery = useQuery({
    queryKey: PREFERENCE_KEY,
    queryFn: getCopilotPreference,
  });

  return (
    <div className="mx-auto max-w-4xl space-y-5 p-4 md:p-6">
      <header>
        <h1 className="text-xl font-semibold text-stone-800">个性化设置</h1>
        <p className="mt-1 text-sm text-stone-500">分别管理新对话的执行默认值，以及跨对话生效的协作规则。</p>
      </header>

      {profileQuery.isLoading ? (
        <section className="flex items-center gap-2 rounded-xl border border-stone-200 bg-white p-5 text-sm text-stone-500 shadow-xs">
          <Spinner size={15} />正在读取默认执行模式…
        </section>
      ) : profileQuery.data ? (
        <ExecutionModeForm
          key={profileQuery.data.default_execution_mode}
          initialMode={profileQuery.data.default_execution_mode}
        />
      ) : (
        <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
          <EmptyState
            icon={<SlidersHorizontal size={30} />}
            title="默认执行模式暂时无法读取"
            description={extractErr(profileQuery.error)}
            action={<Btn size="sm" onClick={() => profileQuery.refetch()}>重试</Btn>}
          />
        </section>
      )}

      {preferenceQuery.isLoading ? (
        <section className="flex items-center gap-2 rounded-xl border border-stone-200 bg-white p-5 text-sm text-stone-500 shadow-xs">
          <Spinner size={15} />正在读取协作偏好…
        </section>
      ) : preferenceQuery.data ? (
        <PreferenceForm key={preferenceQuery.data.version} preference={preferenceQuery.data} />
      ) : (
        <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
        <EmptyState
          icon={<SlidersHorizontal size={30} />}
          title="协作偏好暂时无法读取"
          description={extractErr(preferenceQuery.error)}
          action={<Btn size="sm" onClick={() => preferenceQuery.refetch()}>重试</Btn>}
        />
        </section>
      )}

      <AgentMemorySettingsSection />
    </div>
  );
}

function ExecutionModeForm({ initialMode }: { initialMode: ExecutionMode }) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<ExecutionMode>(initialMode);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const saved = await updateMe({ default_execution_mode: mode });
      queryClient.setQueryData(PROFILE_KEY, saved);
      toast.success('新对话默认执行模式已保存');
    } catch (error) {
      toast.error(extractErr(error, '默认执行模式保存失败'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
      <div>
        <h2 className="text-sm font-semibold text-stone-800">新对话默认执行模式</h2>
        <p className="mt-1 text-xs leading-relaxed text-stone-500">
          新建 Conversation 时由云端继承此设置。当前对话仍可在聊天工具栏单独切换，修改这里不会改变已有对话或持续任务。
        </p>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className={`cursor-pointer rounded-lg border p-4 transition ${mode === 'standard' ? 'border-primary-300 bg-primary-50' : 'border-stone-200 hover:bg-stone-50'}`}>
          <div className="flex items-center gap-2 text-sm font-medium text-stone-800">
            <input
              type="radio"
              name="default-execution-mode"
              value="standard"
              checked={mode === 'standard'}
              onChange={() => setMode('standard')}
            />
            Standard
          </div>
          <p className="mt-2 text-xs leading-relaxed text-stone-500">只读与推理可在授权范围内直接进行；普通外部副作用在执行前请求确认。</p>
        </label>
        <label className={`cursor-pointer rounded-lg border p-4 transition ${mode === 'auto' ? 'border-warning-300 bg-warning-50' : 'border-stone-200 hover:bg-stone-50'}`}>
          <div className="flex items-center gap-2 text-sm font-medium text-stone-800">
            <input
              type="radio"
              name="default-execution-mode"
              value="auto"
              checked={mode === 'auto'}
              onChange={() => setMode('auto')}
            />
            Auto
          </div>
          <p className="mt-2 text-xs leading-relaxed text-stone-500">在当前任务明确的对象、内容与授权范围内减少普通审批；风险、歧义和保留决定仍会询问。</p>
        </label>
      </div>
      <div className="mt-4 flex justify-end">
        <Btn loading={saving} disabled={mode === initialMode} onClick={() => { void save(); }}>保存默认模式</Btn>
      </div>
    </section>
  );
}

function PreferenceForm({ preference }: { preference: CopilotPreference }) {
  const queryClient = useQueryClient();
  const [values, setValues] = useState(
    preference.instructions.length > 0 ? preference.instructions : [''],
  );
  const [saving, setSaving] = useState(false);
  const [version, setVersion] = useState(preference.version);
  const instructions = normalizedInstructions(values);
  const dirty = JSON.stringify(instructions) !== JSON.stringify(preference.instructions);

  const save = async () => {
    if (instructions.length > 20) {
      toast.error('全局协作规则最多 20 条');
      return;
    }
    setSaving(true);
    try {
      const saved = await updateCopilotPreference(version, instructions);
      queryClient.setQueryData(PREFERENCE_KEY, saved);
      toast.success('全局协作偏好已保存');
    } catch (error) {
      if (isConflict(error)) {
        const latest = await getCopilotPreference();
        setVersion(latest.version);
        toast.error('协作偏好已在其他页面更新；已刷新版本，你的草稿仍保留，请再次保存');
      } else {
        toast.error(extractErr(error, '协作偏好保存失败'));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
      <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
        <div className="mb-4">
          <h2 className="text-sm font-semibold text-stone-800">全局协作偏好</h2>
          <p className="mt-1 text-xs leading-relaxed text-stone-500">
            这些是你明确设置、跨对话生效的协作规则。它们不是个人事实、长期记忆、Tool 授权或执行模式。
          </p>
        </div>
        <FormItem label="规则" hint="最多 20 条；每条可以包含多行。更具体的复盘或对话指导可以覆盖全局规则。">
          <div className="space-y-3">
            {values.map((value, index) => (
              <div key={index} className="flex items-start gap-2">
                <TextArea
                  aria-label={`全局协作规则 ${index + 1}`}
                  rows={3}
                  maxLength={1000}
                  value={value}
                  placeholder={index === 0 ? '例如：先给结论，再解释关键原因' : '输入一条明确的协作规则'}
                  onChange={(event) => setValues((current) => current.map(
                    (item, itemIndex) => itemIndex === index ? event.target.value : item,
                  ))}
                />
                <Btn
                  kind="ghost"
                  size="sm"
                  icon={<Trash2 size={13} />}
                  aria-label={`删除全局协作规则 ${index + 1}`}
                  onClick={() => setValues((current) => (
                    current.length === 1 ? [''] : current.filter((_, itemIndex) => itemIndex !== index)
                  ))}
                />
              </div>
            ))}
            <Btn
              kind="outline"
              size="sm"
              icon={<Plus size={13} />}
              disabled={values.length >= 20}
              onClick={() => setValues((current) => [...current, ''])}
            >
              添加规则
            </Btn>
          </div>
        </FormItem>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <span className={`text-xs ${instructions.length > 20 ? 'text-danger-600' : 'text-stone-400'}`}>
            {instructions.length}/20 条 · v{version}
          </span>
          <Btn loading={saving} disabled={!dirty || instructions.length > 20} onClick={() => { void save(); }}>
            保存全局规则
          </Btn>
        </div>
      </section>
  );
}
