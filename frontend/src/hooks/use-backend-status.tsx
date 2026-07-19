"use client";

/**
 * Backend readiness — ONE probe, shared by the whole app.
 *
 * The backend runs on a free tier that suspends the container after a period
 * of inactivity. The first request afterwards is not refused; it is queued
 * while the container boots and answered a cold start later. Presented
 * naively that looked like "Backend offline" — alarming, and wrong: nothing
 * is broken and the request is on its way.
 *
 * Why this is a PROVIDER and not a plain hook: it used to be per-component,
 * so the shell's banner and the dashboard's status pill each ran their own
 * probe. They disagreed — the banner said "Waking up Sahayak" while the pill
 * simultaneously said "Backend offline". A sleeping backend must have exactly
 * one answer, so the probe runs once at the provider and every consumer reads
 * that same state. It also means N mounted pages cannot hammer a container
 * that is still booting.
 *
 * Design constraints this deliberately respects:
 *  - NO polling while the backend is warm. One probe, then silence.
 *  - Only GET /health is ever probed. It is idempotent and dependency-free,
 *    so retrying it can never duplicate a mutation or an upload.
 *  - Retries are BOUNDED. When they run out, consumers are told
 *    "unreachable" so they can show a real error instead of a forever spinner.
 *  - 5xx counts as WAKING, not offline: a booting container answers 502/503
 *    through the proxy before it is ready.
 *
 * States:
 *   checking     — first probe in flight, still within the grace period
 *   waking       — taking longer than a warm backend ever would; say so
 *   warm         — healthy; the probe is finished and goes quiet
 *   unreachable  — bounded retries exhausted; surface a real error
 */

import * as React from "react";

import { healthService } from "@/services";

export type BackendStatus = "checking" | "waking" | "warm" | "unreachable";

/**
 * A warm backend answers /health in well under this. Past it we assume a cold
 * start and tell the user, rather than leaving them staring at a blank shell.
 */
const WAKING_GRACE_MS = 2_500;

/** Per-probe ceiling. Generous: a cold container may take tens of seconds. */
const PROBE_TIMEOUT_MS = 20_000;

/**
 * Backoff between probes, in ms. Bounded on purpose — this covers a typical
 * free-tier cold start with room to spare, then gives up honestly instead of
 * retrying forever.
 */
const RETRY_BACKOFF_MS = [2_000, 4_000, 8_000, 12_000, 15_000] as const;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export type BackendStatusValue = {
  status: BackendStatus;
  /** True while the backend is booting — never means "broken". */
  isWaking: boolean;
  /** True only once bounded retries have conclusively failed. */
  isOffline: boolean;
  /** Probe again after "unreachable" (wired to a Retry button). */
  retry: () => void;
};

const BackendStatusContext = React.createContext<BackendStatusValue | null>(
  null,
);

export function BackendStatusProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [status, setStatus] = React.useState<BackendStatus>("checking");
  const [attemptKey, setAttemptKey] = React.useState(0);

  const retry = React.useCallback(() => {
    setStatus("checking");
    setAttemptKey((key) => key + 1);
  }, []);

  React.useEffect(() => {
    let cancelled = false;

    // Announce a cold start if the first probe outlives the grace period —
    // the probe itself keeps running, this only changes what we say meanwhile.
    const graceTimer = setTimeout(() => {
      if (!cancelled) setStatus((s) => (s === "checking" ? "waking" : s));
    }, WAKING_GRACE_MS);

    void (async () => {
      // One initial probe plus the bounded retry ladder.
      for (let attempt = 0; attempt <= RETRY_BACKOFF_MS.length; attempt++) {
        try {
          await healthService.check(undefined, PROBE_TIMEOUT_MS);
          if (!cancelled) setStatus("warm");
          return; // healthy — stop probing entirely, no polling loop
        } catch {
          if (cancelled) return;
          // Every failure here (timeout, network, 502/503 from the proxy in
          // front of a booting container) is treated as "still waking".
          setStatus("waking");
          const backoff = RETRY_BACKOFF_MS[attempt];
          if (backoff === undefined) break; // ladder exhausted
          await sleep(backoff);
          if (cancelled) return;
        }
      }
      // Bounded retries are spent: report it rather than spin forever.
      if (!cancelled) setStatus("unreachable");
    })();

    return () => {
      cancelled = true;
      clearTimeout(graceTimer);
    };
  }, [attemptKey]);

  const value = React.useMemo<BackendStatusValue>(
    () => ({
      status,
      // "checking" is grouped with waking on purpose: until the probe answers
      // we do not know the backend is healthy, and the one thing we must
      // never do is call it offline while it might simply be booting.
      isWaking: status === "checking" || status === "waking",
      isOffline: status === "unreachable",
      retry,
    }),
    [status, retry],
  );

  return (
    <BackendStatusContext.Provider value={value}>
      {children}
    </BackendStatusContext.Provider>
  );
}

/**
 * Read the shared backend status.
 *
 * Safe outside the provider (marketing pages do not mount it): it then
 * reports a warm backend, which keeps those pages behaving exactly as before.
 */
export function useBackendStatus(): BackendStatusValue {
  const context = React.useContext(BackendStatusContext);
  return (
    context ?? {
      status: "warm",
      isWaking: false,
      isOffline: false,
      retry: () => {},
    }
  );
}
