import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { listCareerActivity } from '@/api/careerActivity';
export function ActivityCenterPage() {
  return <div className="mx-auto max-w-5xl space-y-5 p-6"><h1 className="text-2xl font-semibold">活动与执行记录</h1>
    <p>业务变更、执行状态和页面动作分别记录。页面已打开不代表业务已完成，结果未知不等于失败后可重试。</p>
    <ActivityFeed />
  </div>;
}

export function ActivityFeed({ limit = 100 }: { limit?: number }) {
  const query = useQuery({ queryKey: ['career-activity'], queryFn: listCareerActivity, retry: false, refetchInterval: 15000 });
  return <section aria-label="最近活动" className="my-5 space-y-3"><h2 className="text-lg font-semibold">最近活动</h2>
    <button onClick={() => { void query.refetch(); }} disabled={query.isFetching}>刷新</button>
    {query.isPending ? <p role="status">正在读取活动…</p> : query.isError ? <p role="alert">暂时无法读取活动，请重试。</p>
      : !query.data?.length ? <p>暂时没有活动记录。</p> : <ol className="space-y-3">{query.data.slice(0, limit).map((event) => <li key={event.event_id} className="rounded-xl border bg-white p-4">
        <h2 className="font-semibold">{typeof event.payload.title === 'string' ? event.payload.title : event.event_kind}</h2>
        <p className="text-sm">{event.event_category === 'domain' ? '业务事实' : event.event_category === 'experience' ? '页面动作' : '执行过程'} · {typeof event.payload.status === 'string' ? event.payload.status : '已记录'}</p>
        {typeof event.payload.detail === 'string' && <p>{event.payload.detail}</p>}
        <time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString('zh-CN')}</time>
        {event.conversation_id && <Link className="ml-4" to={`/general-chat?session=${encodeURIComponent(event.conversation_id)}`}>查看原协作</Link>}
      </li>)}</ol>}
    <Link to="/activity">查看全部活动</Link>
  </section>;
}
