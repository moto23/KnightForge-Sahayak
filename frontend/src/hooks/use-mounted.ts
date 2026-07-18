"use client";

import { useSyncExternalStore } from "react";

const emptySubscribe = () => () => {};

/**
 * True only after hydration (server snapshot is false, client is true).
 * Used by theme-dependent UI (e.g. the theme toggle) to avoid server/client
 * mismatch flashes.
 */
export function useMounted(): boolean {
  return useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false,
  );
}
