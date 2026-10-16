import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { listCareerActivity } from '@/api/careerActivity';
import { Btn } from '@/components/ui/Btn';

const categories = { domain: '求职进展', harness: '协作状态', experience: '页面操作' };
const statuses: Record<string, string> = { succeeded: '已完成', completed: '已完成', confirmed: '已确认', pending: '等待处理', running: '正在处理', waiting: '等待回复', failed: '未完成', unknown: '结果待核实', cancelled: '已取消', acknowledged: '已打开' };

export function ActivityCenterPage() {
  const [limit, setLimit] = useState(20);
  const [category, setCategory] = useState('all');
  const query = useQuery({ queryKey: ['career-activity'], queryFn: listCareerActivity, retry: false, refetchInterval: 30000 });
  const events = (query.data ?? []).filter((event) => category === 'all' || event.event_category === category);
  return <div className="workspace-page">
    <header className="mb-5 flex items-start justify-between gap-4"><div><h1 className="text-2xl font-semibold">活动记录</h1><p className="mt-2 text-sm text-stone-500">查看进展与处理结果，需要继续时回到原协作。</p></div><Btn kind="ghost" size="sm" icon={<RefreshCw size={14} />} loading={query.isFetching} onClick={() => query.refetch()}>刷新</Btn></header>
    <div className="profile-tabs" role="group" aria-label="活动分类">{Object.entries({ all: '全部', ...categories }).map(([id, label]) => <button key={id} aria-pressed={category === id} onClick={() => { setCategory(id); setLimit(20); }}>{label}</button>)}</div>
    {query.isPending ? <p role="status">正在读取活动…</p> : query.isError ? <p role="alert">活动暂时无法加载，请点击刷新重试。</p>
      : !events.length ? <p className="py-8 text-sm text-stone-500">暂无对应的活动记录。</p> : <ol className="divide-y divide-stone-200 rounded-xl border border-stone-200 bg-white px-5">{events.slice(0, limit).map((event) => <li key={event.event_id} className="py-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-sm font-medium text-stone-800">{typeof event.payload.title === 'string' ? event.payload.title : '协作进展已更新'}</h2><time className="text-xs text-stone-400" dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString('zh-CN')}</time></div>
        <div className="mt-2 flex items-center gap-3 text-xs text-stone-500"><span>{categories[event.event_category]} · {typeof event.payload.status === 'string' ? statuses[event.payload.status] ?? '已记录' : '已记录'}</span>{event.conversation_id && <Link className="text-primary-700" to={`/general-chat?session=${encodeURIComponent(event.conversation_id)}`}>回到协作 →</Link>}</div>
        {typeof event.payload.detail === 'string' && <details className="mt-2 text-xs text-stone-500"><summary className="cursor-pointer">查看详情</summary><p className="mt-2 leading-6">{event.payload.detail}</p></details>}
      </li>)}</ol>}
    {events.length > limit && <div className="mt-4 text-center"><Btn kind="outline" size="sm" onClick={() => setLimit(limit + 20)}>显示更多记录</Btn></div>}
  </div>;
}
