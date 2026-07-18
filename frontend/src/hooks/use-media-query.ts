"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Reactive media-query hook (SSR-safe: returns false on the server).
 * Example: const isDesktop = useMediaQuery("(min-width: 1024px)")
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onStoreChange: () => void) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onStoreChange);
      return () => mql.removeEventListener("change", onStoreChange);
    },
    [query],
  );

  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  );
}
