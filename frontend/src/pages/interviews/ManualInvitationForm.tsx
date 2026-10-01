import { useEffect, useRef, useState } from 'react';
import { isAxiosError } from 'axios';
import {
  cancelInvitationSubmission, confirmInvitation, getInvitationSubmission,
  resumeInvitationSubmission, type ConfirmInvitationCommand, type ConfirmInvitationResult,
} from '@/api/interviewInvitations';
import { extractErr } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { checkedFacts, invitationDraft, InvitationFields } from './InvitationFields';

// No company/contact/JD/source payload is written to browser storage. The
// server owns the immutable command; the browser keeps only its random key.
export function invitationStorageKey(owner: string): string {
  return `ic:invitation-submission:v1:${encodeURIComponent(owner)}`;
}
function retainedKey(owner: string): string | null {
  try { return sessionStorage.getItem(invitationStorageKey(owner)); }
  catch { return null; }
}

export function ManualInvitationForm({ onConfirmed }: { onConfirmed: (result: ConfirmInvitationResult) => void }) {
  const owner = useAuthStore((s) => s.subjectId);
  return owner ? <OwnedInvitationForm key={owner} owner={owner} onConfirmed={onConfirmed} />
    : <p role="alert">请登录后记录面试邀请。</p>;
}

function OwnedInvitationForm({ owner, onConfirmed }: {
  owner: string; onConfirmed: (result: ConfirmInvitationResult) => void;
}) {
  const [draft, setDraft] = useState(invitationDraft);
  const [recoveryKey] = useState(() => retainedKey(owner));
  const [pending, setPending] = useState(Boolean(recoveryKey));
  const [error, setError] = useState('');
  const key = useRef<string | null>(recoveryKey);
  const [uncertain, setUncertain] = useState(recoveryKey !== null);
  const command = useRef<ConfirmInvitationCommand | null>(null);
  const busy = useRef(Boolean(recoveryKey));
  const mounted = useRef(true);
  const callback = useRef(onConfirmed);
  useEffect(() => { callback.current = onConfirmed; }, [onConfirmed]);
  const release = (resetDraft = true) => {
    if (sessionStorage.getItem(invitationStorageKey(owner)) === key.current) {
      sessionStorage.removeItem(invitationStorageKey(owner));
    }
    command.current = null; key.current = null;
    setUncertain(false); if (resetDraft) setDraft(invitationDraft());
  };
  const accept = (result: ConfirmInvitationResult) => {
    if (!['verified', 'reconciled'].includes(result.verification.conclusion)
      || result.verification.operation_id !== result.operation_id) throw new Error('操作尚未核实，请勿重复创建另一份邀请');
    release(); callback.current(result);
  };
  useEffect(() => {
    mounted.current = true;
    const originalKey = recoveryKey;
    if (originalKey) {
      busy.current = true;
      // Recovery is a read. Loading a page must never replay a write itself.
      void getInvitationSubmission(originalKey).then((receipt) => {
        if (!mounted.current || key.current !== originalKey) return;
        if (receipt.idempotency_key !== originalKey) throw new Error('收据身份不匹配');
        if (receipt.status === 'committed' && receipt.result) {
          if (!['verified', 'reconciled'].includes(receipt.result.verification.conclusion)
            || receipt.result.verification.operation_id !== receipt.result.operation_id) throw new Error('原请求尚未核实');
          sessionStorage.removeItem(invitationStorageKey(owner));
          key.current = null; setUncertain(false); callback.current(receipt.result);
        } else if (['cancelled', 'rejected'].includes(receipt.status)) {
          sessionStorage.removeItem(invitationStorageKey(owner));
          key.current = null; setUncertain(false);
          setError('原请求已被明确取消或拒绝，可以重新填写。');
        } else {
          command.current = receipt.command;
          if (receipt.command) setDraft(invitationDraft(receipt.command.facts));
          setError(receipt.status === 'not_received'
            ? '暂未查到原请求；它可能仍在传输。请核实或先取消原请求，勿重复创建。'
            : '已恢复原始请求，请继续核实或明确取消。');
        }
      }).catch((err: unknown) => {
        if (mounted.current) setError(extractErr(err, '暂时无法核实原请求；原身份已保留。'));
      }).finally(() => { if (mounted.current) { busy.current = false; setPending(false); } });
    }
    return () => { mounted.current = false; };
  }, [owner, recoveryKey]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy.current) return;
    const wasUncertain = uncertain;
    try {
      if (!key.current) {
        const facts = checkedFacts(draft);
        const id = crypto.randomUUID();
        const next: ConfirmInvitationCommand = {
          schema_version: 1, idempotency_key: `manual-invitation:${id}`,
          actor_kind: 'user', asserted_at: new Date().toISOString(), facts,
          confirmation_basis: { kind: 'explicit_user_assertion', source: { kind: 'manual', identity: id } },
          opportunity: { kind: 'create_new' },
        };
        // Fail BEFORE sending when a recoverable identity cannot be retained.
        sessionStorage.setItem(invitationStorageKey(owner), next.idempotency_key);
        key.current = next.idempotency_key; command.current = next;
      }
      busy.current = true; setPending(true); setError('');
      const result = command.current ? await confirmInvitation(command.current)
        : await resumeInvitationSubmission(key.current);
      if (mounted.current) accept(result);
    } catch (err) {
      if (!mounted.current) return;
      // A later 403/404/422 never settles an earlier response-lost request.
      if (!wasUncertain && isAxiosError(err) && [403, 404, 422].includes(err.response?.status ?? 0)) release(false);
      setUncertain(key.current !== null);
      setError(extractErr(err, '暂未取得确认收据；原请求编号已保留，可安全核实'));
    } finally { if (mounted.current) { busy.current = false; setPending(false); } }
  };
  const cancel = async () => {
    if (busy.current || !key.current) return;
    busy.current = true; setPending(true); setError('');
    try {
      const receipt = await cancelInvitationSubmission(key.current);
      if (!mounted.current) return;
      if (receipt.idempotency_key !== key.current) throw new Error('收据身份不匹配');
      if (receipt.status === 'committed' && receipt.result) accept(receipt.result);
      else if (receipt.status === 'cancelled') release();
      else throw new Error('尚未确认取消，原请求仍被保留。');
    } catch (err) { if (mounted.current) setError(extractErr(err, '取消结果未知，请再次核实原请求。')); }
    finally { if (mounted.current) { busy.current = false; setPending(false); } }
  };
  return <form onSubmit={(event) => { void submit(event); }} className="space-y-4 rounded-xl border bg-white p-5" aria-label="记录面试邀请">
    <h2 className="text-lg font-semibold">记录已确认的面试邀请</h2>
    <p className="text-sm text-stone-600">下面是你明确提供的事实。保存会创建关联求职机会和面试，不会发送邮件、创建外部日程或替你接受建议。</p>
    <InvitationFields value={draft} onChange={setDraft} disabled={pending || uncertain} />
    {error && <p role="alert">{error}</p>}
    {uncertain && <p className="text-sm">原请求编号已保留，刷新后可核实。未取得收据不代表没有成功。</p>}
    <button type="submit" disabled={pending} className="rounded-lg bg-stone-800 px-4 py-2 text-white">
      {pending ? '正在核实…' : uncertain ? '重试并核实原请求' : '确认并保存面试'}
    </button>
    {uncertain && <button type="button" disabled={pending} className="ml-3 text-sm" onClick={() => { void cancel(); }}>取消原请求并重新填写</button>}
  </form>;
}
