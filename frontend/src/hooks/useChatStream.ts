import { useEffect, useRef, useState, useCallback } from 'react';
import { tokenStore } from '@/lib/token';
import type { WSEvent } from '@/types/api';

type StreamState =
  | { phase: 'idle' }
  | { phase: 'connecting' }
  | { phase: 'open' }
  | { phase: 'streaming'; buffer: string }
  | { phase: 'closed'; reason?: string };

export interface UseChatStream {
  state: StreamState;
  send: (message: string) => void;
  buffer: string;
  isStreaming: boolean;
  reset: () => void;
}

// WS endpoint: /api/v1/chat/ws/{session_id}?token=<access_token>
// Protocol (per backend/app/api/chat/streaming.py):
//   client sends:   { message: string }
//   server sends:   { type: 'chunk', content: string } | { type: 'done' }
export function useChatStream(
  sessionId: string | null,
  onDone?: (final: string) => void,
): UseChatStream {
  const [state, setState] = useState<StreamState>({ phase: 'idle' });
  const [buffer, setBuffer] = useState('');
  const wsRef = useRef<WebSocket | null>(null);
  const bufRef = useRef('');

  useEffect(() => {
    if (!sessionId) return;
    setState({ phase: 'connecting' });
    const token = tokenStore.getAccess() ?? '';
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${window.location.host}/api/v1/chat/ws/${encodeURIComponent(
      sessionId,
    )}?token=${encodeURIComponent(token)}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setState({ phase: 'open' });
    ws.onmessage = (e) => {
      let evt: WSEvent;
      try {
        evt = JSON.parse(e.data);
      } catch {
        return;
      }
      if (evt.type === 'chunk') {
        bufRef.current += evt.content;
        setBuffer(bufRef.current);
        setState({ phase: 'streaming', buffer: bufRef.current });
      } else if (evt.type === 'done') {
        const final = bufRef.current;
        bufRef.current = '';
        setBuffer('');
        setState({ phase: 'open' });
        onDone?.(final);
      }
    };
    ws.onclose = (e) => setState({ phase: 'closed', reason: e.reason });
    ws.onerror = () => setState({ phase: 'closed', reason: 'error' });

    return () => {
      ws.close();
      wsRef.current = null;
      bufRef.current = '';
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const send = useCallback((message: string) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    bufRef.current = '';
    setBuffer('');
    ws.send(JSON.stringify({ message }));
    setState({ phase: 'streaming', buffer: '' });
  }, []);

  const reset = useCallback(() => {
    bufRef.current = '';
    setBuffer('');
  }, []);

  return {
    state,
    send,
    buffer,
    isStreaming: state.phase === 'streaming',
    reset,
  };
}
