import { useRef, useState } from 'react';
import { isAxiosError } from 'axios';
import { confirmInvitation, type ConfirmInvitationCommand, type ConfirmInvitationResult } from '@/api/interviewInvitations';
import { extractErr } from '@/api/client';
import { checkedFacts, invitationDraft, InvitationFields } from './InvitationFields';

/** A timeout retries the exact command, including assertion time and identity. */
export function ManualInvitationForm({ onConfirmed }: { onConfirmed: (result: ConfirmInvitationResult) => void }) {
  const [draft, setDraft] = useState(invitationDraft);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const command = useRef<ConfirmInvitationCommand | null>(null);
  const busy = useRef(false);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy.current) return;
    try {
      if (!command.current) {
        const facts = checkedFacts(draft);
        const id = crypto.randomUUID();
        command.current = { schema_version: 1, idempotency_key: `manual-invitation:${id}`,
          actor_kind: 'user', asserted_at: new Date().toISOString(), facts,
          confirmation_basis: { kind: 'explicit_user_assertion', source: { kind: 'manual', identity: id } },
          opportunity: { kind: 'create_new' } };
      }
      busy.current = true; setPending(true); setError('');
      const result = await confirmInvitation(command.current);
      if (!['verified', 'reconciled'].includes(result.verification.conclusion)
        || result.verification.operation_id !== result.operation_id) throw new Error('操作尚未核实，请勿重复创建另一份邀请');
      command.current = null; setUncertain(false); setDraft(invitationDraft()); onConfirmed(result);
    } catch (err) {
      // A rejection on the first attempt proves no operation committed. A later
      // rejection cannot settle an earlier lost response (e.g. permission revoked).
      // Once uncertain, preserve the original identity until a verified receipt.
      if (!uncertain && isAxiosError(err) && [403, 404, 422].includes(err.response?.status ?? 0)) {
        command.current = null;
      }
      setUncertain(command.current !== null);
      setError(extractErr(err, '暂未取得确认收据；可用同一请求重试'));
    } finally { busy.current = false; setPending(false); }
  };
  return <form onSubmit={(event) => { void submit(event); }} className="space-y-4 rounded-xl border bg-white p-5" aria-label="记录面试邀请">
    <h2 className="text-lg font-semibold">记录已确认的面试邀请</h2>
    <p className="text-sm text-stone-600">下面是你明确提供的事实。保存会创建关联求职机会和面试，不会发送邮件、创建外部日程或替你接受建议。</p>
    <InvitationFields value={draft} onChange={setDraft} disabled={pending || uncertain} />
    {error && <p role="alert">{error}</p>}
    {uncertain && <p className="text-sm">结果尚未确认，原始请求已保留。重试使用同一身份，不会改写参数。</p>}
    <button type="submit" disabled={pending} className="rounded-lg bg-stone-800 px-4 py-2 text-white">
      {pending ? '正在核实…' : uncertain ? '重试并核实原请求' : '确认并保存面试'}
    </button>
  </form>;
}
