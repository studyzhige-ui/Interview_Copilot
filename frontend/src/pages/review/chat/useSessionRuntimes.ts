import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { SessionRuntime } from './types';

/** Cap for the per-session runtime LRU.
 *  Module scope so the ``useCallback([])`` closure inside ``getRuntime``
 *  doesn't develop a stale-closure footgun if this ever becomes
 *  non-literal. */
const MAX_CACHED_RUNTIMES = 24;

/**
 * Per-session SSE runtime cache.
 *
 * Bounded LRU. JS Maps preserve insertion order, so we use that as
 * the recency axis: every ``getRuntime`` re-inserts at the tail
 * (most-recently-used) and the prune step at the bottom of that
 * function drops entries from the head until we're back under
 * ``MAX_CACHED_RUNTIMES``.
 *
 * Why bother: long-lived FE tabs (esp. for power users with many
 * active interviews) used to grow this Map without bound — every
 * distinct session opened in a tab stayed cached forever, dragging
 * its loaded ``messages`` array along. 50 sessions × ~100 messages
 * × ~2KB markdown ≈ 10MB of heap. The cap is a soft limit (active
 * streamers are skipped during prune so an in-flight SSE is never
 * orphaned). Evicted sessions re-fetch their history on next open
 * via the ``loadedHistory`` flag — no data loss, just a cold refetch.
 */
export function useSessionRuntimes() {
  const runtimes = useRef<Map<string, SessionRuntime>>(new Map());
  const [tick, setTick] = useState(0);

  // ``bump()`` triggers a re-render after we've mutated a runtime out-
  // of-band (the runtimes Map is a ref, so React doesn't see writes).
  // Pre-fix every text_delta from the SSE stream fired ``bump()``
  // synchronously — at typical streaming rates (~50 deltas/sec for a
  // fast LLM) with ~10 visible bubbles that drove ~500 react-markdown
  // reparses/sec. Profiler showed it pinning the main thread.
  //
  // Coalesce via ``requestAnimationFrame``: at most one re-render per
  // frame (~60Hz on a typical display). Multiple ``bump()`` calls
  // within the same frame fold into one. The visual result is
  // identical — chunks land within one frame anyway — but render
  // work drops by an order of magnitude.
  const rafScheduledRef = useRef(false);
  const bump = useCallback(() => {
    if (rafScheduledRef.current) return;
    rafScheduledRef.current = true;
    requestAnimationFrame(() => {
      rafScheduledRef.current = false;
      setTick((n) => n + 1);
    });
  }, []);

  const getRuntime = useCallback((id: string): SessionRuntime => {
    const map = runtimes.current;
    let r = map.get(id);
    if (r) {
      // Re-insert at tail to mark MRU. JS Maps preserve insertion
      // order so this is the canonical idiom; delete+set is O(1).
      map.delete(id);
      map.set(id, r);
    } else {
      r = {
        abort: null, messages: [], partial: '', inflightBlocks: [],
        inflightSources: [],
        status: '', streaming: false, hidePartialBar: false,
        loadedHistory: false,
      };
      map.set(id, r);
    }
    // Prune from head (LRU) until we're under cap. Skip streamers
    // (an in-flight SSE owns its runtime; orphaning would leak the
    // AbortController + the half-built inflightBlocks) and skip the
    // entry we just touched (always the tail, but belt-and-braces).
    if (map.size > MAX_CACHED_RUNTIMES) {
      for (const [k, v] of map) {
        if (map.size <= MAX_CACHED_RUNTIMES) break;
        if (v.streaming) continue;
        if (k === id) continue;
        map.delete(k);
      }
    }
    return r;
  }, []);

  /** Drop a session's runtime entirely (after deletion). */
  const dropRuntime = useCallback((id: string) => {
    const r = runtimes.current.get(id);
    r?.abort?.abort();
    runtimes.current.delete(id);
  }, []);

  // Abort all in-flight SSE on unmount.
  useEffect(() => {
    const map = runtimes.current;
    return () => { map.forEach((r) => r.abort?.abort()); };
  }, []);

  // Streaming-status set for the session dropdown's per-row dot.
  // Reading the runtimes ref during render is intentional here: the Map
  // is mutated out-of-band by the SSE pipeline and ``tick`` is bumped
  // (rAF-coalesced) after every mutation, so this memo re-derives exactly
  // when the underlying data changed.
  const streamingSet = useMemo(() => {
    const set = new Set<string>();
    // eslint-disable-next-line react-hooks/refs
    runtimes.current.forEach((r, id) => { if (r.streaming) set.add(id); });
    return set;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  return { runtimes, tick, bump, getRuntime, dropRuntime, streamingSet };
}
