"use client";

import * as React from "react";

import { toApiError, type ApiError } from "@/services/api-client";

export type AsyncState<T> = {
  data: T | null;
  loading: boolean;
  error: ApiError | null;
};

/**
 * Tiny shared loader hook: runs an async producer, exposes
 * {data, loading, error} plus reload() for retry buttons.
 * The producer receives an AbortSignal that fires on unmount/reload, so
 * in-flight requests are truly cancelled (not just ignored).
 */
export function useAsync<T>(
  producer: (signal?: AbortSignal) => Promise<T>,
  deps: React.DependencyList = [],
): AsyncState<T> & { reload: () => void; setData: (data: T | null) => void } {
  const [state, setState] = React.useState<AsyncState<T>>({
    data: null,
    loading: true,
    error: null,
  });
  const [tick, setTick] = React.useState(0);

  const producerRef = React.useRef(producer);
  React.useEffect(() => {
    producerRef.current = producer;
  });

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    producerRef
      .current(controller.signal)
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null });
      })
      .catch((error: unknown) => {
        const apiError = toApiError(error);
        // Aborted by our own cleanup — never surface as a UI error.
        if (!cancelled && !apiError.isCancelled)
          setState({ data: null, loading: false, error: apiError });
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  const reload = React.useCallback(() => {
    // Event-handler context: safe to flip loading synchronously here.
    setState((prev) => ({ ...prev, loading: true, error: null }));
    setTick((t) => t + 1);
  }, []);

  const setData = React.useCallback(
    (data: T | null) => setState({ data, loading: false, error: null }),
    [],
  );

  return { ...state, reload, setData };
}
