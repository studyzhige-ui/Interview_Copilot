import { useRef, useState } from 'react';
import { apiClient, extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';

/** Explicit user input enters the same verified Operation as Agent intake. */
export function ManualInvitationForm({ onSaved }: { onSaved: () => void }) {
  const [company, setCompany] = useState('');
  const [role, setRole] = useState('');
  const [start, setStart] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const attempt = useRef<{ fingerprint: string; payload: Record<string, unknown> } | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const date = new Date(start);
    if (!company.trim() || !role.trim() || !Number.isFinite(date.getTime())) {
      setError('请填写公司、岗位和有效的面试时间。');
      return;
    }
    const facts = {
      company_name: company.trim(), job_title: role.trim(),
      scheduled_start_at: date.toISOString(), original_time_text: start,
      source_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    };
    const fingerprint = JSON.stringify(facts);
    if (attempt.current?.fingerprint !== fingerprint) {
      const key = crypto.randomUUID();
      attempt.current = { fingerprint, payload: {
        schema_version: 1, idempotency_key: key, actor_kind: 'user',
        asserted_at: new Date().toISOString(), facts,
        confirmation_basis: { kind: 'explicit_user_assertion', source: { kind: 'manual', identity: `manual-form:${key}`, version: '1' } },
        opportunity: { kind: 'create_new' }, interview: { kind: 'create' },
      } };
    }
    setBusy(true);
    setError('');
    try {
      await apiClient.post('/career/interview-invitations/confirm', attempt.current.payload);
      onSaved();
    } catch (cause) {
      setError(extractErr(cause, '保存失败，请重试；重复提交不会重复创建记录。'));
    } finally {
      setBusy(false);
    }
  }

  return <form onSubmit={submit} className="space-y-4">
    <p className="text-sm text-stone-500">记录已确认的新岗位面试安排。保存会创建岗位和面试记录；不会发送邮件或创建额外待办。已有岗位可在岗位详情中记录进展。</p>
    <label className="block text-sm">公司<input className="mt-1 w-full rounded-lg border p-2" value={company} onChange={e => setCompany(e.target.value)} maxLength={200} required disabled={busy} /></label>
    <label className="block text-sm">岗位<input className="mt-1 w-full rounded-lg border p-2" value={role} onChange={e => setRole(e.target.value)} maxLength={300} required disabled={busy} /></label>
    <label className="block text-sm">面试时间（本地时区）<input className="mt-1 w-full rounded-lg border p-2" type="datetime-local" value={start} onChange={e => setStart(e.target.value)} required disabled={busy} /></label>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    <Btn type="submit" disabled={busy}>{busy ? '正在保存…' : '保存面试安排'}</Btn>
  </form>;
}
