import { useMemo, useState } from 'react';
import { Link2, MessageCircleQuestion, MonitorCheck, ShieldCheck, X } from 'lucide-react';
import { resolveAgentInteraction } from '@/api/chat';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { TextArea } from '@/pages/career/CareerFields';
import { toast } from '@/store/uiStore';
import type {
  AgentInteraction,
  ClarificationInteraction,
  ConnectionInteraction,
} from '@/types/api';

type ResolutionStatus = 'resolved' | 'rejected' | 'cancelled';

function providerLabel(interaction: ConnectionInteraction): string {
  const explicit = interaction.request.provider;
  if (typeof explicit === 'string' && explicit.trim()) return explicit;
  const tool = String(interaction.request.tool_name ?? '');
  if (tool.startsWith('gmail_')) return 'Gmail';
  return '外部服务';
}

function clarificationOptions(interaction: ClarificationInteraction) {
  return (interaction.request.options ?? []).map((option) => (
    typeof option === 'string'
      ? { value: option, label: option, description: '' }
      : {
          value: option.value,
          label: option.label ?? option.value,
          description: option.description ?? '',
        }
  ));
}

export function InteractionCard({
  sessionId,
  turnId,
  interaction,
  onResolved,
}: {
  sessionId: string;
  turnId: string;
  interaction: AgentInteraction;
  onResolved: (cancelled: boolean) => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [answer, setAnswer] = useState('');
  const options = useMemo(
    () => interaction.kind === 'clarification' ? clarificationOptions(interaction) : [],
    [interaction],
  );

  const resolve = async (
    status: ResolutionStatus,
    resolution: Record<string, unknown>,
  ) => {
    if (submitting) return;
    setSubmitting(true);
    try {
      const response = await resolveAgentInteraction(
        sessionId,
        turnId,
        interaction.id,
        { expected_version: interaction.version, status, resolution },
      );
      onResolved(response.turn_status === 'cancelled');
    } catch (error) {
      toast.error(extractErr(error, '操作未能提交'));
    } finally {
      setSubmitting(false);
    }
  };

  if (interaction.kind === 'clarification') {
    const question = String(
      interaction.request.question ?? interaction.request.prompt ?? 'Agent 需要你补充一项信息。',
    );
    return (
      <InteractionShell icon={MessageCircleQuestion} title="需要你补充信息">
        <p className="text-xs leading-relaxed text-stone-600">{question}</p>
        {options.length > 0 && (
          <div className="mt-2 grid gap-1.5">
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                disabled={submitting}
                onClick={() => setAnswer(option.value)}
                className={`rounded-lg border px-3 py-2 text-left text-xs transition ${answer === option.value ? 'border-primary-300 bg-primary-50 text-primary-800' : 'border-stone-200 bg-white text-stone-700 hover:border-primary-200'}`}
              >
                <span className="font-medium">{option.label}</span>
                {option.description && <span className="mt-0.5 block text-[11px] text-stone-500">{option.description}</span>}
              </button>
            ))}
          </div>
        )}
        <div className="mt-2">
          <TextArea
            aria-label="补充信息"
            rows={2}
            value={answer}
            disabled={submitting}
            placeholder={options.length ? '也可以输入其他回答' : '请输入回答'}
            onChange={(event) => setAnswer(event.target.value)}
          />
        </div>
        <Actions>
          <Btn
            size="sm"
            loading={submitting}
            disabled={!answer.trim()}
            onClick={() => { void resolve('resolved', { answer: answer.trim() }); }}
          >
            提交回答
          </Btn>
          <Btn
            kind="outline"
            size="sm"
            disabled={submitting}
            onClick={() => { void resolve('rejected', { reason: 'user_declined_clarification' }); }}
          >
            不再继续
          </Btn>
        </Actions>
      </InteractionShell>
    );
  }

  if (interaction.kind === 'connection') {
    const provider = providerLabel(interaction);
    const reason = String(interaction.request.reason ?? 'connection_required');
    return (
      <InteractionShell icon={Link2} title={`需要连接 ${provider}`}>
        <p className="text-xs leading-relaxed text-stone-600">
          原调用会保持在当前任务中。请到“设置与连接”查看真实连接状态，再回来重新检查。
        </p>
        <p className="mt-1 font-mono text-[10px] text-stone-400">{reason}</p>
        <Actions>
          <a
            href="/plugins?plugin=gmail"
            className="inline-flex items-center justify-center rounded-md border border-primary-300 bg-white px-3 py-1.5 text-xs font-medium text-primary-700 hover:bg-primary-50"
          >
            打开设置与连接
          </a>
          <Btn
            size="sm"
            loading={submitting}
            onClick={() => {
              void resolve('resolved', {
                connection_status: 'ready',
                provider: provider.toLowerCase(),
              });
            }}
          >
            重新检查连接
          </Btn>
          <Btn
            kind="ghost"
            size="sm"
            disabled={submitting}
            onClick={() => { void resolve('rejected', { connection_status: 'declined' }); }}
          >
            暂不连接
          </Btn>
        </Actions>
      </InteractionShell>
    );
  }

  if (interaction.kind === 'client_readiness') {
    const requirement = String(
      interaction.request.requirement ?? interaction.request.action ?? '需要当前设备和页面准备就绪。',
    );
    return (
      <InteractionShell icon={MonitorCheck} title="等待当前设备准备">
        <p className="text-xs leading-relaxed text-stone-600">{requirement}</p>
        <Actions>
          <Btn
            size="sm"
            loading={submitting}
            onClick={() => { void resolve('resolved', { ready: true }); }}
          >
            已准备好
          </Btn>
          <Btn
            kind="outline"
            size="sm"
            disabled={submitting}
            onClick={() => { void resolve('rejected', { ready: false, reason: 'user_not_ready' }); }}
          >
            当前无法完成
          </Btn>
        </Actions>
      </InteractionShell>
    );
  }

  const toolName = String(interaction.request.tool_name ?? interaction.request.action ?? '当前操作');
  const args = interaction.request.arguments;
  return (
    <InteractionShell icon={ShieldCheck} title="需要批准具体操作">
      <p className="text-xs leading-relaxed text-stone-600">
        Agent 准备执行 <span className="font-medium text-stone-800">{toolName}</span>。批准只适用于这里展示的本次调用。
      </p>
      {args && Object.keys(args).length > 0 && (
        <pre className="mt-2 max-h-28 overflow-auto rounded-lg border border-stone-200 bg-white p-2 font-mono text-[10px] text-stone-600">
          {JSON.stringify(args, null, 2)}
        </pre>
      )}
      {typeof interaction.request.reason === 'string' && (
        <p className="mt-1 font-mono text-[10px] text-stone-400">{interaction.request.reason}</p>
      )}
      <Actions>
        <Btn
          size="sm"
          loading={submitting}
          onClick={() => { void resolve('resolved', { decision: 'approved' }); }}
        >
          批准本次操作
        </Btn>
        <Btn
          kind="outline"
          size="sm"
          disabled={submitting}
          onClick={() => { void resolve('rejected', { decision: 'rejected' }); }}
        >
          拒绝
        </Btn>
      </Actions>
    </InteractionShell>
  );
}

function InteractionShell({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof X;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mx-3 mb-2 rounded-xl border border-warning-200 bg-warning-50 p-3" aria-label={title}>
      <div className="flex items-start gap-2">
        <Icon size={16} className="mt-0.5 shrink-0 text-warning-700" />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium text-stone-800">{title}</h3>
          <div className="mt-1">{children}</div>
        </div>
      </div>
    </section>
  );
}

function Actions({ children }: { children: React.ReactNode }) {
  return <div className="mt-3 flex flex-wrap items-center gap-2">{children}</div>;
}
