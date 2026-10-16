import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { extractErr } from '@/api/client';
import { confirmInvitation, getInvitationSubmission, resumeInvitationSubmission, cancelInvitationSubmission, type ConfirmInvitationCommand, type InvitationFacts } from '@/api/interviewInvitations';
import { useAuthStore } from '@/store/authStore';
import { Btn } from '@/components/ui/Btn';
import { localDateTimeFromIso } from './CareerFields';
import { useRefreshCareer } from './useCareerWorkspace';

/** Explicit user input enters the same verified Operation as Agent intake. */
export function ManualInvitationForm({ onSaved, opportunity, interview }: { onSaved: () => void; opportunity?: { id: string; company_name: string; job_title: string; version: number }; interview?: { id: string; schedule_version: number; scheduled_start_at: string | null; scheduled_location: string | null; stage_label: string | null } }) {
  const [company, setCompany] = useState(opportunity?.company_name ?? '');
  const [role, setRole] = useState(opportunity?.job_title ?? '');
  const [start, setStart] = useState(interview?.scheduled_start_at ? localDateTimeFromIso(interview.scheduled_start_at) : '');
  const [location, setLocation] = useState(interview?.scheduled_location ?? '');
  const [label, setLabel] = useState(interview?.stage_label ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const refreshCareer = useRefreshCareer();
  const queryClient = useQueryClient();
  const user = useAuthStore(s => s.subjectId);
  const storageKey = `invitation-submission:${user}:${opportunity?.id ?? 'new'}:${interview?.id ?? 'new'}`;
  const [submissionKey, setSubmissionKey] = useState<string | null>(() => {
    try { return localStorage.getItem(storageKey); } catch { return null; }
  });
  const inFlight = useRef(false);
  const receipt = useQuery({ queryKey: ['invitation-submission', user, submissionKey], queryFn: () => getInvitationSubmission(submissionKey!), enabled: Boolean(submissionKey), retry: false });
  const clearSubmission = () => {
    try { localStorage.removeItem(storageKey); } catch { /* A stale key can only replay its own receipt. */ }
    setSubmissionKey(null);
  };
  const recover = async (action: 'resume' | 'cancel' | 'acknowledge') => {
    if (!submissionKey || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError('');
    try {
      if (action === 'resume') { await resumeInvitationSubmission(submissionKey); clearSubmission(); onSaved(); }
      else if (action === 'cancel') {
        const result = await cancelInvitationSubmission(submissionKey);
        clearSubmission();
        if (result.status === 'committed') onSaved();
        else await refreshCareer();
      } else { const committed = receipt.data?.status === 'committed'; clearSubmission(); if (committed) onSaved(); else await refreshCareer(); }
    } catch (cause) { setError(extractErr(cause)); void receipt.refetch(); }
    finally { inFlight.current = false; setBusy(false); }
  };

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (inFlight.current || submissionKey) return;
    const date = new Date(start);
    if (!company.trim() || !role.trim() || !Number.isFinite(date.getTime())) {
      setError('请填写公司、岗位和有效的面试时间。');
      return;
    }
    const facts: InvitationFacts = {
      company_name: company.trim(), job_title: role.trim(),
      scheduled_start_at: date.toISOString(), original_time_text: start,
      source_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      location: location || null, stage_label: label || null,
    };
    const key = crypto.randomUUID();
    const payload: ConfirmInvitationCommand = {
        schema_version: 1, idempotency_key: key, actor_kind: 'user',
        asserted_at: new Date().toISOString(), facts,
        confirmation_basis: { kind: 'explicit_user_assertion', source: { kind: 'manual', identity: `manual-form:${key}`, version: '1' } },
        opportunity: opportunity ? { kind: 'link_existing', opportunity_id: opportunity.id, expected_version: opportunity.version } : { kind: 'create_new' },
        interview: interview ? { kind: 'update_existing', interview_id: interview.id, expected_schedule_version: interview.schedule_version } : { kind: 'create' },
      };
    try { localStorage.setItem(storageKey, key); }
    catch { setError('无法保存恢复凭据，请允许当前页面使用本地存储后再提交。'); return; }
    inFlight.current = true;
    setSubmissionKey(key);
    setBusy(true);
    setError('');
    try {
      await confirmInvitation(payload);
      clearSubmission();
      onSaved();
    } catch (cause) {
      setError(extractErr(cause, '保存结果尚未确认，请核对上次结果后继续。'));
      void queryClient.invalidateQueries({ queryKey: ['invitation-submission', user, key] });
    } finally {
      setBusy(false);
      inFlight.current = false;
    }
  }

  return <form onSubmit={submit} className="space-y-4">
    <p className="text-sm text-stone-500">记录已确认的面试时间，保存后可从这里进入面试准备和复盘。</p>
    {submissionKey && <section aria-label="恢复上次面试安排" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm space-y-3">
      <p>{receipt.data?.status === 'committed' ? '上次安排已经保存，可以直接查看。' : receipt.data?.status === 'pending' ? '上次保存尚未完成，可以继续原来的安排或取消。' : receipt.data?.status === 'rejected' || receipt.data?.status === 'cancelled' ? '上次保存已终止，可以返回编辑。' : receipt.data?.status === 'not_received' ? '未查到上次保存。可以继续核对，或取消后重新填写。' : '正在核对上次保存；确认结果前请勿重新创建安排。'}</p>
      {receipt.data?.command && <p>{receipt.data.command.facts.company_name} · {receipt.data.command.facts.job_title} · {new Date(receipt.data.command.facts.scheduled_start_at).toLocaleString('zh-CN')}</p>}
      {receipt.isError && <p role="alert">暂时无法读取保存结果，原恢复凭据仍然保留。</p>}
      <div className="flex flex-wrap gap-3">
        <button type="button" disabled={busy || receipt.isFetching} onClick={() => void receipt.refetch()}>核对保存结果</button>
        {receipt.data?.status === 'pending' && <button type="button" disabled={busy} onClick={() => void recover('resume')}>继续上次保存</button>}
        {['not_received', 'pending'].includes(receipt.data?.status ?? '') && <button type="button" disabled={busy} onClick={() => void recover('cancel')}>取消未完成保存</button>}
        {['committed', 'rejected', 'cancelled'].includes(receipt.data?.status ?? '') && <button type="button" disabled={busy} onClick={() => void recover('acknowledge')}>{receipt.data?.status === 'committed' ? '查看已保存安排' : '返回编辑'}</button>}
      </div>
    </section>}
    <fieldset disabled={busy || Boolean(submissionKey)} className="space-y-4">
    <label className="block text-sm">公司<input className="mt-1 w-full rounded-lg border p-2" value={company} onChange={e => setCompany(e.target.value)} maxLength={200} required disabled={busy} /></label>
    <label className="block text-sm">岗位<input className="mt-1 w-full rounded-lg border p-2" value={role} onChange={e => setRole(e.target.value)} maxLength={300} required disabled={busy} /></label>
    <label className="block text-sm">面试时间（本地时区）<input className="mt-1 w-full rounded-lg border p-2" type="datetime-local" value={start} onChange={e => setStart(e.target.value)} required disabled={busy} /></label>
    <label className="block text-sm">面试轮次 · 选填<input className="mt-1 w-full rounded-lg border p-2" value={label} onChange={e => setLabel(e.target.value)} maxLength={200} placeholder="例如：技术一面" disabled={busy} /></label>
    <label className="block text-sm">地点或会议方式 · 选填<input className="mt-1 w-full rounded-lg border p-2" value={location} onChange={e => setLocation(e.target.value)} maxLength={500} disabled={busy} /></label>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    <Btn type="submit" disabled={busy}>{busy ? '正在保存…' : '保存面试安排'}</Btn>
    </fieldset>
  </form>;
}
