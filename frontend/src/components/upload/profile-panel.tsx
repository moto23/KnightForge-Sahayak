"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  CircleDashed,
  FileText,
  Layers,
  ShieldCheck,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { FieldConflictInfo, UnifiedProfileResponse } from "@/types/api";

/**
 * Unified KYC Profile panel (Phase 11 — Universal Document Intelligence).
 *
 * Renders the merge engine's output for the current session: merge status,
 * the canonical profile preview with per-field provenance (which document a
 * value came from), and conflict cards when documents disagree — the user
 * must explicitly choose; nothing is ever silently overwritten.
 */
export function ProfilePanel({
  profile,
  resolvingId,
  onResolve,
}: {
  profile: UnifiedProfileResponse | null;
  /** canonical_id of the conflict currently being resolved (busy state). */
  resolvingId: string | null;
  onResolve: (conflict: FieldConflictInfo, documentId: string) => void;
}) {
  if (!profile || profile.documents.length === 0) return null;

  const openConflicts = profile.conflicts.filter((c) => !c.resolved);
  const hasConflicts = openConflicts.length > 0;

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0 gap-3">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Layers className="size-4.5 text-accent" aria-hidden />
            Unified KYC profile
          </CardTitle>
          <CardDescription>
            One canonical profile merged from {profile.documents.length}{" "}
            document{profile.documents.length === 1 ? "" : "s"} — validated
            values win, then higher confidence, then earlier uploads.
            {profile.primary_form && (
              <>
                {" "}Final output:{" "}
                <span className="font-medium text-foreground">
                  {profile.primary_form.label}
                </span>
                .
              </>
            )}
          </CardDescription>
        </div>
        <Badge variant={hasConflicts ? "warning" : "success"}>
          {hasConflicts ? (
            <>
              <AlertTriangle aria-hidden />
              {openConflicts.length} conflict
              {openConflicts.length === 1 ? "" : "s"} to resolve
            </>
          ) : (
            <>
              <CheckCircle2 aria-hidden /> Merged
            </>
          )}
        </Badge>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Conflict cards — never silently overwritten */}
        <AnimatePresence initial={false}>
          {openConflicts.map((conflict) => (
            <motion.div
              key={conflict.canonical_id}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.97 }}
              className="rounded-xl border border-warning/40 bg-warning/5 p-4"
              role="group"
              aria-label={`Conflict on ${conflict.label}`}
            >
              <p className="flex items-center gap-2 text-sm font-semibold">
                <AlertTriangle className="size-4 text-warning" aria-hidden />
                Conflict detected — {conflict.label}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Your documents disagree. Please choose the correct value:
              </p>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {conflict.options.map((option) => (
                  <div
                    key={`${option.document_id}-${option.value}`}
                    className="flex flex-col justify-between gap-2 rounded-lg border border-border bg-card p-3"
                  >
                    <div className="min-w-0">
                      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <FileText className="size-3 shrink-0 text-accent" aria-hidden />
                        <span className="truncate">
                          {option.document_type_label} · {option.document_name}
                        </span>
                      </p>
                      <p className="mt-1 break-words font-mono text-sm">
                        {option.value}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      className="w-full"
                      loading={resolvingId === conflict.canonical_id}
                      onClick={() => onResolve(conflict, option.document_id)}
                    >
                      Use this value
                    </Button>
                  </div>
                ))}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {/* Unified profile preview */}
        {profile.fields.length > 0 ? (
          <ul className="grid gap-2 sm:grid-cols-2">
            {profile.fields.map((field) => (
              <li
                key={field.canonical_id}
                className="flex items-center justify-between gap-3 rounded-lg bg-muted/40 px-3 py-2"
              >
                <span className="min-w-0">
                  <span className="block truncate text-xs font-medium">
                    {field.label}
                    {field.resolved && (
                      <span className="ml-1.5 text-[10px] text-accent">
                        (your choice)
                      </span>
                    )}
                  </span>
                  <span className="block truncate font-mono text-xs text-muted-foreground">
                    {field.value}
                  </span>
                </span>
                <span
                  className="flex shrink-0 items-center gap-1.5"
                  title={`From ${field.source_type_label} (${field.source_document_name}) · confidence ${Math.round(field.confidence * 100)}%`}
                >
                  {field.validated ? (
                    <ShieldCheck
                      className="size-3.5 text-success"
                      aria-label="Validated"
                    />
                  ) : (
                    // Kept and shown, never silently dropped — but it failed
                    // validation, so it is not written into your form.
                    <AlertTriangle
                      className="size-3.5 text-warning"
                      aria-label="Read but could not be verified — not applied"
                    />
                  )}
                  <span
                    className={cn(
                      "rounded-full border border-border px-2 py-0.5 text-[10px] text-muted-foreground",
                    )}
                  >
                    {field.source_type_label} · {Math.round(field.confidence * 100)}%
                  </span>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            No canonical values could be merged yet — upload a filled form or
            an identity document.
          </p>
        )}

        {/* Missing canonical fields — exactly what the interview will ask */}
        {profile.missing_fields.length > 0 && (
          <div>
            <p className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
              <CircleDashed className="size-3.5" aria-hidden />
              Still missing ({profile.missing_fields.length}) — the interview
              asks only for these
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {profile.missing_fields.map((field) => (
                <span
                  key={field.canonical_id}
                  className="rounded-full border border-dashed border-border px-2.5 py-0.5 text-[11px] text-muted-foreground"
                >
                  {field.label}
                  {field.required && <span className="text-destructive"> *</span>}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Extended profile — extracted evidence outside the KYC form */}
        {profile.extra_fields.length > 0 && (
          <div>
            <p className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
              <Archive className="size-3.5" aria-hidden />
              Extra extracted fields ({profile.extra_fields.length}) — kept as
              evidence, nothing is discarded
            </p>
            <ul className="mt-2 grid gap-2 sm:grid-cols-2">
              {profile.extra_fields.map((extra) => (
                <li
                  key={`${extra.key}-${extra.source_document_id}-${extra.value}`}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border/60 px-3 py-2"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-xs font-medium">
                      {extra.label}
                    </span>
                    <span className="block truncate font-mono text-xs text-muted-foreground">
                      {extra.value}
                    </span>
                  </span>
                  <span
                    className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[10px] text-muted-foreground"
                    title={`From ${extra.source_document_name} · confidence ${Math.round(extra.confidence * 100)}%`}
                  >
                    {extra.source_type_label} · {Math.round(extra.confidence * 100)}%
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="text-xs text-muted-foreground">
          {profile.applied_field_ids.length} merged value
          {profile.applied_field_ids.length === 1 ? "" : "s"} applied to your
          interview session — only the remaining fields will be asked.
          {profile.fields.some((f) => !f.validated) && (
            <>
              {" "}
              Values marked{" "}
              <AlertTriangle
                className="inline size-3 text-warning align-[-1px]"
                aria-hidden
              />{" "}
              were read but couldn&apos;t be verified, so they weren&apos;t
              filled in — you can correct them in the interview.
            </>
          )}
        </p>
      </CardContent>
    </Card>
  );
}
