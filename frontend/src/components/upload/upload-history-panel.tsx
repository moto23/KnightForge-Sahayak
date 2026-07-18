"use client";

import * as React from "react";
import { History } from "lucide-react";

import { Badge, StatusBadge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { SkeletonRow } from "@/components/ui/skeleton";
import { useAuth } from "@/contexts/auth-context";
import { uploadService } from "@/services";
import { toApiError } from "@/services/api-client";
import type { UploadHistoryItem } from "@/types/api";
import { formatBytes, formatDateTime } from "@/utils/format";

import { DOCUMENT_TYPE_LABELS } from "./document-types";

/** OCR status → StatusBadge tone. */
const OCR_STATUS: Record<
  UploadHistoryItem["ocr_status"],
  React.ComponentProps<typeof StatusBadge>["status"]
> = {
  pending: "pending",
  completed: "completed",
  failed: "failed",
};

const PROCESSING_LABELS: Record<UploadHistoryItem["processing_status"], string> = {
  uploaded: "Uploaded",
  analyzed: "Analyzed",
  prefilled: "Prefilled",
  deleted: "Deleted",
};

/**
 * Persistent upload history (Phase 13) — the signed-in account's uploads
 * from SQLite: filename, selected/detected type, date, OCR + processing
 * status. Guests see nothing (the panel renders null) — history is the
 * account's perk, guest mode keeps working without it.
 */
export function UploadHistoryPanel({
  refreshKey = 0,
  limit,
  title = "Upload history",
  description = "Every document you've uploaded with this account — kept across sessions.",
}: {
  /** Bump to reload (e.g. after a new upload completes). */
  refreshKey?: number;
  /** Show only the most recent N rows (dashboard uses a short list). */
  limit?: number;
  title?: string;
  description?: string;
}) {
  const { isAuthenticated, restoring } = useAuth();
  const [items, setItems] = React.useState<UploadHistoryItem[] | null>(null);
  const [error, setError] = React.useState<string>("");

  React.useEffect(() => {
    // Signed out → the component renders null, so no state reset is needed;
    // on the next sign-in this effect re-runs and replaces the list anyway.
    if (!isAuthenticated) return;
    const controller = new AbortController();
    uploadService
      .history(controller.signal)
      .then((response) => {
        setItems(response.items);
        setError("");
      })
      .catch((err) => {
        const apiError = toApiError(err);
        if (!apiError.isCancelled) setError(apiError.message);
      });
    return () => controller.abort();
  }, [isAuthenticated, refreshKey]);

  if (restoring || !isAuthenticated) return null;

  const visible = limit && items ? items.slice(0, limit) : items;

  return (
    <Card id="history" className="scroll-mt-20">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <History className="size-4 text-accent" aria-hidden /> {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {items === null && !error && (
          <div className="space-y-3" aria-label="Loading history">
            <SkeletonRow />
            <SkeletonRow />
          </div>
        )}

        {error && <p className="text-sm text-muted-foreground">{error}</p>}

        {visible && visible.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No uploads yet — your documents will be remembered here.
          </p>
        )}

        {visible?.map((item) => (
          <div
            key={item.history_id}
            className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border border-border p-3"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{item.filename}</p>
              <p className="text-xs text-muted-foreground">
                {formatBytes(item.file_size)} · {formatDateTime(item.uploaded_at)}
              </p>
            </div>
            <Badge variant="accent">
              {item.detected_type ??
                DOCUMENT_TYPE_LABELS[item.document_type] ??
                item.document_type}
            </Badge>
            <StatusBadge status={OCR_STATUS[item.ocr_status]} />
            <Badge
              variant={item.processing_status === "deleted" ? "outline" : "default"}
            >
              {PROCESSING_LABELS[item.processing_status]}
            </Badge>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
