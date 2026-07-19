"use client";

/**
 * Backend readiness — tells the UI when the API is merely ASLEEP rather than
 * broken.
 *
 * The backend runs on a free tier that suspends the container after a period
 * of inactivity. The first request afterwards is not refused; it is queued
 * while the container boots and answered a cold start later. Presented
 * naively that looked like "Backend offline" — alarming, and wrong: nothing
 * is broken and the request is on its way.
 *
 * Design constraints this deliberately respects:
 *  - NO polling while the backend is warm. One probe on mount, then silence.
 *  - Only GET /health is ever probed. It is idempotent and dependency-free,
 *    so retrying it can never duplicate a mutation or an upload.
 *  - Retries are BOUNDED. When they run out the caller is told "unreachable"
 *    so it can show a real error instead of an endless spinner.
 *
 * States:
 *   checking     — first probe in flight, still within the grace period
 *   waking       — taking longer than a warm backend ever would; say so
 *   warm         — healthy; the hook is finished and goes quiet
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

export function useBackendStatus(): {
  status: BackendStatus;
  /** Probe again after "unreachable" (wired to a Retry button). */
  retry: () => void;
} {
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

  return { status, retry };
}
