/** Small pure formatting helpers shared across pages. */

/** "150111" -> "146.6 KB" */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes;
  let unit = "B";
  for (const next of units) {
    if (value < 1024) break;
    value /= 1024;
    unit = next;
  }
  return `${value.toFixed(1)} ${unit}`;
}

/** ISO timestamp -> "16 Jul 2026, 10:42" (stable, locale-independent-ish). */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** Clamp a percentage into [0, 100] for progress UI. */
export function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, Math.round(value)));
}
