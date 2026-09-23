import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { listCareerActivity } from '@/api/careerActivity';

export function RecentActivity() {
  const activity = useQuery({ queryKey: ['career-activity'], queryFn: listCareerActivity, retry: false, refetchInterval: 15000 });
  return <section className="mt-6 rounded-xl border border-stone-200 bg-white p-5" aria-label="最近进展">
    <h2 className="mb-3 font-medium">最近进展</h2>
    {activity.isPending ? <p role="status">正在读取最近进展…</p>
      : activity.isError ? <div role="alert"><p>暂时无法读取最近进展，已有记录不会改变。</p><button type="button" disabled={activity.isFetching} onClick={() => { void activity.refetch(); }}>重新加载进展</button></div>
        : activity.data.length === 0 ? <p className="text-sm text-stone-500">暂无进展记录。</p>
          : <ul className="space-y-3">{activity.data.map(event => <li key={event.event_id}>
            <small className="text-stone-500">{event.event_category === 'domain' ? '已确认的进展' : event.event_category === 'harness' ? '执行与确认' : '交互记录'} · {new Date(event.occurred_at).toLocaleString()}</small>
            <p>{event.payload.title || '进展记录'}</p><p className="text-sm text-stone-600">{event.payload.detail}</p>
            {event.conversation_id && <Link className="text-sm underline" to={`/chat?session=${encodeURIComponent(event.conversation_id)}`}>查看相关对话</Link>}
          </li>)}</ul>}
  </section>;
}
