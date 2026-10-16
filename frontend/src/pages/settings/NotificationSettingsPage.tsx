import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell, X } from 'lucide-react';
import { dismissReminder, getNotificationPreference, listReminderInbox, updateNotificationPreference } from '@/api/careerInsights';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import type { NotificationPreference } from '@/types/career';
import { displayDate, FormItem, TextInput } from '../career/CareerFields';

export function ReminderSettings() {
  const queryClient = useQueryClient();
  const preferenceQuery = useQuery({ queryKey: ['career-insights', 'notification-preference'], queryFn: getNotificationPreference });
  const inboxQuery = useQuery({ queryKey: ['career-insights', 'reminder-inbox'], queryFn: listReminderInbox });
  const [draft, setDraft] = useState<NotificationPreference | null>(null);
  const [busy, setBusy] = useState(false);
  const current = draft ?? preferenceQuery.data;
  if (!current) return <Spinner />;
  const save = async () => {
    setBusy(true);
    try { const updated = await updateNotificationPreference(current); setDraft(updated); await queryClient.invalidateQueries({ queryKey: ['career-insights'] }); toast.success('通知设置已保存'); }
    catch (error) { toast.error(extractErr(error)); }
    finally { setBusy(false); }
  };
  const update = <K extends keyof NotificationPreference>(key: K, value: NotificationPreference[K]) => setDraft({ ...current, [key]: value });
  return <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
    <div className="mb-4 flex items-center gap-2"><Bell size={17} className="text-primary-700" /><h2 className="font-semibold text-stone-800">行动提醒</h2><Pill tone="neutral">应用内提醒</Pill></div>
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <FormItem label="启用应用内提醒"><label className="flex h-10 items-center gap-2 text-sm text-stone-700"><input type="checkbox" checked={current.enabled} onChange={(event) => update('enabled', event.target.checked)} />启用</label></FormItem>
      <FormItem label="时区"><TextInput value={current.timezone} onChange={(event) => update('timezone', event.target.value)} /></FormItem>
      <FormItem label="安静时段开始"><TextInput type="time" value={current.quiet_start ?? ''} onChange={(event) => update('quiet_start', event.target.value || null)} /></FormItem>
      <FormItem label="安静时段结束"><TextInput type="time" value={current.quiet_end ?? ''} onChange={(event) => update('quiet_end', event.target.value || null)} /></FormItem>
    </div>
    <div className="mt-3 flex justify-end"><Btn size="sm" loading={busy} onClick={save}>保存通知设置</Btn></div>
    {(inboxQuery.data?.length ?? 0) > 0 && <div className="mt-5 border-t border-stone-100 pt-4"><h3 className="mb-2 text-sm font-medium text-stone-700">已送达提醒</h3><div className="space-y-2">{inboxQuery.data?.map((action) => <div key={action.id} className="flex items-center justify-between gap-3 rounded-md bg-primary-50 px-3 py-2"><div><p className="text-sm text-stone-800">{action.content}</p><p className="text-[11px] text-stone-500">送达于 {displayDate(action.reminder_delivered_at)}</p></div><button aria-label="关闭提醒" onClick={async () => { try { await dismissReminder(action); await inboxQuery.refetch(); } catch (error) { toast.error(extractErr(error)); } }}><X size={15} /></button></div>)}</div></div>}
  </section>;
}

export function NotificationSettingsPage() {
  return <div className="career-workspace"><header className="career-page-heading"><div><p className="career-eyebrow">STAY IN THE LOOP</p><h1>在合适的时间，提醒你。</h1><p>设置应用内提醒与安静时段。</p></div></header><ReminderSettings /></div>;
}
