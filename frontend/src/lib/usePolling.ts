"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Loads data with `load` and reloads every `intervalMs` while `shouldPoll(data)` is true.
 * `refresh()` reloads immediately and restarts polling (e.g. after starting a new call).
 */
export function usePolling<T>(
  load: () => Promise<T>,
  shouldPoll: (data: T | undefined) => boolean,
  intervalMs = 3000,
) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [generation, setGeneration] = useState(0);
  const loadRef = useRef(load);
  const shouldPollRef = useRef(shouldPoll);
  useEffect(() => {
    loadRef.current = load;
    shouldPollRef.current = shouldPoll;
  });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      let next: T | undefined;
      try {
        next = await loadRef.current();
        if (cancelled) return;
        setData(next);
        setError(undefined);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
      if (!cancelled && shouldPollRef.current(next)) timer = setTimeout(tick, intervalMs);
    };
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [generation, intervalMs]);

  const refresh = useCallback(() => setGeneration((g) => g + 1), []);
  return { data, error, loading, refresh, setData };
}
