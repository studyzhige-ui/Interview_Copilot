import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { listPendingConfirmations } from '@/api/interviewInvitations';

const labels = { clarification: '补充信息', connection: '连接服务', approval: '确认操作', client_readiness: '继续页面操作', fact_confirmation: '核对面试安排', profile_update_confirmation: '核对档案更新' };

export function PendingConfirmations() {
  const [expanded, setExpanded] = useState(false);
  const query = useQuery({ queryKey: ['pending-confirmations'], queryFn: listPendingConfirmations, retry: false, refetchInterval: 30000 });
  if (query.isError) return <p role="alert" className="today-confirmations">确认请求暂时无法加载。<button onClick={() => { void query.refetch(); }}>重试</button></p>;
  if (!query.data?.length) return null;
  return <section aria-label="等待你确认" className="today-confirmations">
    <strong>{query.data.length} 项协作等待你确认</strong>
    <div>{(expanded ? query.data : query.data.slice(0, 3)).map(({ conversation_id, interaction }) => <Link key={interaction.id} to={`/general-chat?session=${encodeURIComponent(conversation_id)}`}>
      {labels[interaction.kind]} <ArrowRight size={13} />
    </Link>)}</div>
    {query.data.length > 3 && <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? '收起' : '查看其余协作'}</button>}
  </section>;
}
