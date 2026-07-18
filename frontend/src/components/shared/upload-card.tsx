"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { FileImage, FileText, UploadCloud, X } from "lucide-react";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { UploadedDocument } from "@/types";
import { formatBytes, formatDateTime } from "@/utils/format";

/**
 * Upload dropzone card — drag & drop + click-to-browse + keyboard operable.
 * Phase 9A: purely visual; `onFiles` receives the picked files so Phase 9B
 * can wire the real upload without touching this component.
 */
export function UploadCard({
  onFiles,
  className,
}: {
  onFiles?: (files: File[]) => void;
  className?: string;
}) {
  const [dragging, setDragging] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const handleFiles = (list: FileList | null) => {
    if (list && list.length > 0) onFiles?.(Array.from(list));
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Upload documents: drag and drop one or more files, or press Enter to browse"
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          inputRef.current?.click();
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        handleFiles(e.dataTransfer.files);
      }}
      className={cn(
        "group relative flex min-h-52 cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed p-6 text-center transition-all duration-300 sm:min-h-64",
        dragging
          ? "border-primary bg-primary/10 glow-primary"
          : "border-border bg-card/50 hover:border-primary/60 hover:bg-muted/40",
        className,
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.png,.jpg,.jpeg"
        multiple
        className="sr-only"
        onChange={(e) => handleFiles(e.target.files)}
        tabIndex={-1}
      />
      <motion.span
        animate={dragging ? { scale: 1.12, y: -4 } : { scale: 1, y: 0 }}
        className="grid size-14 place-items-center rounded-2xl bg-gradient-to-br from-primary/20 to-accent/20 text-primary"
      >
        <UploadCloud className="size-7" aria-hidden />
      </motion.span>
      <div className="space-y-1">
        <p className="text-sm font-medium sm:text-base">
          {dragging ? "Drop them here" : "Drag & drop your documents"}
        </p>
        <p className="text-xs text-muted-foreground sm:text-sm">
          or <span className="text-primary underline-offset-2 group-hover:underline">browse files</span> — select multiple at once · PDF, PNG or JPG, up to 10 MB each
        </p>
      </div>
    </div>
  );
}

/** A single uploaded document row with type icon, size, status and remove. */
export function UploadedFileCard({
  document,
  onRemove,
  className,
}: {
  document: UploadedDocument;
  onRemove?: (documentId: string) => void;
  className?: string;
}) {
  const isPdf = document.contentType === "application/pdf";
  const Icon = isPdf ? FileText : FileImage;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      className={cn(
        "flex items-center gap-3 rounded-xl border border-border bg-card p-3.5 shadow-sm",
        className,
      )}
    >
      <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-muted text-primary">
        <Icon className="size-5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{document.filename}</p>
        <p className="text-xs text-muted-foreground">
          {formatBytes(document.sizeBytes)}
          {document.pageCount ? ` · ${document.pageCount} pages` : ""} ·{" "}
          {formatDateTime(document.uploadedAt)}
        </p>
      </div>
      <StatusBadge status={document.status} className="hidden sm:inline-flex" />
      {onRemove && (
        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:text-destructive"
          aria-label={`Remove ${document.filename}`}
          onClick={() => onRemove(document.documentId)}
        >
          <X className="size-4" />
        </Button>
      )}
    </motion.div>
  );
}
