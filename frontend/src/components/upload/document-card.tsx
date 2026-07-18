"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ChevronDown,
  Eye,
  FileImage,
  FileText,
  Loader2,
  ScanText,
  Sparkles,
  Trash2,
} from "lucide-react";

import { Badge, StatusBadge, type Status } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { DocumentTypeInfo, OCRExtractResponse } from "@/types/api";
import { formatBytes } from "@/utils/format";

/** UI lifecycle of one document in the upload workspace. */
export type DocPhase = "uploading" | "processing" | "analyzed" | "failed";

export type WorkspaceDocument = {
  /** Client key (stable across upload → server id swap). */
  key: string;
  documentId: string | null;
  filename: string;
  contentType: string;
  sizeBytes: number;
  phase: DocPhase;
  uploadPercent: number;
  extraction: OCRExtractResponse | null;
  /** Detected document type from the intelligence classifier (Phase 11). */
  docType: DocumentTypeInfo | null;
  errorMessage: string | null;
  /**
   * URL for viewing the uploaded document: the backend file endpoint for
   * stored documents (persists across OCR, refresh and navigation), or a
   * temporary object URL while the upload is still in flight.
   */
  previewUrl: string | null;
};

const PHASE_TO_STATUS: Record<DocPhase, Status> = {
  uploading: "processing",
  processing: "processing",
  analyzed: "analyzed",
  failed: "failed",
};

function ConfidenceBar({ value }: { value: number }) {
  const percent = Math.round(value * 100);
  return (
    <span className="flex items-center gap-2" title={`Confidence ${percent}%`}>
      <span className="h-1.5 w-14 overflow-hidden rounded-full bg-muted">
        <span
          className={cn(
            "block h-full rounded-full transition-all",
            percent >= 75 ? "bg-success" : percent >= 50 ? "bg-warning" : "bg-destructive",
          )}
          style={{ width: `${percent}%` }}
        />
      </span>
      <span className="w-8 text-right text-xs tabular-nums text-muted-foreground">
        {percent}%
      </span>
    </span>
  );
}

/**
 * One uploaded document: upload progress → OCR processing animation →
 * extraction results with per-field confidence — plus prefill & delete.
 */
