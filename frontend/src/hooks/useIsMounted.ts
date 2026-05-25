import { useEffect, useRef } from 'react';

/**
 * Returns a ref whose ``.current`` is true between mount and unmount.
 *
 * Use it to guard ``setState`` calls inside user-initiated async
 * handlers (file upload, manual refresh, save-then-reload). If the
 * user navigates away while the await is in flight, the unmounted
 * component would otherwise log React's "setState on unmounted
 * component" warning — and in StrictMode could also stomp a fresh
 * mount's state.
 *
 * React's preferred pattern for *effect-driven* fetches is an
 * AbortController inside the effect's cleanup (we use that
 * extensively elsewhere). But for *manually-triggered* refreshes
 * (button click, save-then-reload), there's no effect to attach
 * the controller to — the handler closes over the latest setters
 * and runs without a lifecycle anchor. ``useIsMounted`` is the
 * minimum-friction guard for that case.
 *
 * Usage:
 *   const isMounted = useIsMounted();
 *   const refresh = async () => {
 *     setLoading(true);
 *     try {
 *       const data = await fetchSomething();
 *       if (!isMounted.current) return;
 *       setData(data);
 *     } finally {
 *       if (isMounted.current) setLoading(false);
 *     }
 *   };
 */
export function useIsMounted() {
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  return mounted;
}
