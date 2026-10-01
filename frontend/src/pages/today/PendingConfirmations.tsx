import { useQuery, useQueryClient } from '@tanstack/react-query';
import { listPendingConfirmations } from '@/api/interviewInvitations';
import { InteractionCard } from '@/pages/review/chat/InteractionCard';
export function PendingConfirmations() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ['pending-confirmations'], queryFn: listPendingConfirmations, retry: false, refetchInterval: 15000 });
  return <section aria-label="待我确认" className="my-5"><h2 className="text-lg font-semibold">待我确认</h2>
    {query.isPending ? <p role="status">正在读取确认请求…</p> : query.isError ? <div role="alert"><p>暂时无法读取确认请求。</p><button onClick={() => { void query.refetch(); }}>重新读取</button></div>
      : !query.data?.length ? <p className="text-sm text-stone-500">没有待确认请求。</p>
        : query.data.map(({ conversation_id, interaction }) => <InteractionCard key={`${interaction.id}:${interaction.version}`}
          sessionId={conversation_id} turnId={interaction.turn_id} interaction={interaction}
          onResolved={() => { void client.invalidateQueries(); }} />)}
  </section>;
}