export function DocumentCard({
  doc,
  labelOf,
  onPrefill,
  onDelete,
  prefillBusy,
}: {
  doc: WorkspaceDocument;
  labelOf: (fieldId: string) => string;
  onPrefill: (doc: WorkspaceDocument) => void;
  onDelete: (doc: WorkspaceDocument) => void;
  prefillBusy: boolean;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const isPdf = doc.contentType === "application/pdf";
  const Icon = isPdf ? FileText : FileImage;
  const extraction = doc.extraction?.extraction ?? null;
  const acceptedCount = extraction?.fields_accepted ?? 0;
  /** A recognized document (any type) with nothing extractable — benign. */
  const blankDocument =
    extraction !== null && extraction.fields_found === 0;
  const detectedLabel =
    doc.docType && doc.docType.kind !== "unknown"
      ? doc.docType.label
      : extraction?.is_kyc_form
        ? "KYC form"
        : null;
  const missingCount = extraction?.missing_required.length ?? 0;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      className="rounded-xl border border-border bg-card shadow-sm"
    >
      {/* Header row */}
      <div className="flex items-start gap-3 p-4">
        {doc.previewUrl && !isPdf ? (
          /* eslint-disable-next-line @next/next/no-img-element -- backend file URL / blob:, next/image can't optimize these */
          <img
            src={doc.previewUrl}
            alt={`Preview of ${doc.filename}`}
            className="size-12 shrink-0 rounded-lg border border-border object-cover"
          />
        ) : (
          <span className="grid size-12 shrink-0 place-items-center rounded-lg bg-muted text-primary">
            <Icon className="size-6" aria-hidden />
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{doc.filename}</p>
          <p className="text-xs text-muted-foreground">
            {formatBytes(doc.sizeBytes)}
            {doc.extraction
              ? ` · ${doc.extraction.analysis.page_count} page${doc.extraction.analysis.page_count > 1 ? "s" : ""} · quality: ${doc.extraction.analysis.overall_quality}`
              : ""}
          </p>
          {/* Status chips — always visible, wrap on small screens. */}
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {doc.docType && (
              <Badge
                variant={doc.docType.kind === "unknown" ? "outline" : "accent"}
                title={`Detected with ${Math.round(doc.docType.confidence * 100)}% confidence`}
              >
                {doc.docType.label}
              </Badge>
            )}
            <StatusBadge status={PHASE_TO_STATUS[doc.phase]} />
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {doc.previewUrl && (
            <Button
              variant="ghost"
              size="icon"
              className="size-8 text-muted-foreground"
              aria-label={`View ${doc.filename}`}
              title="View document"
              asChild
            >
              <a href={doc.previewUrl} target="_blank" rel="noreferrer">
                <Eye className="size-4" />
              </a>
            </Button>
          )}
          {doc.documentId && doc.phase !== "uploading" && (
            <Button
              variant="ghost"
              size="icon"
              className="size-8 text-muted-foreground hover:text-destructive"
              aria-label={`Delete ${doc.filename}`}
              title="Delete document"
              onClick={() => onDelete(doc)}
            >
              <Trash2 className="size-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Uploading: progress bar */}
      {doc.phase === "uploading" && (
        <div className="space-y-1.5 px-3.5 pb-3.5">
          <Progress value={doc.uploadPercent} aria-label="Upload progress" />
          <p className="text-xs text-muted-foreground">
            Uploading… {doc.uploadPercent}%
          </p>
        </div>
      )}

      {/* Processing: OCR animation */}
      {doc.phase === "processing" && (
        <div className="flex items-center gap-2.5 px-3.5 pb-3.5 text-sm text-muted-foreground">
          <span className="relative grid size-7 place-items-center">
            <motion.span
              className="absolute inset-0 rounded-full border-2 border-transparent border-t-primary border-r-accent"
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
            />
            <ScanText className="size-3.5 text-primary" aria-hidden />
          </span>
          Reading the document (OCR)… this can take a few seconds
        </div>
      )}

      {/* Failed */}
      {doc.phase === "failed" && doc.errorMessage && (
        <p className="px-3.5 pb-3.5 text-xs text-destructive" role="alert">
          {doc.errorMessage}
        </p>
      )}

      {/* Analyzed: extraction summary + prefill */}
      {doc.phase === "analyzed" && extraction && (
        <div className="border-t border-border px-3.5 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
            >
              <ChevronDown
                className={cn("size-3.5 transition-transform", expanded && "rotate-180")}
                aria-hidden
              />
              {extraction.fields_found} fields read · {acceptedCount} ready to prefill
              {" · "}OCR confidence{" "}
              {Math.round((doc.extraction?.ocr.mean_confidence ?? 0) * 100)}%
            </button>
            {acceptedCount > 0 && (
              <Button
                size="sm"
                variant="gradient"
                loading={prefillBusy}
                onClick={() => onPrefill(doc)}
              >
                {prefillBusy ? (
                  "Prefilling…"
                ) : (
                  <>
                    <Sparkles aria-hidden /> Prefill my form
                  </>
                )}
              </Button>
            )}
          </div>

          {/* Universal extraction summary — every document type is welcome. */}
          <div className="mt-2 grid gap-x-4 gap-y-0.5 text-xs sm:grid-cols-2" role="status">
            <p className="text-muted-foreground">
              Detected:{" "}
              <span className="font-medium text-foreground">
                {detectedLabel ?? "Unrecognized document"}
              </span>
              {doc.docType && doc.docType.kind !== "unknown" && (
                <span> ({Math.round(doc.docType.confidence * 100)}% sure)</span>
              )}
            </p>
            <p className="text-muted-foreground">
              Extracted:{" "}
              <span className="font-medium text-foreground">
                {extraction.fields_found} field{extraction.fields_found === 1 ? "" : "s"}
              </span>
              {acceptedCount > 0 && <span> · {acceptedCount} validated</span>}
            </p>
            {missingCount > 0 && (
              <p className="text-muted-foreground">
                Still missing:{" "}
                <span className="font-medium text-foreground">
                  {missingCount} required field{missingCount === 1 ? "" : "s"}
                </span>{" "}
                — the interview will ask only for these.
              </p>
            )}
            {blankDocument && (
              <p className="text-muted-foreground sm:col-span-2">
                No readable values were found on this document — upload another
                document or continue the interview manually.
              </p>
            )}
          </div>

          <AnimatePresence initial={false}>
            {expanded && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.25, ease: "easeOut" }}
                className="overflow-hidden"
              >
                <ul className="mt-3 space-y-1.5">
                  {extraction.fields.map((field) => (
                    <li
                      key={field.field_id}
                      className="flex items-center justify-between gap-3 rounded-lg bg-muted/40 px-2.5 py-1.5"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-xs font-medium">
                          {labelOf(field.field_id)}
                        </span>
                        <span className="block truncate font-mono text-xs text-muted-foreground">
                          {field.value}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-2">
                        {!field.validation_result.valid && (
                          <span className="text-xs text-destructive">invalid</span>
                        )}
                        <ConfidenceBar value={field.confidence} />
                      </span>
                    </li>
                  ))}
                  {extraction.fields.length === 0 && (
                    <li className="text-xs text-muted-foreground">
                      No recognizable values were found on this document.
                    </li>
                  )}
                </ul>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* Screen-reader live status */}
      <span className="sr-only" role="status">
        {doc.phase === "uploading" && `Uploading ${doc.filename}`}
        {doc.phase === "processing" && `Reading ${doc.filename}`}
        {doc.phase === "analyzed" && `${doc.filename} analyzed`}
        {doc.phase === "failed" && `${doc.filename} failed`}
      </span>
    </motion.div>
  );
}

/** Small inline spinner used by list-level busy states. */
export function InlineSpinner({ label }: { label: string }) {
  return (
    <span className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden /> {label}
    </span>
  );
}
