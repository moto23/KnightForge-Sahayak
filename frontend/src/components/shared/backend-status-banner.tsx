"use client";

/**
 * A non-destructive strip explaining that the backend is waking up.
 *
 * Deliberately NOT a blocking overlay: a cold start does not stop the user
 * reading the page, changing theme, or navigating, and the requests they
 * trigger are queued and served once the container is up. The banner only
 * explains the wait — it never gates the UI behind itself.
 *
 * Silent while the backend is warm (the overwhelmingly common case), so it
 * costs a healthy session nothing but one /health probe.
 */

import { Loader2, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useBackendStatus } from "@/hooks/use-backend-status";

export function BackendStatusBanner() {
  const { status, retry } = useBackendStatus();

  if (status === "warm" || status === "checking") return null;

  if (status === "unreachable") {
    return (
      <div
        role="alert"
        className="flex items-center justify-center gap-3 border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive"
      >
        <TriangleAlert className="size-4 shrink-0" aria-hidden />
        <span>Sahayak&apos;s backend isn&apos;t responding.</span>
        <Button variant="outline" size="sm" onClick={retry}>
          Try again
        </Button>
      </div>
    );
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center justify-center gap-2 border-b border-border bg-muted/60 px-4 py-2 text-sm text-muted-foreground"
    >
      <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
      <span>
        Waking up Sahayak — the free-tier server sleeps when idle. This can take
        up to a minute the first time.
      </span>
    </div>
  );
}
