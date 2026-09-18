import type { InvitationFacts } from '@/api/interviewInvitations';

export type InvitationDraft = Record<keyof InvitationFacts, string>;
const fields: Array<[keyof InvitationFacts, string, number, boolean]> = [
  ['company_name', '公司', 200, true], ['job_title', '岗位', 300, true],
  ['scheduled_start_at', '开始时间（含时区）', 40, true],
  ['source_timezone', '时间所属时区', 80, true],
  ['original_time_text', '原始时间描述', 300, true],
  ['scheduled_end_at', '结束时间（含时区，可选）', 40, false],
  ['stage_label', '面试阶段', 200, false], ['location', '面试地点', 500, false],
  ['meeting_url', '会议链接', 4000, false], ['contact_name', '联系人', 200, false],
  ['contact_email', '联系邮箱', 320, false],
];
export function invitationDraft(facts: Partial<InvitationFacts> = {}): InvitationDraft {
  return Object.fromEntries(fields.map(([key]) => [key, facts[key] ?? (
    key === 'source_timezone' ? Intl.DateTimeFormat().resolvedOptions().timeZone : ''
  )])) as InvitationDraft;
}
export function checkedFacts(draft: InvitationDraft): InvitationFacts {
  for (const [key, label, max, required] of fields) {
    if ((required && !draft[key].trim()) || draft[key].trim().length > max) throw new Error(`请核对${label}`);
  }
  const aware = (value: string) => /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) && Number.isFinite(Date.parse(value));
  if (!aware(draft.scheduled_start_at) || (draft.scheduled_end_at && !aware(draft.scheduled_end_at))) {
    throw new Error('请提供明确带时区的日期时间，例如 2026-10-01T14:00:00+08:00');
  }
  if (draft.scheduled_end_at && Date.parse(draft.scheduled_end_at) <= Date.parse(draft.scheduled_start_at)) {
    throw new Error('结束时间必须晚于开始时间');
  }
  return Object.fromEntries(fields.map(([key, , , required]) => [key, draft[key].trim() || (required ? '' : null)])) as unknown as InvitationFacts;
}
export function InvitationFields({ value, onChange, disabled = false }: {
  value: InvitationDraft; onChange: (draft: InvitationDraft) => void; disabled?: boolean;
}) {
  return <fieldset disabled={disabled} className="grid gap-3 md:grid-cols-2">
    <legend className="sr-only">面试邀请事实</legend>
    {fields.map(([key, label, max, required]) => <label key={key} className="grid gap-1 text-sm">
      {label}<input className="rounded-lg border border-stone-300 bg-white p-2" value={value[key]}
        required={required} maxLength={max} onChange={(event) => onChange({ ...value, [key]: event.target.value })}
        placeholder={key === 'scheduled_start_at' ? '2026-10-01T14:00:00+08:00' : undefined} />
    </label>)}
  </fieldset>;
}
