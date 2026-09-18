import { useRef, useState } from 'react';
import { resolveAgentInteraction } from '@/api/chat';
import { extractErr } from '@/api/client';
import type { FactConfirmationInteraction } from '@/types/api';
import type { OpportunityResolution } from '@/api/interviewInvitations';
import { checkedFacts, InvitationFields, invitationDraft } from './InvitationFields';

export function FactConfirmationCard({ sessionId, turnId, interaction, onResolved }: {
  sessionId: string; turnId: string; interaction: FactConfirmationInteraction;
  onResolved: (cancelled: boolean) => void;
}) {
  const request = interaction.request;
  const [draft, setDraft] = useState(() => invitationDraft(request.invitation_facts));
  const [selection, setSelection] = useState('');
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const busy = useRef(false);
  const attempt = useRef<{ fingerprint: string; identity: string } | null>(null);
  const compatible = interaction.schema_version === 1
    && request.protocol === 'interview_invitation.fact_confirmation.v1'
    && request.expected_candidate_version === request.candidate_reference?.version;
  const decide = async (decision: 'confirm' | 'correct_and_confirm' | 'reject') => {
    if (busy.current || !compatible) return;
    try {
      let opportunity: OpportunityResolution | undefined;
      if (decision !== 'reject') {
        if (selection === 'new') opportunity = { kind: 'create_new' };
        else {
          const candidate = request.opportunity_match_options?.find((option) => option.opportunity_id === selection);
          if (!candidate) throw new Error('请明确选择关联机会或创建新机会');
          opportunity = { kind: 'link_existing', opportunity_id: candidate.opportunity_id, expected_version: candidate.expected_version };
        }
      }
      const resolution: Record<string, unknown> = { protocol: request.protocol, decision,
        ...(opportunity ? { opportunity } : {}),
        ...(decision === 'correct_and_confirm' ? { corrected_facts: checkedFacts(draft) } : {}) };
      const fingerprint = JSON.stringify(resolution);
      if (!attempt.current || attempt.current.fingerprint !== fingerprint) attempt.current = { fingerprint, identity: crypto.randomUUID() };
      busy.current = true; setPending(true); setError('');
      const result = await resolveAgentInteraction(sessionId, turnId, interaction.id, {
        expected_version: interaction.version, status: decision === 'reject' ? 'rejected' : 'resolved',
        resolution_identity: attempt.current.identity, resolution,
      });
      onResolved(result.turn_status === 'cancelled');
    } catch (err) { setError(extractErr(err, '决定尚未提交，请刷新当前状态或重试')); }
    finally { busy.current = false; setPending(false); }
  };
  if (!compatible) return <section role="alert" className="m-3 rounded-xl border p-4">该事实确认协议暂不兼容，请刷新后处理；没有批准任何操作。</section>;
  return <section aria-label="确认面试邀请事实" className="m-3 space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
    <h3 className="font-semibold">确认面试邀请事实</h3>
    <p className="text-sm">这是待确认提取，不是已经发生的业务变更。确认会更新本产品内的机会与面试，不会发送邮件或接受外部邀约。</p>
    <p>来源：{request.source_and_evidence_references?.map((source) => `${source.kind}: ${source.identity}`).join('；') || '未提供'}</p>
    {!!request.conflicts?.length && <p role="note">冲突：{request.conflicts.join('；')}</p>}
    {!!request.missing_or_uncertain_fields?.length && <p role="note">待核对：{request.missing_or_uncertain_fields.join('；')}</p>}
    {editing ? <InvitationFields value={draft} onChange={setDraft} disabled={pending} />
      : <dl className="text-sm">{Object.entries(request.invitation_facts).map(([key, value]) => <div key={key} className="flex flex-wrap gap-2"><dt>{key}</dt><dd>{value || '未提供'}</dd></div>)}</dl>}
    <label className="grid gap-1 text-sm">关联求职机会<select value={selection} disabled={pending} onChange={(event) => setSelection(event.target.value)} className="rounded-lg border bg-white p-2">
      <option value="">请明确选择</option><option value="new">创建新的求职机会</option>
      {request.opportunity_match_options?.map((option) => <option key={option.opportunity_id} value={option.opportunity_id}>{option.company_name} · {option.job_title} · {option.current_step}</option>)}
    </select></label>
    {error && <p role="alert">{error}</p>}
    <div className="flex flex-wrap gap-3 text-sm">
      <button disabled={pending} onClick={() => setEditing(!editing)}>{editing ? '取消更正' : '更正提取事实'}</button>
      <button disabled={pending || !selection || (!editing && !!request.missing_or_uncertain_fields?.length)} onClick={() => { void decide(editing ? 'correct_and_confirm' : 'confirm'); }}>
        {pending ? '提交中…' : editing ? '更正并确认' : '确认这些事实'}
      </button>
      <button disabled={pending} onClick={() => { void decide('reject'); }}>拒绝这条提取</button>
    </div>
  </section>;
}
