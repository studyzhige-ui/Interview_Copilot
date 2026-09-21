import { useEffect, useMemo, useState } from 'react';
import { RealtimeClient, INITIAL_MEDIA_VIEW, type RealtimeView } from '@/lib/realtime/client';

export function useRealtimeInterview(recordId: string, onSynchronize: () => void) {
  const [saved, setSaved] = useState({ recordId, view: INITIAL_MEDIA_VIEW });
  const client = useMemo(() => new RealtimeClient(recordId,
    (view: RealtimeView) => setSaved({ recordId, view }), () => {}), [recordId]);
  useEffect(() => { client.setSynchronize(onSynchronize); }, [client, onSynchronize]);
  useEffect(() => () => client.disconnect(false), [client]);
  return { client, view: saved.recordId === recordId ? saved.view : INITIAL_MEDIA_VIEW };
}
